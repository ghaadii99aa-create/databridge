"""Safe identifiers for dynamically created tables and columns.

User-supplied column names are never interpolated into SQL. Each source column gets a
generated key (snake_case, ASCII, unique within the dataset) that is validated against a
strict pattern before it is used as an identifier.
"""
from __future__ import annotations

import re
import unicodedata

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_RESERVED = {
    "select", "from", "where", "table", "order", "group", "user", "index", "limit", "offset",
    "and", "or", "not", "null", "default", "column", "check", "primary", "key", "references",
    "_row_id",
}


def is_safe_identifier(name: str) -> bool:
    return bool(_IDENT.match(name))


def assert_safe_identifier(name: str) -> str:
    if not is_safe_identifier(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def to_column_key(name: object, position: int) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)  # camelCase -> camel_Case
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    if not text or text.startswith("unnamed"):
        text = f"column_{position + 1}"
    if text[0].isdigit():
        text = f"c_{text}"
    text = text[:55]
    if text in _RESERVED:
        text = f"{text}_col"
    return text


def unique_column_keys(names: list[object]) -> list[str]:
    seen: dict[str, int] = {}
    keys: list[str] = []
    for i, name in enumerate(names):
        base = to_column_key(name, i)
        key = base
        n = seen.get(base, 0)
        while key in keys:
            n += 1
            key = f"{base}_{n}"
        seen[base] = n
        keys.append(assert_safe_identifier(key))
    return keys


def staging_table_name(dataset_id: int) -> str:
    return assert_safe_identifier(f"stg_{int(dataset_id)}")


def processed_table_name(run_id: int) -> str:
    return assert_safe_identifier(f"prc_{int(run_id)}")
