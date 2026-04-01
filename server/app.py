from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import ServerSettings
from .repository import Repository


class PairRequest(BaseModel):
    bootstrap_token: str = Field(min_length=1)
    device_label: str = Field(min_length=1)


class QueueDecisionRequest(BaseModel):
    note_id: Optional[int] = None
    reason: Optional[str] = None


def create_app(
    *,
    settings: ServerSettings | None = None,
    repository: Repository | None = None,
) -> FastAPI:
    settings = settings or ServerSettings.from_env()
    repository = repository or Repository(settings.sqlite_path)
    app = FastAPI(title="Cambridge Fetch Telegram Sync API", version="1.0")

    def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token.")
        return authorization.removeprefix("Bearer ").strip()

    @app.post("/api/v1/pair")
    def pair_device(body: PairRequest):
        if body.bootstrap_token != settings.pair_bootstrap_token:
            raise HTTPException(status_code=403, detail="Invalid bootstrap token.")
        return repository.pair_device(body.device_label)

    @app.put("/api/v1/manifest")
    def upload_manifest(payload: dict, token: str = Depends(bearer_token)):
        try:
            return repository.save_manifest(token, payload)
        except LookupError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @app.put("/api/v1/duplicate-index")
    def upload_duplicate_index(payload: dict, token: str = Depends(bearer_token)):
        try:
            return repository.save_duplicate_index(token, payload)
        except LookupError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @app.get("/api/v1/queue/pending")
    def pending_queue(limit: int = 25, token: str = Depends(bearer_token)):
        try:
            items = repository.list_pending(token, limit)
        except LookupError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {"items": items}

    @app.post("/api/v1/queue/{item_id}/complete")
    def complete_queue(item_id: int, body: QueueDecisionRequest, token: str = Depends(bearer_token)):
        if body.note_id is None:
            raise HTTPException(status_code=400, detail="note_id is required.")
        try:
            return repository.mark_complete(token, item_id, int(body.note_id))
        except LookupError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @app.post("/api/v1/queue/{item_id}/fail")
    def fail_queue(item_id: int, body: QueueDecisionRequest, token: str = Depends(bearer_token)):
        if not body.reason:
            raise HTTPException(status_code=400, detail="reason is required.")
        try:
            return repository.mark_failed(token, item_id, body.reason)
        except LookupError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    app.state.settings = settings
    app.state.repository = repository
    return app


app = create_app()
