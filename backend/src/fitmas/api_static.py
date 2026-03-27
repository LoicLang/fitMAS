from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from fitmas.api_support import FRONTEND_DIR, FRONTEND_INDEX

router = APIRouter()


@router.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(
        FRONTEND_INDEX,
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@router.get("/manifest.json", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / "manifest.json",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
