"""Creation, loading and reading of generated row tables (stg_* and prc_*).

Tables are defined with SQLAlchemy Core so column types, the primary key and indexes are
explicit and portable across PostgreSQL and SQLite. Identifiers are validated before use.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, Index, Integer, MetaData, Table, Text, inspect, select,
)
from sqlalchemy.engine import Connection, Engine

from app.core.identifiers import assert_safe_identifier

ROW_ID = "_row_id"
INSERT_CHUNK = 5_000

SQL_TYPES = {
    "integer": BigInteger,
    "decimal": Float,
    "boolean": Boolean,
    "datetime": DateTime,
}
INDEXED_TYPES = {"category", "datetime", "identifier"}


def define_table(name: str, columns: list[tuple[str, str]], typed: bool, metadata: MetaData | None = None) -> Table:
    """columns: list of (key, inferred_type). Untyped (staging) tables store everything as text."""
    md = metadata or MetaData()
    cols = [Column(ROW_ID, Integer, primary_key=True, autoincrement=False)]
    for key, col_type in columns:
        sql_type = SQL_TYPES.get(col_type, Text) if typed else Text
        cols.append(Column(assert_safe_identifier(key), sql_type, nullable=True))
    table = Table(assert_safe_identifier(name), md, *cols)
    if typed:
        for i, (key, col_type) in enumerate(columns):
            if col_type in INDEXED_TYPES and i < 20:
                Index(f"ix_{name}_{key}"[:63], table.c[key])
    return table


def _py(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def create_and_load(conn: Connection, table: Table, frame: pd.DataFrame) -> int:
    """Create the table and bulk insert the frame (inside the caller's transaction)."""
    table.create(conn)
    keys = [c.name for c in table.columns if c.name != ROW_ID]
    frame = frame[keys]
    if conn.dialect.name == "postgresql":
        return _copy_postgres(conn, table, keys, frame)
    rows = 0
    for start in range(0, len(frame), INSERT_CHUNK):
        chunk = frame.iloc[start : start + INSERT_CHUNK]
        records = []
        for offset, values in enumerate(chunk.itertuples(index=False, name=None)):
            rec = {ROW_ID: start + offset + 1}
            rec.update({k: _py(v) for k, v in zip(keys, values)})
            records.append(rec)
        if records:
            conn.execute(table.insert(), records)
            rows += len(records)
    return rows


def _copy_postgres(conn: Connection, table: Table, keys: list[str], frame: pd.DataFrame) -> int:
    """Bulk load with COPY ... FROM STDIN on the caller's connection (same transaction).

    COPY streams rows in PostgreSQL's own protocol instead of one INSERT round trip per batch.
    Identifiers were validated by define_table; values are sent as data, never as SQL.
    """
    cols = ", ".join([f'"{ROW_ID}"', *(f'"{assert_safe_identifier(c)}"' for c in keys)])
    dbapi = conn.connection.dbapi_connection
    rows = 0
    with dbapi.cursor() as cur, cur.copy(f'COPY "{assert_safe_identifier(table.name)}" ({cols}) FROM STDIN') as copy:
        for i, values in enumerate(frame.itertuples(index=False, name=None), start=1):
            copy.write_row((i, *(_py(v) for v in values)))
            rows += 1
    return rows


def reflect(engine: Engine | Connection, name: str) -> Table:
    return Table(assert_safe_identifier(name), MetaData(), autoload_with=engine)


def table_exists(engine: Engine, name: str) -> bool:
    return inspect(engine).has_table(assert_safe_identifier(name))


def drop_table(engine: Engine, name: str | None) -> None:
    if not name:
        return
    if table_exists(engine, name):
        with engine.begin() as conn:
            reflect(conn, name).drop(conn)


def read_frame(engine: Engine, name: str, keys: list[str] | None = None, limit: int | None = None) -> pd.DataFrame:
    table = reflect(engine, name)
    cols = [table.c[k] for k in keys] if keys else [c for c in table.columns if c.name != ROW_ID]
    stmt = select(*cols).order_by(table.c[ROW_ID])
    if limit:
        stmt = stmt.limit(limit)
    with engine.connect() as conn:
        result = conn.execute(stmt)
        frame = pd.DataFrame(result.fetchall(), columns=[c.name for c in cols])
    return frame


def jsonable(value: Any) -> Any:
    value = _py(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ").replace(" 00:00:00", "") if value.time() == datetime.min.time() else value.isoformat(sep=" ")
    if isinstance(value, float):
        return round(value, 6)
    return value
