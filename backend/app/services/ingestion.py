"""File ingestion: validate, store, parse, profile, stage and assess an uploaded dataset."""
from __future__ import annotations

import csv
import io
import logging
import time
import zipfile
from pathlib import Path
from typing import BinaryIO

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import LimitExceeded, NotFound, UnsupportedFile, ValidationFailed
from app.core.identifiers import staging_table_name, unique_column_keys
from app.core.storage import remove_file, save_stream
from app.core.visitor import SYSTEM_SCOPE, Scope
from app.db import get_engine
from app.models import Dataset, DatasetColumn, ProcessedDataset
from app.services import tables
from app.services import typing as T
from app.services.quality.service import assess_dataset

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".csv": "csv", ".xlsx": "xlsx"}
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def _validate_name(filename: str | None) -> tuple[str, str]:
    if not filename:
        raise ValidationFailed("A file name is required")
    name = Path(filename).name[:255]
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFile(
            f"'{ext or 'no extension'}' files are not supported. Upload a .csv or .xlsx file.",
            {"allowed": sorted(ALLOWED_EXTENSIONS)},
        )
    return name, ext


def _sniff_content(path: Path, fmt: str) -> None:
    head = path.open("rb").read(8192)
    if fmt == "xlsx":
        if not head.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(path):
            raise UnsupportedFile("The file has an .xlsx extension but is not a valid Excel workbook.")
        with zipfile.ZipFile(path) as zf:
            if "[Content_Types].xml" not in zf.namelist():
                raise UnsupportedFile("The workbook is missing required Excel metadata.")
    else:
        if b"\x00" in head:
            raise UnsupportedFile("The file has a .csv extension but contains binary data.")


def read_csv(path: Path) -> tuple[pd.DataFrame, str, str]:
    last_error: Exception | None = None
    for enc in ENCODINGS:
        try:
            with path.open("r", encoding=enc, newline="") as fh:
                sample = fh.read(64_000)
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
            frame = pd.read_csv(
                path, sep=delimiter, dtype=str, keep_default_na=False, na_filter=False,
                encoding=enc, skipinitialspace=False, on_bad_lines="error",
            )
            return frame, enc, delimiter
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.ParserError as exc:
            raise ValidationFailed(f"The CSV file could not be parsed: {str(exc).splitlines()[0]}") from exc
        except pd.errors.EmptyDataError as exc:
            raise ValidationFailed("The CSV file has no columns.") from exc
    raise ValidationFailed(f"Unsupported text encoding ({last_error}).")


def read_excel(path: Path) -> tuple[pd.DataFrame, str]:
    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str, engine="openpyxl")
    except Exception as exc:  # openpyxl raises a variety of errors for corrupt files
        raise ValidationFailed(f"The Excel file could not be read: {exc}") from exc
    for sheet_name, frame in sheets.items():
        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        if not frame.empty:
            return frame.fillna(""), str(sheet_name)
    raise ValidationFailed("The workbook does not contain any data.")


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame.astype(str).replace({"nan": ""})
    # drop rows where every cell is blank (common at the end of exported sheets)
    blank = frame.apply(lambda s: s.str.strip() == "").all(axis=1)
    return frame[~blank].reset_index(drop=True)


def ingest_upload(
    session: Session, stream: BinaryIO, filename: str | None, name: str | None = None,
    description: str | None = None, is_sample: bool = False, owner_id: str | None = None,
) -> Dataset:
    settings = get_settings()
    original, ext = _validate_name(filename)
    fmt = ALLOWED_EXTENSIONS[ext]
    stored = save_stream(stream, settings.upload_dir, ext, settings.max_upload_bytes)
    try:
        _sniff_content(stored.path, fmt)
    except Exception:
        stored.path.unlink(missing_ok=True)
        raise

    dataset = Dataset(
        name=(name or Path(original).stem)[:200], description=description,
        original_filename=original, stored_filename=stored.path.name, file_format=fmt,
        file_size_bytes=stored.size_bytes, sha256=stored.sha256, status="processing", is_sample=is_sample,
        owner_id=owner_id,
    )
    session.add(dataset)
    session.commit()
    log.info("dataset stored", extra={"dataset_id": dataset.id, "bytes": stored.size_bytes})

    started = time.perf_counter()
    try:
        _process(session, dataset, stored.path)
        dataset.status = "ready"
    except LimitExceeded:
        # Over-limit files are rejected outright: no record, no stored file, no staged rows.
        session.rollback()
        session.delete(dataset)
        session.commit()
        stored.path.unlink(missing_ok=True)
        raise
    except ValidationFailed as exc:
        session.rollback()
        dataset.status = "failed"
        dataset.error_message = exc.message
    except Exception as exc:  # unexpected — keep the record, log the trace
        session.rollback()
        log.exception("ingestion failed", extra={"dataset_id": dataset.id})
        dataset.status = "failed"
        dataset.error_message = f"Unexpected error while processing the file ({type(exc).__name__})."
    dataset.ingest_duration_ms = int((time.perf_counter() - started) * 1000)
    session.add(dataset)
    session.commit()
    if dataset.status == "failed":
        tables.drop_table(get_engine(), dataset.staging_table)
    return dataset


