"""Measure DataBridge end to end against a running server.

Builds a larger SAMPLE file by repeating the synthetic retail dataset (with unique
transaction IDs), then times upload/ingestion, a full pipeline run and typical read
queries through the public API. Results are printed as a Markdown table.

Usage:
    python scripts/benchmark.py --rows 200000 --base http://127.0.0.1:8000

Numbers depend on the machine; record the hardware with the results.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import statistics
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data" / "retail_sales_sample.csv"


def build_csv(rows: int) -> bytes:
    with SAMPLE.open(encoding="utf-8") as fh:
        reader = list(csv.reader(fh))
    header, body = reader[0], reader[1:]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    for i in range(rows):
        r = list(body[i % len(body)])
        r[0] = f"TXN-{1_000_000 + i}" if i >= len(body) else r[0]
        w.writerow(r)
    return out.getvalue().encode()


def timed(fn):
    t = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - t) * 1000


def p50(fn, n: int = 7) -> float:
    return statistics.median(timed(fn)[1] for _ in range(n))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=200_000)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    c = httpx.Client(base_url=args.base, timeout=600)

    data = build_csv(args.rows)
    res, upload_ms = timed(lambda: c.post("/api/datasets", files={"file": ("benchmark_sample.csv", data, "text/csv")},
                                          data={"name": f"Benchmark {args.rows:,} rows (SAMPLE)"}))
    res.raise_for_status()
    ds = res.json()
    assert ds["status"] == "ready", ds

    pid = c.post("/api/pipelines", json={"dataset_id": ds["id"], "name": "Benchmark pipeline",
                                         "config": {"required_columns": ["transaction_id"]}}).json()["id"]
    t0 = time.perf_counter()
    run_id = c.post(f"/api/pipelines/{pid}/runs").json()["id"]
    while True:
        run = c.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.25)
    wall_ms = (time.perf_counter() - t0) * 1000
    assert run["status"] == "succeeded", run["error_message"]
    src = f"processed-{run_id}"
    filters = json.dumps([{"column": "region", "op": "eq", "value": "Central"}, {"column": "quantity", "op": "gte", "value": "3"}])

    reads = {
        "Explorer page (50 rows, unfiltered)": lambda: c.get("/api/explorer/rows", params={"source": src}),
        "Explorer page (2 filters + sort)": lambda: c.get("/api/explorer/rows", params={"source": src, "filters": filters,
                                                                                         "sort": "revenue_sar", "order": "desc"}),
        "Explorer text search": lambda: c.get("/api/explorer/rows", params={"source": src, "search": "Perfume"}),
        "Category chart (sum by region)": lambda: c.get("/api/analytics/category", params={"source": src, "column": "region",
                                                                                            "measure": "revenue_sar", "agg": "sum"}),
        "Monthly time series": lambda: c.get("/api/analytics/timeseries", params={"source": src, "column": "transaction_date"}),
        "Overview metrics": lambda: c.get("/api/overview"),
        "Health check": lambda: c.get("/api/health"),
    }
    _, first_stats = timed(lambda: c.get("/api/explorer/stats", params={"source": src}))
    cached_stats = p50(lambda: c.get("/api/explorer/stats", params={"source": src}))

    print(f"\n### Benchmark: {args.rows:,} rows, {len(data) / 1024 / 1024:.1f} MB CSV (SAMPLE data)\n")
    print("| Operation | Time |\n|---|---|")
    print(f"| Upload + validate + profile + stage + raw quality assessment | {upload_ms / 1000:.2f} s (server: {ds['ingest_duration_ms'] / 1000:.2f} s) |")
    print(f"| Pipeline run, all five stages | {run['duration_ms'] / 1000:.2f} s (wall clock incl. polling {wall_ms / 1000:.2f} s) |")
    for stage, ms in run["stage_timings_ms"].items():
        print(f"| &nbsp;&nbsp;{stage} | {ms / 1000:.2f} s |")
    print(f"| Rows extracted / loaded / rejected | {run['rows_extracted']:,} / {run['rows_loaded']:,} / {run['rows_rejected']:,} |")
    print(f"| Quality score source → processed | {run['quality_before']['score']} → {run['quality_after']['score']} |")
    print(f"| Column statistics, first request | {first_stats:.0f} ms |")
    print(f"| Column statistics, cached (median of 7) | {cached_stats:.1f} ms |")
    for label, fn in reads.items():
        print(f"| {label} (median of 7) | {p50(fn):.1f} ms |")

    c.delete(f"/api/datasets/{ds['id']}")


if __name__ == "__main__":
    main()
