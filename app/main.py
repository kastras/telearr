from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import SESSION_MAX_AGE_SECONDS, SessionAuth, verify_password
from .config import ConfigManager
from .db import Database
from .services import ClientService
from .telegram_bot import TelegramBotService


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.yaml"
DB_PATH = DATA_DIR / "telearr.db"

config_manager = ConfigManager(CONFIG_PATH)
db = Database(DB_PATH)
client_service = ClientService(db)
logger = logging.getLogger("telearr")

BOT_RUNTIME: dict[str, object] = {
    "enabled": False,
    "running": False,
    "last_error": None,
}


def build_auth() -> SessionAuth:
    cfg = config_manager.config
    return SessionAuth(cfg.runtime.session_secret)


async def run_telegram_bot(stop_event: asyncio.Event) -> None:
    cfg = config_manager.config
    BOT_RUNTIME["enabled"] = bool(cfg.telegram.bot_token)
    if not cfg.telegram.bot_token:
        BOT_RUNTIME["running"] = False
        BOT_RUNTIME["last_error"] = "TELEGRAM_BOT_TOKEN vacio"
        logger.warning("Telegram bot desactivado: TELEGRAM_BOT_TOKEN vacio")
        return

    retry_delay = 1
    while not stop_event.is_set():
        service = TelegramBotService(config_manager, client_service)
        app = service.build_application()
        initialized = False
        started = False
        polling = False
        try:
            await app.initialize()
            initialized = True
            await app.start()
            started = True
            await app.updater.start_polling()
            polling = True
            BOT_RUNTIME["running"] = True
            BOT_RUNTIME["last_error"] = None
            retry_delay = 1
            logger.info("Telegram bot iniciado en modo polling")
            while not stop_event.is_set():
                await asyncio.sleep(1)
        except Exception as exc:
            BOT_RUNTIME["running"] = False
            BOT_RUNTIME["last_error"] = str(exc)
            logger.exception("Fallo del bot Telegram; reintentando en %s segundos", retry_delay)
        finally:
            if polling:
                await app.updater.stop()
            if started:
                await app.stop()
            if initialized:
                await app.shutdown()
            BOT_RUNTIME["running"] = False

        if not stop_event.is_set():
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

    logger.info("Telegram bot detenido")


@asynccontextmanager
async def lifespan(application: FastAPI):
    config_manager.validate_runtime_secrets(config_manager.config)
    stop_event = asyncio.Event()
    bot_task = asyncio.create_task(run_telegram_bot(stop_event))

    application.state.stop_event = stop_event
    application.state.bot_task = bot_task

    try:
        yield
    finally:
        stop_event.set()
        await bot_task


app = FastAPI(title="TeleArr", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def require_admin(request: Request) -> bool:
    auth = build_auth()
    return auth.is_valid(request.cookies.get("telearr_session"))


def require_csrf(request: Request, csrf_token: str | None) -> bool:
    auth = build_auth()
    return bool(csrf_token) and auth.is_valid_csrf(request.cookies.get("telearr_session"), csrf_token)


def dashboard_context(request: Request, message: str | None = None) -> dict[str, object]:
    auth = build_auth()
    session = auth.session_data(request.cookies.get("telearr_session")) or {}
    return {
        "pending": client_service.list_pending_tokens(),
        "clients": client_service.list_clients(),
        "searches": client_service.last_searches(30),
        "activities": client_service.last_activities(30),
        "config_yaml": config_manager.get_yaml_text(),
        "bot_runtime": BOT_RUNTIME,
        "csrf_token": session.get("csrf", ""),
        "message": message,
    }


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    cfg = config_manager.config
    if not verify_password(password, cfg.runtime.admin_password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Password invalida"},
            status_code=401,
        )

    auth = build_auth()
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        "telearr_session",
        auth.create_session(),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=SESSION_MAX_AGE_SECONDS,
    )
    return response


@app.post("/logout")
async def logout(request: Request, csrf_token: str | None = Form(None)):
    if not require_admin(request) or not require_csrf(request, csrf_token):
        return RedirectResponse(url="/login", status_code=303)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("telearr_session")
    return response


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(request, "dashboard.html", dashboard_context(request))


@app.get("/health")
async def health():
    healthy = not BOT_RUNTIME["enabled"] or BOT_RUNTIME["running"]
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"ok": healthy, "bot": BOT_RUNTIME},
    )


@app.post("/clients/{telegram_user_id}/approve")
async def approve_client(request: Request, telegram_user_id: int, token: str = Form(...), csrf_token: str | None = Form(None)):
    if not require_admin(request) or not require_csrf(request, csrf_token):
        return RedirectResponse(url="/login", status_code=303)

    client_service.approve_with_token(telegram_user_id, token)
    return RedirectResponse(url="/", status_code=303)


@app.post("/clients/{telegram_user_id}/block")
async def block_client(request: Request, telegram_user_id: int, csrf_token: str | None = Form(None)):
    if not require_admin(request) or not require_csrf(request, csrf_token):
        return RedirectResponse(url="/login", status_code=303)

    client_service.set_blocked(telegram_user_id, True)
    return RedirectResponse(url="/", status_code=303)


@app.post("/clients/{telegram_user_id}/unblock")
async def unblock_client(request: Request, telegram_user_id: int, csrf_token: str | None = Form(None)):
    if not require_admin(request) or not require_csrf(request, csrf_token):
        return RedirectResponse(url="/login", status_code=303)

    client_service.set_blocked(telegram_user_id, False)
    return RedirectResponse(url="/", status_code=303)


@app.post("/config/save", response_class=HTMLResponse)
async def save_config(request: Request, config_yaml: str = Form(...), csrf_token: str | None = Form(None)):
    if not require_admin(request) or not require_csrf(request, csrf_token):
        return RedirectResponse(url="/login", status_code=303)

    message = "Configuracion guardada"
    try:
        config_manager.update_from_yaml_text(config_yaml)
    except Exception as exc:
        message = f"Error guardando configuracion: {exc}"

    return templates.TemplateResponse(request, "dashboard.html", dashboard_context(request, message))
