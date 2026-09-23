"""FastAPI routes for the Workbench (product/07_API_CONTRACT.md)."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles

from .progress import BROKER, sse_format
from .backup import MAX_ARCHIVE_BYTES
from .service import ApiError, Service
from .sharing import PUBLIC_HEADERS, render_missing_article, render_public_article

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _export_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ApiError("VALIDATION", "include_title must be true or false.")


def create_app(service: Service | None = None) -> FastAPI:
    app = FastAPI(title="Narrative Writing Workbench", docs_url=None,
                  redoc_url=None)
    app.state.service = service or Service()

    # ------------------------------------------------------------ errors ----

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message,
                               "retryable": exc.retryable}})

    @app.exception_handler(Exception)
    async def _other(_: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"error": {
            "code": "INTERNAL", "message": "Something went wrong.",
            "retryable": True}})

    svc = lambda: app.state.service  # noqa: E731

    async def backup_body(request: Request) -> bytes:
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > MAX_ARCHIVE_BYTES:
                    raise ApiError("BACKUP_TOO_LARGE", "The backup file is too large.", 413)
            except ValueError:
                raise ApiError("VALIDATION", "Content-Length must be an integer.")
        content = await request.body()
        if len(content) > MAX_ARCHIVE_BYTES:
            raise ApiError("BACKUP_TOO_LARGE", "The backup file is too large.", 413)
        return content

    # ---------------------------------------------------------- projects ----

    @app.post("/projects")
    def create_project(body: dict):
        return svc().create_project(body.get("name", ""), body.get("description", ""))

    @app.get("/projects")
    def list_projects():
        return {"projects": svc().list_projects()}

    @app.get("/projects/{project_id}")
    def get_project(project_id: str):
        return svc().project_detail(project_id)

    @app.delete("/projects/{project_id}")
    def delete_project(project_id: str):
        return svc().delete_project(project_id)

    @app.post("/projects/{project_id}/sources")
    def create_source(project_id: str, body: dict):
        return svc().create_source(project_id, body.get("title", ""),
                                   body.get("type", "pasted_text"),
                                   body.get("content", ""))

    @app.patch("/sources/{source_id}")
    def update_source(source_id: str, body: dict):
        return svc().update_source(source_id, body.get("title"),
                                   body.get("content"))

    @app.delete("/sources/{source_id}")
    def delete_source(source_id: str):
        return svc().delete_source(source_id)

    # ------------------------------------------------------------- tasks ----

    @app.post("/tasks")
    def create_task(body: dict):
        return svc().create_task(body)

    @app.get("/tasks")
    def list_tasks():
        return {"tasks": svc().list_tasks()}

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        return svc().task_detail(task_id)

    @app.patch("/tasks/{task_id}")
    def update_task(task_id: str, body: dict):
        return svc().update_task(task_id, body)

    @app.delete("/tasks/{task_id}")
    def delete_task(task_id: str):
        return svc().delete_task(task_id)

    @app.post("/tasks/{task_id}/sources")
    def add_task_source(task_id: str, body: dict):
        return svc().add_task_source(task_id, body.get("title", ""),
                                     body.get("content", ""))

    @app.patch("/tasks/{task_id}/sources/{source_id}")
    def update_task_source(task_id: str, source_id: str, body: dict):
        return svc().update_task_source(task_id, source_id, body.get("title"),
                                        body.get("content"))

    @app.delete("/tasks/{task_id}/sources/{source_id}")
    def delete_task_source(task_id: str, source_id: str):
        return svc().delete_task_source(task_id, source_id)

    @app.post("/tasks/{task_id}/generate")
    def generate(task_id: str, body: dict | None = None):
        return svc().generate(task_id, body or {})

    @app.post("/tasks/{task_id}/angle-options")
    def angle_options(task_id: str, body: dict | None = None):
        return svc().angle_options(task_id, body or {})

    @app.get("/tasks/{task_id}/angle-options")
    def get_angle_options(task_id: str, discovery_id: str):
        return svc().get_angle_options(task_id, discovery_id)

    @app.post("/tasks/{task_id}/confirm-angle")
    def confirm_angle(task_id: str, body: dict):
        return svc().confirm_angle(task_id, body)

    @app.get("/tasks/{task_id}/meaning")
    def meaning(task_id: str):
        return svc().meaning_summary(task_id)

    @app.post("/tasks/{task_id}/rediscover-angle")
    def rediscover_angle(task_id: str, body: dict | None = None):
        return svc().rediscover_angle(task_id, body or {})

    @app.post("/tasks/{task_id}/regenerate")
    def regenerate(task_id: str, body: dict | None = None):
        return svc().regenerate(task_id, body or {})

    @app.post("/tasks/{task_id}/suggest-intent")
    def suggest_intent(task_id: str, body: dict | None = None):
        return svc().suggest_instruction(task_id, body or {})

    @app.get("/taxonomy")
    def taxonomy():
        return svc().taxonomy()

    @app.post("/topics/suggest")
    def suggest_topics(body: dict | None = None):
        return svc().suggest_topics(body or {})

    @app.get("/ideas")
    def list_ideas(q: str = "", status: str = "all", limit: int = 100):
        return svc().list_ideas(q, status, limit)

    @app.post("/ideas")
    def create_idea(body: dict):
        return svc().create_idea(body)

    @app.patch("/ideas/{idea_id}")
    def update_idea(idea_id: str, body: dict):
        return svc().update_idea(idea_id, body)

    @app.post("/ideas/import-legacy")
    def import_legacy_ideas(body: dict):
        return svc().import_legacy_ideas(body)

    @app.get("/tasks/{task_id}/operations/{operation_id}")
    def operation(task_id: str, operation_id: str):
        return svc().operation_detail(task_id, operation_id)

    @app.get("/tasks/{task_id}/progress")
    def progress(task_id: str, operation_id: str | None = None,
                 after_operation_id: str | None = None):
        """Replay one operation, then follow it. Transport lifetime is not a timeout."""
        svc().get_task(task_id)
        ch = BROKER.get(task_id)
        if operation_id:
            saved = svc().operation_detail(task_id, operation_id)
            if not ch or ch.operation_id != operation_id:
                def persisted():
                    for event in saved["events"]:
                        yield sse_format({**event, "operation_id": operation_id})
                    yield sse_format({"seq": -1, "kind": "eof", "operation_id": operation_id, "data": {"status": saved["status"]}})
                return StreamingResponse(persisted(), media_type="text/event-stream")
        else:
            # Legacy/start-before-POST clients get a short rendezvous window.
            for _ in range(20):
                latest = BROKER.get(task_id)
                if latest and (latest is not ch or (not latest.closed and latest.events)):
                    ch = latest
                    if not after_operation_id or ch.operation_id != after_operation_id:
                        break
                time.sleep(0.1)
            if after_operation_id and ch and ch.operation_id == after_operation_id:
                ch = None

        def gen():
            if not ch:
                yield sse_format({"seq": -1, "kind": "eof", "data": {}})
                return
            idx = 0
            while True:
                with ch.cond:
                    ch.cond.wait_for(lambda: idx < len(ch.events) or ch.closed, timeout=1)
                    batch, closed = ch.events[idx:], ch.closed
                    idx = len(ch.events)
                for event in batch:
                    yield sse_format(event)
                if closed:
                    yield sse_format({"seq": -1, "kind": "eof", "operation_id": ch.operation_id, "data": {}})
                    return
                if not batch:
                    yield ": heartbeat\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/tasks/{task_id}/review")
    def review(task_id: str):
        return svc().review(task_id)

    @app.post("/tasks/{task_id}/check-evidence")
    def check_evidence(task_id: str):
        return svc().check_evidence(task_id)

    @app.get("/tasks/{task_id}/evidence-check")
    def evidence_check(task_id: str):
        return svc().evidence_check(task_id)

    @app.post("/claim-links/{link_id}/confirm")
    def confirm_claim_link(link_id: str):
        return svc().confirm_claim_link(link_id)

    @app.post("/claim-links/{link_id}/dismiss")
    def dismiss_claim_link(link_id: str):
        return svc().dismiss_claim_link(link_id)

    @app.post("/tasks/{task_id}/reader-path-review")
    def review_reader_path(task_id: str):
        return svc().review_reader_path(task_id)

    @app.get("/tasks/{task_id}/reader-path-review")
    def reader_path_review(task_id: str):
        return svc().reader_path_review(task_id)

    @app.get("/tasks/{task_id}/revision-worklist")
    def revision_worklist(task_id: str):
        return svc().revision_worklist(task_id)

    @app.post("/revision-items/{item_id}/dismiss")
    def dismiss_revision_item(item_id: str):
        return svc().dismiss_revision_item(item_id)

    @app.get("/tasks/{task_id}/preserved-spans")
    def preserved_spans(task_id: str):
        return svc().list_preserved_spans(task_id)

    @app.post("/tasks/{task_id}/preserved-spans")
    def create_preserved_span(task_id: str, body: dict):
        return svc().create_preserved_span(task_id, body)

    @app.delete("/preserved-spans/{span_id}")
    def delete_preserved_span(span_id: str):
        return svc().delete_preserved_span(span_id)

    @app.post("/tasks/{task_id}/patch")
    def propose_patch(task_id: str, body: dict):
        return svc().propose_patch(task_id, body)

    @app.get("/tasks/{task_id}/writing-map")
    def writing_map(task_id: str):
        return svc().writing_map(task_id)

    # ------------------------------------------------------------ sharing ----

    @app.get("/tasks/{task_id}/share")
    def get_task_share(task_id: str):
        return svc().get_task_share(task_id)

    @app.post("/tasks/{task_id}/share")
    def create_task_share(task_id: str, body: dict | None = None):
        return svc().create_task_share(task_id, body or {})

    @app.delete("/tasks/{task_id}/share")
    def revoke_task_share(task_id: str):
        return svc().revoke_task_share(task_id)

    @app.get("/s/{token}/meta")
    def public_share_meta(token: str):
        try:
            return JSONResponse(svc().public_share(token), headers=PUBLIC_HEADERS)
        except ApiError as exc:
            if exc.status == 404:
                return JSONResponse(
                    {"error": {"code": "NOT_FOUND", "message": "Shared article not found.",
                               "retryable": False}},
                    status_code=404, headers=PUBLIC_HEADERS)
            raise

    @app.get("/s/{token}")
    def public_share_page(token: str, request: Request):
        try:
            share = svc().public_share(token)
        except ApiError as exc:
            if exc.status == 404:
                return HTMLResponse(render_missing_article(), status_code=404,
                                    headers=PUBLIC_HEADERS)
            raise
        return HTMLResponse(
            render_public_article(share, str(request.url).split("?", 1)[0]),
            headers=PUBLIC_HEADERS)

    @app.post("/tasks/{task_id}/checkpoint")
    def checkpoint(task_id: str, body: dict | None = None):
        return svc().checkpoint(task_id, (body or {}).get("expected_revision"))

    # ----------------------------------------------------------- patches ----

    @app.post("/patches/{patch_id}/accept")
    def accept_patch(patch_id: str):
        return svc().accept_patch(patch_id)

    @app.post("/patches/{patch_id}/reject")
    def reject_patch(patch_id: str):
        return svc().reject_patch(patch_id)

    # ---------------------------------------------------------- versions ----

    @app.get("/drafts/{draft_id}/versions")
    def list_versions(draft_id: str):
        return {"versions": svc().list_versions(draft_id)}

    @app.patch("/drafts/{draft_id}")
    def autosave(draft_id: str, body: dict):
        content = body.get("working_content")
        if not isinstance(content, str):
            raise ApiError("VALIDATION", "working_content must be text.")
        return svc().autosave(draft_id, content, body.get("expected_revision"))

    @app.get("/versions/{version_id}")
    def get_version(version_id: str):
        return svc().get_version(version_id)

    @app.get("/tasks/{task_id}/export")
    def export_task(task_id: str, format: str = "md",
                    expected_revision: str | None = None,
                    include_title: str = "true"):
        try:
            revision = int(expected_revision) if expected_revision is not None else None
        except ValueError:
            revision = expected_revision
        artifact = svc().export_task(
            task_id, format, revision, _export_bool(include_title))
        return Response(content=artifact.content, media_type=artifact.media_type,
                        headers=artifact.headers)

    @app.get("/versions/{version_id}/export")
    def export_version(version_id: str, format: str = "md",
                       include_title: str = "true"):
        artifact = svc().export_version(
            version_id, format, _export_bool(include_title))
        return Response(content=artifact.content, media_type=artifact.media_type,
                        headers=artifact.headers)

    @app.post("/versions/{version_id}/restore")
    def restore_version(version_id: str, body: dict | None = None):
        return svc().restore_version(version_id, (body or {}).get("expected_revision"))

    # ------------------------------------------------------------- misc ----

    @app.get("/settings")
    def settings():
        return svc().settings_view()

    @app.post("/settings")
    def update_settings(body: dict):
        return svc().update_settings(body)

    @app.get("/settings/providers")
    def settings_providers():
        return {"providers": svc().list_providers()}

    @app.post("/settings/models")
    def settings_models(body: dict):
        return svc().fetch_models(body)

    @app.post("/settings/test")
    def test_settings(body: dict):
        return svc().test_connection(body)

    # ----------------------------------------------------------- backups ----

    @app.get("/backups/export")
    def export_backup():
        artifact = svc().create_workspace_backup()
        return Response(content=artifact.content, media_type=artifact.media_type,
                        headers=artifact.headers)

    @app.post("/backups/inspect")
    async def inspect_backup(request: Request):
        return svc().inspect_workspace_backup(await backup_body(request))

    @app.post("/backups/restore")
    async def restore_backup(request: Request):
        return svc().restore_workspace_backup(await backup_body(request))

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
