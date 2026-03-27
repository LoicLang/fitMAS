from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from fitmas.api_support import FRONTEND_BUILD_DIR, FRONTEND_INDEX

router = APIRouter()


def _cache_headers(path: Path) -> dict[str, str]:
    if path.suffix in {".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff2"}:
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _resolve_frontend_path(raw_path: str) -> Path | None:
    if not FRONTEND_BUILD_DIR.exists():
        return None
    candidate = (FRONTEND_BUILD_DIR / raw_path).resolve()
    try:
        candidate.relative_to(FRONTEND_BUILD_DIR.resolve())
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/{full_path:path}", include_in_schema=False, response_model=None)
def frontend(full_path: str) -> FileResponse | HTMLResponse:
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")

    target = _resolve_frontend_path(full_path) if full_path else None
    if target is not None:
        return FileResponse(target, headers=_cache_headers(target))

    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX, headers=_cache_headers(FRONTEND_INDEX))

    return HTMLResponse(
        "<h1>Frontend build missing</h1><p>Run <code>cd frontend && npm install && npm run build</code> or use the Vite dev server.</p>",
        status_code=503,
    )
