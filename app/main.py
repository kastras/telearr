from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import SessionAuth, verify_password
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

    try:
        service = TelegramBotService(config_manager, client_service)
        app = service.build_application()

        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        BOT_RUNTIME["running"] = True
        BOT_RUNTIME["last_error"] = None
        logger.info("Telegram bot iniciado en modo polling")

        try:
            while not stop_event.is_set():
                await asyncio.sleep(1)
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            BOT_RUNTIME["running"] = False
            logger.info("Telegram bot detenido")
    except Exception as exc:
        BOT_RUNTIME["running"] = False
        BOT_RUNTIME["last_error"] = str(exc)
        logger.exception("Fallo al iniciar Telegram bot")


@asynccontextmanager
async def lifespan(application: FastAPI):
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


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    cfg = config_manager.config
    if not verify_password(password, cfg.runtime.admin_password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Password invalida"},
            status_code=401,
        )

    auth = build_auth()
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("telearr_session", auth.create_session(), httponly=True, samesite="lax")
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("telearr_session")
    return response


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    context = {
        "request": request,
        "pending": client_service.list_pending_tokens(),
        "clients": client_service.list_clients(),
        "searches": client_service.last_searches(30),
        "activities": client_service.last_activities(30),
        "config_yaml": config_manager.get_yaml_text(),
        "bot_runtime": BOT_RUNTIME,
        "message": None,
    }
    return templates.TemplateResponse("dashboard.html", context)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "bot": BOT_RUNTIME,
    }


@app.post("/clients/{telegram_user_id}/approve")
async def approve_client(request: Request, telegram_user_id: int, token: str = Form(...)):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    client_service.approve_with_token(telegram_user_id, token)
    return RedirectResponse(url="/", status_code=303)


@app.post("/clients/{telegram_user_id}/block")
async def block_client(request: Request, telegram_user_id: int):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    client_service.set_blocked(telegram_user_id, True)
    return RedirectResponse(url="/", status_code=303)


@app.post("/clients/{telegram_user_id}/unblock")
async def unblock_client(request: Request, telegram_user_id: int):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    client_service.set_blocked(telegram_user_id, False)
    return RedirectResponse(url="/", status_code=303)


@app.post("/config/save", response_class=HTMLResponse)
async def save_config(request: Request, config_yaml: str = Form(...)):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=303)

    message = "Configuracion guardada"
    try:
        config_manager.update_from_yaml_text(config_yaml)
    except Exception as exc:
        message = f"Error guardando configuracion: {exc}"

    context = {
        "request": request,
        "pending": client_service.list_pending_tokens(),
        "clients": client_service.list_clients(),
        "searches": client_service.last_searches(30),
        "activities": client_service.last_activities(30),
        "config_yaml": config_manager.get_yaml_text(),
        "bot_runtime": BOT_RUNTIME,
        "message": message,
    }
    return templates.TemplateResponse("dashboard.html", context)
