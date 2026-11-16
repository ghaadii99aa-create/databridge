from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.errors import LimitExceeded, NotFound
from app.core.storage import safe_child
from app.core.visitor import Scope, ScopeDep
from app.models import Dataset, Pipeline
from app.schemas import AssessmentOut, DatasetDetail, DatasetOut, DatasetUpdate, QualityBrief
from app.services import access, demo, ingestion
from app.services.quality import service as quality
from app.services.quality.engine import methodology

router = APIRouter(prefix="/datasets", tags=["datasets"])
SAMPLE_FILE = demo.SAMPLE_FILE


def _out(session: SessionDep, scope: Scope, ds: Dataset, detail: bool = False) -> DatasetOut:
    model = DatasetDetail if detail else DatasetOut
    out = model.model_validate(ds)
    latest = quality.latest_assessment(session, ds.id, "raw")
    out.latest_quality = QualityBrief.model_validate(latest) if latest else None
    out.pipeline_count = session.scalar(
        select(func.count(Pipeline.id)).where(Pipeline.dataset_id == ds.id, scope.visible(Pipeline.owner_id))) or 0
    out.read_only = scope.read_only(ds.owner_id)
    return out


@router.get("", response_model=list[DatasetOut])
def list_datasets(session: SessionDep, scope: ScopeDep, search: str | None = Query(None, max_length=100),
                  status_: str | None = Query(None, alias="status", pattern="^(processing|ready|failed)$")):
    return [_out(session, scope, d) for d in ingestion.list_datasets(session, search, status_, scope)]


@router.post("", response_model=DatasetDetail, status_code=status.HTTP_201_CREATED)
def upload_dataset(session: SessionDep, scope: ScopeDep, file: UploadFile = File(...),
                   name: str | None = Form(None, max_length=200), description: str | None = Form(None, max_length=2000)):
    """Upload a CSV or XLSX file. The response includes the ingestion status; a file that
    is stored but cannot be parsed is returned with status 'failed' and an error message.
    Files over the size, row or column limits are rejected with 413 and nothing is kept."""
    if scope.demo:
        owned = session.scalar(select(func.count(Dataset.id)).where(Dataset.owner_id == scope.visitor_id)) or 0
        limit = get_settings().demo_max_datasets_per_visitor
        if owned >= limit:
            raise LimitExceeded(f"The public demo keeps up to {limit} uploaded datasets per visitor. "
                                "Delete one of yours to upload another.", {"limit": limit})
    ds = ingestion.ingest_upload(session, file.file, file.filename, name, description, owner_id=scope.owner_for_new)
    return _out(session, scope, ds, detail=True)


@router.post("/sample", response_model=DatasetDetail, status_code=status.HTTP_201_CREATED)
def load_sample(session: SessionDep, scope: ScopeDep, response: Response):
    """Load the bundled, clearly labelled SAMPLE retail dataset for the demonstration workflow.
    In demo mode the shared sample is preloaded, so this returns it instead of adding a copy."""
    if scope.demo:
        existing = demo.system_sample(session)
        if existing:
            response.status_code = status.HTTP_200_OK
            return _out(session, scope, existing, detail=True)
    path = get_settings().sample_dir / SAMPLE_FILE
    if not path.exists():
        raise NotFound("The sample dataset file is not available on the server. Run scripts/generate_sample_data.py.")
    with path.open("rb") as fh:
        ds = ingestion.ingest_upload(session, fh, SAMPLE_FILE, demo.SAMPLE_NAME, demo.SAMPLE_DESCRIPTION,
                                     is_sample=True, owner_id=scope.owner_for_new)
    return _out(session, scope, ds, detail=True)


@router.get("/limits")
def upload_limits(session: SessionDep) -> dict:
    return {**demo.demo_info(session), "allowed_extensions": sorted(ingestion.ALLOWED_EXTENSIONS)}


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: int, session: SessionDep, scope: ScopeDep):
    return _out(session, scope, access.dataset(session, scope, dataset_id), detail=True)


@router.patch("/{dataset_id}", response_model=DatasetDetail)
def update_dataset(dataset_id: int, body: DatasetUpdate, session: SessionDep, scope: ScopeDep):
    ds = access.dataset(session, scope, dataset_id, modify=True)
    ds.name, ds.description = body.name.strip(), body.description
    session.commit()
    return _out(session, scope, ds, detail=True)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_dataset(dataset_id: int, session: SessionDep, scope: ScopeDep) -> None:
    access.dataset(session, scope, dataset_id, modify=True)
    ingestion.delete_dataset(session, dataset_id)


@router.get("/{dataset_id}/preview")
def preview(dataset_id: int, session: SessionDep, scope: ScopeDep, limit: int = Query(50, ge=1, le=200)) -> dict:
    access.dataset(session, scope, dataset_id)
    return ingestion.preview(session, dataset_id, limit)


@router.get("/{dataset_id}/download")
def download_original(dataset_id: int, session: SessionDep, scope: ScopeDep) -> FileResponse:
    ds = access.dataset(session, scope, dataset_id)
    path = safe_child(get_settings().upload_dir, ds.stored_filename)
    if not path.exists():
        raise NotFound("The original file is no longer stored")
    return FileResponse(path, filename=ds.original_filename)


# ---- quality -------------------------------------------------------------------------

@router.get("/{dataset_id}/quality", response_model=AssessmentOut | None)
def latest_quality(dataset_id: int, session: SessionDep, scope: ScopeDep):
    access.dataset(session, scope, dataset_id)
    return quality.latest_assessment(session, dataset_id, "raw")


@router.post("/{dataset_id}/quality", response_model=AssessmentOut, status_code=status.HTTP_201_CREATED)
def run_quality(dataset_id: int, session: SessionDep, scope: ScopeDep):
    ds = access.dataset(session, scope, dataset_id, modify=True)
    a = quality.assess_dataset(session, ds)
    session.commit()
    return quality.get_assessment(session, a.id)


@router.get("/{dataset_id}/quality/history", response_model=list[QualityBrief])
def quality_history(dataset_id: int, session: SessionDep, scope: ScopeDep):
    access.dataset(session, scope, dataset_id)
    return quality.history(session, dataset_id, scope)


quality_router = APIRouter(prefix="/quality", tags=["quality"])


@quality_router.get("/methodology")
def quality_methodology() -> dict:
    return methodology()


@quality_router.get("/assessments/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: int, session: SessionDep, scope: ScopeDep):
    access.assessment(session, scope, assessment_id)
    return quality.get_assessment(session, assessment_id)
