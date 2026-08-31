"""FastAPI routes for the Workbench (product/07_API_CONTRACT.md)."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .progress import BROKER, sse_format
from .service import ApiError, Service

STATIC_DIR = Path(__file__).resolve().parent / "static"


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

    @app.post("/projects/{project_id}/sources")
    def create_source(project_id: str, body: dict):
        return svc().create_source(project_id, body.get("title", ""),
                                   body.get("type", "pasted_text"),
                                   body.get("content", ""))

    # ------------------------------------------------------------- tasks ----

    @app.post("/tasks")
    def create_task(body: dict):
        return svc().create_task(body)

    @app.get("/tasks")
    def list_tasks():
        return {"tasks": svc().db.q(
            "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT 50")}

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        return svc().task_detail(task_id)

    @app.patch("/tasks/{task_id}")
    def update_task(task_id: str, body: dict):
        return svc().update_task(task_id, body)

    @app.post("/tasks/{task_id}/sources")
    def add_task_source(task_id: str, body: dict):
        return svc().add_task_source(task_id, body.get("title", ""),
                                     body.get("content", ""))

    @app.post("/tasks/{task_id}/generate")
    def generate(task_id: str, body: dict | None = None):
        return svc().generate(task_id, body or {})

    @app.get("/tasks/{task_id}/meaning")
    def meaning(task_id: str):
        return svc().meaning_summary(task_id)

    @app.post("/tasks/{task_id}/rediscover-angle")
    def rediscover_angle(task_id: str, body: dict | None = None):
        return svc().rediscover_angle(task_id, body or {})

    @app.post("/tasks/{task_id}/regenerate")
    def regenerate(task_id: str, body: dict | None = None):
        return svc().regenerate(task_id, body or {})

    @app.get("/tasks/{task_id}/progress")
    def progress(task_id: str):
        """Server-Sent Events stream of generation stage/angle events.

        Replays buffered history (so a late/refreshing client catches up),
        then follows live until the channel closes.
        """
        svc().get_task(task_id)  # 404 guard
        # Two situations involve a *closed* channel with events:
        #  (a) a second run is about to start (client opens SSE a few ms
        #      before POST resets the channel) -> we must NOT replay the
        #      previous run; wait for the swap;
        #  (b) a late subscriber after completion -> replay is desired.
        # Distinguish by watching for the channel object to change; if no
        # new run appears within the grace window, fall through to replay.
        ch = BROKER.channel(task_id)
        for _ in range(20):
            cur = BROKER.channel(task_id)
            if cur is not ch:
                ch = cur
            if not ch.closed and (ch.events or
                                  svc().get_task(task_id)["status"] == "generating"):
                break
            time.sleep(0.1)
        if not ch.events and svc().get_task(task_id)["status"] != "generating":
            async def _eof():
                yield 'event: eof\ndata: {"seq":-1,"kind":"eof"}\n\n'
            return StreamingResponse(_eof(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache"})

        def gen():
            cur, idx = ch, 0
            deadline = time.monotonic() + 300  # cap on a stuck channel
            while True:
                latest = BROKER.channel(task_id)
                if latest is not cur:          # new run reset the channel
                    cur, idx = latest, 0
                with cur.cond:
                    cur.cond.wait_for(
                        lambda: idx < len(cur.events) or cur.closed
                        or BROKER.channel(task_id) is not cur,
                        timeout=0.5)
                    batch = cur.events[idx:]
                    idx = len(cur.events)
                    closed = cur.closed
                for ev in batch:
                    yield sse_format(ev)
                if BROKER.channel(task_id) is not cur:
                    continue                   # swapped mid-wait: follow the new run
                if closed and idx >= len(cur.events):
                    yield 'event: eof\ndata: {"seq":-1,"kind":"eof"}\n\n'
                    return
                if time.monotonic() > deadline:
                    return

        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers=headers)

    @app.post("/tasks/{task_id}/review")
    def review(task_id: str):
        return svc().review(task_id)

    @app.post("/tasks/{task_id}/patch")
    def propose_patch(task_id: str, body: dict):
        return svc().propose_patch(task_id, body)

    @app.get("/tasks/{task_id}/writing-map")
    def writing_map(task_id: str):
        return svc().writing_map(task_id)

    @app.post("/tasks/{task_id}/checkpoint")
    def checkpoint(task_id: str):
        return svc().checkpoint(task_id)

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
        return svc().autosave(draft_id, content)

    @app.get("/versions/{version_id}")
    def get_version(version_id: str):
        return svc().get_version(version_id)

    @app.post("/versions/{version_id}/restore")
    def restore_version(version_id: str):
        return svc().restore_version(version_id)

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

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
