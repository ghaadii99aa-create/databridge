"""AI Data Analyst.

Every question gets a statistical answer computed directly from the data. If an AI provider
is configured, the same dataset profile is sent to it and its answer is returned alongside,
clearly labelled. The profile — not the full dataset — is what leaves the server, and it is
returned to the client so the user can see exactly what was shared.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.errors import ProviderError
from app.services import explorer
from app.services import typing as T
from app.services.ai.providers import get_provider, provider_status
from app.services.quality.service import latest_assessment

SAMPLE_ROWS = 5
SYSTEM_PROMPT = (
    "You are a careful data analyst inside a data engineering tool. You receive a JSON profile of a "
    "dataset: column statistics, data quality findings and a few sample rows. Answer the user's question "
    "using only this profile. Quote concrete numbers from it. If the profile cannot answer the question, "
    "say what additional analysis would be needed. Do not invent values. Be concise; use short paragraphs "
    "or bullet points. Write for a business audience."
)

INTENTS: dict[str, re.Pattern[str]] = {
    "missing": re.compile(r"missing|null|empty|blank|incomplete|gap", re.I),
    "duplicates": re.compile(r"duplicat|repeated|unique", re.I),
    "unusual": re.compile(r"unusual|outlier|anomal|strange|extreme|odd", re.I),
    "quality": re.compile(r"quality|clean|issue|problem|error|invalid", re.I),
    "patterns": re.compile(r"pattern|trend|distribut|correlat|relationship", re.I),
    "insights": re.compile(r"insight|finding|important|business|key|recommend", re.I),
    "summary": re.compile(r"summar|overview|describe|explain|simple|what is", re.I),
}


def build_profile(session: Session, source_id: str) -> dict[str, Any]:
    stats = explorer.column_stats(session, source_id)
    src = stats["source"]
    assessment = (latest_assessment(session, src["dataset_id"], "processed", run_id=src["run_id"])
                  if src["kind"] == "processed" else latest_assessment(session, src["dataset_id"], "raw"))
    sample = explorer.query_rows(session, source_id, page=1, page_size=SAMPLE_ROWS)["rows"]
    columns = []
    for c in stats["columns"]:
        item = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items()
                if k in ("name", "type", "count", "missing", "distinct", "mean", "median", "min", "max", "std",
                         "sum", "span_days", "top_values")}
        if c["type"] in ("identifier", "text"):
            item.pop("top_values", None)  # identifiers/free text carry no aggregate meaning; don't share them
        elif "top_values" in item:
            item["top_values"] = item["top_values"][:5]
        columns.append(item)
    return {
        "dataset": src["dataset_name"],
        "source": f"processed output of pipeline run #{src['run_id']}" if src["kind"] == "processed" else "raw upload, before cleaning",
        "rows": src["row_count"],
        "columns": columns,
        "quality": None if not assessment else {
            "score": assessment.score, "completeness": assessment.completeness, "validity": assessment.validity,
            "uniqueness": assessment.uniqueness, "consistency": assessment.consistency,
            "affected_rows": assessment.affected_rows,
            "issues": [{"check": i.check_code, "severity": i.severity, "column": i.column_name,
                        "rows": i.affected_rows, "message": i.message} for i in assessment.issues[:12]],
        },
        "sample_rows": [{k: v for k, v in r.items() if k != "_row_id"} for r in sample],
    }


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1000 or float(v).is_integer() else f"{v:,.2f}"


def statistical_answer(profile: dict[str, Any], question: str) -> list[dict[str, str]]:
    """Deterministic findings chosen by the question's intent. No language model involved."""
    intents = [k for k, rx in INTENTS.items() if rx.search(question)] or ["summary", "insights"]
    rows = profile["rows"]
    cols = profile["columns"]
    quality = profile.get("quality") or {}
    issues = quality.get("issues", [])
    out: list[dict[str, str]] = []

    if "summary" in intents or "insights" in intents:
        types: dict[str, int] = {}
        for c in cols:
            types[c["type"]] = types.get(c["type"], 0) + 1
        parts = ", ".join(f"{n} {t}" for t, n in sorted(types.items(), key=lambda x: -x[1]))
        text = f"{profile['dataset']}, {profile['source']}, has {rows:,} rows and {len(cols)} columns: {parts}."
        if quality:
            text += f" Its quality score is {quality['score']}/100; {quality['affected_rows']:,} rows have at least one issue."
        out.append({"title": "Dataset overview", "detail": text})
        dates = [c for c in cols if c["type"] == "datetime" and c.get("min")]
        for d in dates[:1]:
            out.append({"title": f"Time coverage — {d['name']}",
                        "detail": f"Records run from {d['min'][:10]} to {d['max'][:10]} ({d.get('span_days', 0)} days)."})

    if "missing" in intents or "quality" in intents:
        missing = sorted([c for c in cols if c.get("missing")], key=lambda c: -c["missing"])
        if missing:
            lines = "; ".join(f"{c['name']}: {c['missing']:,} ({c['missing'] / rows:.1%})" for c in missing[:5])
            out.append({"title": "Columns with missing values", "detail": lines + "."})
        else:
            out.append({"title": "Missing values", "detail": "No column has missing values."})

    if "duplicates" in intents or "quality" in intents:
        dup = [i for i in issues if i["check"] in ("duplicate_rows", "duplicate_identifier")]
        out.append({"title": "Duplicates", "detail": " ".join(i["message"] for i in dup) if dup
                    else "No duplicate records were detected."})

    if "quality" in intents:
        other = [i for i in issues if i["check"] not in ("missing_values", "duplicate_rows", "duplicate_identifier", "outliers")]
        if other:
            out.append({"title": "Other quality findings", "detail": " ".join(i["message"] for i in other[:5])})

    if "unusual" in intents:
        outl = [i for i in issues if i["check"] in ("outliers", "unexpected_negative", "invalid_type")]
        if outl:
            out.append({"title": "Unusual records", "detail": " ".join(i["message"] for i in outl[:5])})
        else:
            out.append({"title": "Unusual records", "detail": "No outliers, negative quantities or invalid values were flagged."})

    if "patterns" in intents or "insights" in intents:
        numeric = [c for c in cols if c["type"] in T.NUMERIC_TYPES and c.get("mean") is not None]
        for c in numeric[:3]:
            skew = ""
            if c.get("median") and c["mean"] > 1.5 * c["median"]:
                skew = " The mean is well above the median, so a small number of large values drive the total."
            out.append({"title": f"{c['name']} distribution",
                        "detail": f"Ranges from {_fmt(c['min'])} to {_fmt(c['max'])}; median {_fmt(c['median'])}, "
                                  f"mean {_fmt(c['mean'])}" + (f", total {_fmt(c['sum'])}" if c.get("sum") else "") + f".{skew}"})
        cats = [c for c in cols if c["type"] == "category" and c.get("top_values")]
        for c in cats[:3]:
            top = c["top_values"][0]
            share = top["count"] / max(1, c["count"])
            out.append({"title": f"{c['name']} concentration",
                        "detail": f"{c['distinct']} distinct values; the largest is '{top['value']}' with "
                                  f"{top['count']:,} rows ({share:.0%})."})

    if "insights" in intents and quality and quality.get("score", 100) < 95:
        out.append({"title": "Recommendation", "detail":
                    "Run a cleaning pipeline before reporting on this data; the quality findings above would distort "
                    "totals and category breakdowns."})
    return out


def ask(session: Session, source_id: str, question: str, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    profile = build_profile(session, source_id)
    status = provider_status()
    result: dict[str, Any] = {
        "question": question,
        "statistical": {"label": "Statistical analysis (computed by DataBridge, no AI)",
                        "findings": statistical_answer(profile, question)},
        "ai": None,
        "ai_status": status,
        "shared_profile": profile if status["configured"] else None,
    }
    provider = get_provider(transport=transport)
    if provider is None:
        return result
    prompt = f"Dataset profile (JSON):\n{json.dumps(profile, default=str)}\n\nQuestion: {question}"
    try:
        completion = provider.complete(SYSTEM_PROMPT, prompt)
        result["ai"] = {"label": f"AI-generated analysis ({provider.name}, {completion.model})",
                        "text": completion.text, "model": completion.model,
                        "usage": {"input_tokens": completion.input_tokens, "output_tokens": completion.output_tokens},
                        "error": None}
    except ProviderError as exc:
        result["ai"] = {"label": f"AI-generated analysis ({provider.name})", "text": None, "model": provider.model,
                        "usage": None, "error": exc.message}
    return result
