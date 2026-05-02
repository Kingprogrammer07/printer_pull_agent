import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routers import agents, health, jobs, printer
from app.core.config import settings
from app.core.database import initialize_database
from app.core.logger import get_logger
from app.repositories.job_repository import JobRepository
from app.services.agent_connection_manager import AgentConnectionManager
from app.services.archive_service import cleanup_archive


logger = get_logger(__name__)
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def format_datetime(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        if "T" in text:
            return text.replace("T", " ").split("+", 1)[0].split("Z", 1)[0]
        return text


templates.env.filters["datetime_human"] = format_datetime


def redirect_with_notice(request: Request, notice: str, kind: str = "ok") -> RedirectResponse:
    target = request.headers.get("referer") or "/?tab=jobs"
    separator = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{separator}{urlencode({'notice': notice, 'notice_kind': kind})}", status_code=303)


def create_directories() -> None:
    for path in (
        settings.downloads_dir,
        settings.pending_dir,
        settings.ready_dir,
        settings.archive_dir,
        Path(settings.db_path).parent,
        BASE_DIR / "static",
        BASE_DIR / "templates",
    ):
        Path(path).mkdir(parents=True, exist_ok=True)


def start_archive_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("archive_scheduler_not_started", reason="apscheduler missing")
        return None

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        cleanup_archive,
        "cron",
        hour=2,
        minute=0,
        args=[settings.archive_dir, settings.archive_retention_days],
        id="archive_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("cloud_server_starting")
    app.state.started_at = time.monotonic()
    app.state.scheduler = None

    create_directories()
    database = await initialize_database(settings.db_path)
    repo = JobRepository(database)
    await repo.mark_stale_jobs_pending()

    app.state.database = database
    app.state.job_repo = repo
    app.state.agent_manager = AgentConnectionManager()
    app.state.scheduler = start_archive_scheduler()

    try:
        yield
    finally:
        logger.info("cloud_server_stopping")
        if app.state.scheduler is not None:
            app.state.scheduler.shutdown(wait=False)
        logger.info("cloud_server_stopped")


app = FastAPI(
    title="PDF Print Queue Cloud",
    version="2.0.0",
    lifespan=lifespan,
    debug=settings.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(jobs.router, prefix="/api/v1")
app.include_router(printer.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    order_number: str | None = None,
    user_code: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    tab: str | None = None,
    notice: str | None = None,
    notice_kind: str | None = None,
):
    repo: JobRepository = request.app.state.job_repo
    stats = await repo.get_stats()
    printer_status = await repo.get_latest_printer_status()
    agents_list = await repo.list_agents()
    jobs_page = await repo.get_paginated(
        page=page,
        limit=limit,
        status=status or None,
        order_number=order_number or None,
        user_code=user_code or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    filters = {
        "status": status or "",
        "order_number": order_number or "",
        "user_code": user_code or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
        "limit": limit,
    }
    filters_active = any(
        filters[key] for key in ("status", "order_number", "user_code", "date_from", "date_to")
    )
    active_tab = tab if tab in {"overview", "jobs", "agents"} else ("jobs" if filters_active else "overview")

    def dashboard_url(target_page: int) -> str:
        values = {key: value for key, value in filters.items() if value not in ("", None)}
        values["page"] = max(target_page, 1)
        values["tab"] = "jobs"
        return f"/?{urlencode(values)}"

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "printer_status": printer_status,
            "agents": agents_list,
            "jobs": jobs_page["items"],
            "pagination": jobs_page,
            "filters": filters,
            "filters_active": filters_active,
            "active_tab": active_tab,
            "notice": notice,
            "notice_kind": notice_kind or "ok",
            "retryable_statuses": {"FAILED", "FAILED_PERM", "PRINTER_OFFLINE"},
            "statuses": [
                "PENDING",
                "CLAIMED",
                "DOWNLOADING",
                "PRINTING",
                "PRINTED",
                "PRINTER_OFFLINE",
                "FAILED",
                "FAILED_PERM",
            ],
            "prev_url": dashboard_url(page - 1),
            "next_url": dashboard_url(page + 1),
            "first_url": dashboard_url(1),
            "last_url": dashboard_url(jobs_page["total_pages"] or 1),
            "connected_agents": request.app.state.agent_manager.connected_count(),
        },
    )


@app.post("/dashboard/jobs/{job_id}/retry")
async def dashboard_retry_job(request: Request, job_id: int):
    repo: JobRepository = request.app.state.job_repo
    updated = await repo.retry_job_for_print(job_id)
    if updated is None:
        return redirect_with_notice(request, "Job topilmadi", "error")
    if updated["status"] != "PENDING":
        return redirect_with_notice(request, "Bu jobni qayta printga berib bo'lmaydi", "error")
    await request.app.state.agent_manager.broadcast({"type": "job_available"})
    return redirect_with_notice(request, f"Job #{job_id} qayta navbatga berildi")


@app.post("/dashboard/jobs/retry-failed")
async def dashboard_retry_failed(
    request: Request,
    statuses: list[str] | None = Form(default=None),
):
    repo: JobRepository = request.app.state.job_repo
    count = await repo.retry_jobs_by_status(statuses or [])
    if count:
        await request.app.state.agent_manager.broadcast({"type": "job_available"})
    return redirect_with_notice(request, f"{count} ta job qayta navbatga berildi")


@app.post("/dashboard/cleanup")
async def dashboard_cleanup(
    request: Request,
    statuses: list[str] | None = Form(default=None),
    older_than_days: int = Form(default=0),
):
    repo: JobRepository = request.app.state.job_repo
    count = await repo.cleanup_jobs(statuses or [], older_than_days=max(older_than_days, 0))
    return redirect_with_notice(request, f"Cleanup: {count} ta job o'chirildi")