def _process(session: Session, dataset: Dataset, path: Path) -> None:
    settings = get_settings()
    if dataset.file_format == "csv":
        frame, encoding, delimiter = read_csv(path)
        dataset.encoding, dataset.delimiter = encoding, delimiter
    else:
        frame, sheet = read_excel(path)
        dataset.sheet_name = sheet
    frame = _normalise_frame(frame)

    if frame.shape[1] == 0:
        raise ValidationFailed("No columns were found in the file.")
    if frame.shape[0] == 0:
        raise ValidationFailed("The file has a header row but no data rows.")
    if frame.shape[1] > settings.max_columns:
        raise LimitExceeded(f"The file has {frame.shape[1]} columns; the limit is {settings.max_columns}.",
                            {"columns": frame.shape[1], "limit": settings.max_columns})
    if frame.shape[0] > settings.max_rows:
        raise LimitExceeded(f"The file has {frame.shape[0]:,} rows; the limit is {settings.max_rows:,}. "
                            "Upload a smaller extract.", {"rows": frame.shape[0], "limit": settings.max_rows})

    names = list(frame.columns)
    keys = unique_column_keys(names)
    frame.columns = keys

    columns: list[DatasetColumn] = []
    for pos, (key, original) in enumerate(zip(keys, names)):
        s = frame[key]
        missing = T.missing_mask(s)
        present = s[~missing]
        columns.append(DatasetColumn(
            position=pos, name=original[:255] or f"Column {pos + 1}", key=key,
            inferred_type=T.infer_type(s, original),
            null_count=int(missing.sum()), distinct_count=int(present.nunique()),
            sample_values=[str(v) for v in present.unique()[:5]],
        ))
    dataset.columns = columns
    dataset.row_count, dataset.column_count = frame.shape
    dataset.staging_table = staging_table_name(dataset.id)

    # Metadata and staged rows are written on the same connection, in one transaction:
    # if anything fails, neither the column profile nor a half-loaded table remains.
    session.flush()
    table = tables.define_table(dataset.staging_table, [(c.key, c.inferred_type) for c in columns], typed=False)
    tables.create_and_load(session.connection(), table, frame)
    assess_dataset(session, dataset, frame=frame)


def get_dataset(session: Session, dataset_id: int) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise NotFound(f"Dataset {dataset_id} does not exist")
    return dataset


def list_datasets(session: Session, search: str | None = None, status: str | None = None,
                  scope: Scope = SYSTEM_SCOPE) -> list[Dataset]:
    stmt = (select(Dataset).where(scope.visible(Dataset.owner_id))
            .order_by(Dataset.is_sample.desc(), Dataset.created_at.desc(), Dataset.id.desc()))
    if search:
        stmt = stmt.where(Dataset.name.ilike(f"%{search.strip()}%"))
    if status:
        stmt = stmt.where(Dataset.status == status)
    return list(session.scalars(stmt))


def delete_dataset(session: Session, dataset_id: int) -> None:
    dataset = get_dataset(session, dataset_id)
    engine = get_engine()
    outputs = session.scalars(select(ProcessedDataset.table_name).where(ProcessedDataset.dataset_id == dataset_id)).all()
    for table_name in outputs:
        tables.drop_table(engine, table_name)
    tables.drop_table(engine, dataset.staging_table)
    remove_file(get_settings().upload_dir, dataset.stored_filename)
    session.delete(dataset)
    session.commit()


def preview(session: Session, dataset_id: int, limit: int = 50) -> dict:
    dataset = get_dataset(session, dataset_id)
    if dataset.status != "ready" or not dataset.staging_table:
        raise ValidationFailed("Preview is only available for datasets that were ingested successfully.")
    frame = tables.read_frame(get_engine(), dataset.staging_table, limit=limit)
    return {
        "columns": [{"key": c.key, "name": c.name, "type": c.inferred_type} for c in dataset.columns],
        "rows": frame.to_dict(orient="records"),
        "total_rows": dataset.row_count,
    }

