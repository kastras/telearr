from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .arr_clients import ArrClientError, RadarrClient, SonarrClient
from .config import ConfigManager
from .services import ClientService


class TelegramBotService:
    def __init__(self, config_manager: ConfigManager, client_service: ClientService):
        self.config_manager = config_manager
        self.client_service = client_service

    def build_application(self) -> Application:
        cfg = self.config_manager.config
        app = Application.builder().token(cfg.telegram.bot_token).build()

        app.add_handler(CommandHandler("start", self.on_start))
        app.add_handler(CommandHandler("help", self.on_help))
        app.add_handler(CommandHandler("serie", self.on_serie))
        app.add_handler(CommandHandler("pelicula", self.on_pelicula))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_free_text))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_error_handler(self.error_handler)

        return app

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Manejador de errores para el bot."""
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error al procesar update: {context.error}", exc_info=context.error)
        
        message = self._safe_reply_target(update)
        if message:
            try:
                error_msg = str(context.error)[:200]
                await message.reply_text(
                    f"❌ Error: {error_msg}\n\n"
                    f"Asegúrate de que Sonarr/Radarr estén accesibles y las URLs sean correctas."
                )
            except Exception as e:
                logger.error(f"Error al enviar mensaje de error: {e}")

    @staticmethod
    def _safe_reply_target(update: Update):
        return update.effective_message

    @staticmethod
    def _parse_value_and_options(tokens: list[str]) -> tuple[str, dict[str, str]]:
        value_parts: list[str] = []
        options: dict[str, str] = {}
        for token in tokens:
            if "=" in token:
                key, raw_value = token.split("=", 1)
                options[key.strip().lower()] = raw_value.strip().lower()
                continue
            value_parts.append(token)
        return " ".join(value_parts).strip(), options

    @staticmethod
    def _profile_key(resolution: str, audio: str) -> str:
        return f"{resolution.lower()}|{audio.lower()}"

    def _resolve_series_profiles(
        self,
        options: dict[str, str],
    ) -> tuple[str, str, int, int | None]:
        cfg = self.config_manager.config
        defaults = cfg.defaults

        resolution = options.get("res", defaults.series_default_resolution).lower()
        audio = options.get("audio", defaults.series_default_audio).lower()
        key = self._profile_key(resolution, audio)

        quality_profile_id = defaults.series_quality_profiles.get(
            key,
            defaults.series_quality_profile_id,
        )
        language_profile_id = defaults.series_language_profiles.get(audio)
        return resolution, audio, quality_profile_id, language_profile_id

    def _resolve_movie_profiles(self, options: dict[str, str]) -> tuple[str, str, int]:
        cfg = self.config_manager.config
        defaults = cfg.defaults

        resolution = options.get("res", defaults.movies_default_resolution).lower()
        audio = options.get("audio", defaults.movies_default_audio).lower()
        key = self._profile_key(resolution, audio)

        quality_profile_id = defaults.movies_quality_profiles.get(
            key,
            defaults.movies_quality_profile_id,
        )
        return resolution, audio, quality_profile_id

    @staticmethod
    def _resolution_options(profile_map: dict[str, int], default_resolution: str) -> list[str]:
        values = {k.split("|", 1)[0].strip().lower() for k in profile_map if "|" in k}
        if default_resolution:
            values.add(default_resolution.lower())
        if not values:
            values = {"1080p"}

        order = {"4k": 0, "2160p": 0, "1080p": 1, "720p": 2, "480p": 3}
        return sorted(values, key=lambda x: (order.get(x, 99), x))

    async def _show_series_carousel_result(
        self,
        message,
        search_id: str,
        results: list[dict[str, Any]],
        current_index: int,
        context: ContextTypes.DEFAULT_TYPE,
        edit_existing: bool = False,
    ) -> None:
        """Muestra un resultado de serie en formato carrusel con imagen y navegación."""
        import httpx
        
        if not results or current_index >= len(results):
            return

        result = results[current_index]
        tvdb_id = result.get("tvdbId")
        title = result.get("title", "Desconocida")
        year = result.get("releaseDate", "")[:4] if result.get("releaseDate") else ""
        overview = result.get("overview", "Sin descripción")[:300]
        images = result.get("images", [])
        
        # Buscar imagen poster
        poster_url = None
        for img in images:
            if img.get("coverType") == "poster":
                poster_url = img.get("url")
                break
        
        cfg = self.config_manager.config
        defaults = cfg.defaults
        resolution = defaults.series_default_resolution.lower()
        audio = defaults.series_default_audio.lower()

        # Construir URL completa de la imagen si es relativa
        if poster_url and not poster_url.startswith(("http://", "https://")):
            poster_url = f"{cfg.sonarr.base_url}{poster_url}"

        # Construir mensaje
        year_str = f" ({year})" if year else ""
        header = f"📺 {title}{year_str}\n"
        msg = header + overview + f"\n\n({current_index + 1}/{len(results)})"

        # Construir teclado
        keyboard = []

        # Primera fila: anterior/siguiente
        nav_buttons = []
        if current_index > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️ Anterior",
                    callback_data=f"snav|{search_id}|prev",
                )
            )
        if current_index < len(results) - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Siguiente ▶️",
                    callback_data=f"snav|{search_id}|next",
                )
            )
        if nav_buttons:
            keyboard.append(nav_buttons)

        # Segunda fila: agregar
        keyboard.append([
            InlineKeyboardButton(
                text="✅ Agregar",
                callback_data=f"sadd|{tvdb_id}|{resolution}|{audio}",
            )
        ])

        # Tercera fila: cambiar calidad
        keyboard.append([
            InlineKeyboardButton(
                text="⚙️ Calidad",
                callback_data=f"sq|{tvdb_id}",
            )
        ])

        # Guardar índice en context
        context.user_data[f"series_search_{search_id}_index"] = current_index

        # Intentar enviar con imagen
        if poster_url:
            try:
                # Agregar API key como parámetro de query para MediaCoverProxy
                url_with_auth = poster_url
                if "?" in poster_url:
                    url_with_auth = f"{poster_url}&apikey={cfg.sonarr.api_token}"
                else:
                    url_with_auth = f"{poster_url}?apikey={cfg.sonarr.api_token}"
                
                # Descargar imagen
                async with httpx.AsyncClient(timeout=10) as client:
                    res = await client.get(url_with_auth)
                    res.raise_for_status()
                    image_data = res.content
                
                if edit_existing:
                    from telegram import InputMediaPhoto
                    media = InputMediaPhoto(media=image_data, caption=msg, parse_mode=None)
                    await message.edit_media(media, reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    await message.reply_photo(
                        photo=image_data,
                        caption=msg,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
            except Exception as exc:
                # Si hay error con la imagen, mostrar solo texto
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error al descargar imagen {poster_url}: {exc}")
                await message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    async def _run_series_search_flow(
        self,
        message,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        query_text: str,
        force_api: bool = False,
    ) -> None:
        cfg = self.config_manager.config
        sonarr = SonarrClient(cfg.sonarr.base_url, cfg.sonarr.api_token)

        self.client_service.log_search(user_id, "serie", query_text)

        if not force_api:
            local_results = await sonarr.search_local(query_text)
            if local_results:
                msg = "📺 Encontré esto en tu Sonarr:\n\n"
                keyboard: list[list[InlineKeyboardButton]] = []
                for s in local_results[:10]:
                    series_id = s.get("id")
                    title = s.get("title", "Desconocida")
                    status = s.get("status", "unknown")
                    seasons = s.get("seasons", [])
                    total_eps = 0
                    downloaded_eps = 0
                    for season in seasons:
                        stats = season.get("statistics", {})
                        total_eps += int(stats.get("episodeCount", 0) or 0)
                        downloaded_eps += int(stats.get("episodeFileCount", 0) or 0)

                    msg += f"• {title} ({status}) - {downloaded_eps}/{total_eps} episodios\n"
                    if series_id is not None:
                        keyboard.append([
                            InlineKeyboardButton(
                                text=f"Ver estado: {title[:28]}",
                                callback_data=f"sinfo|{series_id}",
                            )
                        ])

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            text="Buscar una serie nueva con este nombre",
                            callback_data="tgnew|serie",
                        )
                    ]
                )
                await message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
                self.client_service.log_activity(user_id, "serie.local", query_text)
                return

        # Buscar en API
        results = await sonarr.search(query_text)
        top = [x for x in results if x.get("tvdbId")][:8]

        if not top:
            await message.reply_text("No encontré resultados en Sonarr local ni en la API.")
            return

        # Guardar resultados en context y mostrar carrusel
        search_id = str(uuid.uuid4())
        context.user_data[f"series_search_{search_id}"] = top
        context.user_data[f"series_search_{search_id}_index"] = 0

        await self._show_series_carousel_result(message, search_id, top, 0, context)
        self.client_service.log_activity(user_id, "serie.buscar", query_text)

    async def _run_movie_search_flow(
        self,
        message,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        query_text: str,
        force_api: bool = False,
    ) -> None:
        cfg = self.config_manager.config
        radarr = RadarrClient(cfg.radarr.base_url, cfg.radarr.api_token)
        defaults = cfg.defaults

        self.client_service.log_search(user_id, "pelicula", query_text)

        if not force_api:
            local_results = await radarr.search_local(query_text)
            if local_results:
                msg = "🎬 Encontré esto en tu Radarr:\n\n"
                keyboard: list[list[InlineKeyboardButton]] = []
                for m in local_results[:10]:
                    movie_id = m.get("id")
                    title = m.get("title", "Desconocida")
                    year = m.get("year", "")
                    status = m.get("status", "unknown")
                    has_file = bool(m.get("hasFile", False))
                    file_status = "descargada" if has_file else "sin archivo"

                    msg += f"• {title} ({year}) - {status} - {file_status}\n"
                    if movie_id is not None:
                        keyboard.append([
                            InlineKeyboardButton(
                                text=f"Ver estado: {title[:28]}",
                                callback_data=f"minfo|{movie_id}",
                            )
                        ])

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            text="Buscar una película nueva con este nombre",
                            callback_data="tgnew|pelicula",
                        )
                    ]
                )
                await message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
                self.client_service.log_activity(user_id, "pelicula.local", query_text)
                return

        resolution = defaults.movies_default_resolution.lower()
        audio = defaults.movies_default_audio.lower()
        results = await radarr.search(query_text)
        top = [x for x in results if x.get("tmdbId")][:8]

        if not top:
            await message.reply_text("No encontré resultados en Radarr local ni en la API.")
            return

        lines = [f"• {x.get('title')} | tmdbId={x.get('tmdbId')}" for x in top]
        msg = (
            f"Resultados de película para '{query_text}' (calidad por defecto: {resolution}/{audio}):\n\n"
            + "\n".join(lines)
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    text=f"Agregar: {x.get('title')[:24]}",
                    callback_data=f"madd|{x.get('tmdbId')}|{resolution}|{audio}",
                ),
                InlineKeyboardButton(
                    text="Cambiar calidad",
                    callback_data=f"mq|{x.get('tmdbId')}",
                ),
            ]
            for x in top
        ]

        await message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        self.client_service.log_activity(user_id, "pelicula.buscar", query_text)

    async def _check_access(self, update: Update) -> tuple[bool, int]:
        user = update.effective_user
        message = self._safe_reply_target(update)
        if not user:
            return False, 0

        self.client_service.ensure_client(user)
        state = self.client_service.get_client_state(user.id)
        if not state:
            return False, user.id

        if state["blocked"]:
            if message:
                await message.reply_text("Tu acceso esta bloqueado por un administrador.")
            return False, user.id

        if not state["approved"]:
            token, expires = self.client_service.create_pair_token(user.id)
            expires_at = datetime.fromisoformat(expires).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
            if message:
                await message.reply_text(
                    "Aun no estas aprobado. Pasa este token al administrador para habilitar tu acceso:\n"
                    f"Token: {token}\n"
                    f"Caduca: {expires_at}"
                )
            return False, user.id

        return True, user.id

    async def on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user:
            return

        self.client_service.ensure_client(user)
        state = self.client_service.get_client_state(user.id)

        if state and state["approved"] and not state["blocked"]:
            await update.message.reply_text(
                "Bienvenido a TeleArr. Usa /help para ver comandos disponibles."
            )
            return

        token, expires = self.client_service.create_pair_token(user.id)
        expires_at = datetime.fromisoformat(expires).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        await update.message.reply_text(
            "Bienvenido. Tu acceso necesita aprobacion en el panel admin.\n"
            f"Token temporal: {token}\n"
            f"Caduca en 30 minutos ({expires_at})."
        )

    async def on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "También puedes escribir directamente un nombre (ej: dark o interstellar) y te preguntaré si es serie o película.\n\n"
            "Comandos:\n"
            "/serie buscar <texto> [res=1080p] [audio=multi]\n"
            "/serie agregar <tvdbId> [res=1080p] [audio=multi]\n"
            "/serie estado <sonarrId>\n"
            "/serie borrar <sonarrId>\n\n"
            "/pelicula buscar <texto> [res=1080p] [audio=multi]\n"
            "/pelicula agregar <tmdbId> [res=1080p] [audio=multi]\n"
            "/pelicula estado <radarrId>\n"
            "/pelicula borrar <radarrId>\n\n"
            "Tambien puedes usar botones tras /serie buscar y /pelicula buscar."
        )

    async def on_free_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, _ = await self._check_access(update)
        if not ok:
            return

        message = self._safe_reply_target(update)
        if not message:
            return

        query_text = (message.text or "").strip()
        if not query_text:
            return

        context.user_data["pending_query"] = query_text
        keyboard = [
            [
                InlineKeyboardButton("📺 Es una serie", callback_data="tgtype|serie"),
                InlineKeyboardButton("🎬 Es una película", callback_data="tgtype|pelicula"),
            ]
        ]
        await message.reply_text(
            f"Entendido: '{query_text}'. ¿Qué quieres buscar?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def on_serie(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._check_access(update)
        if not ok:
            return

        # Sin argumentos: mostrar menú de acciones
        if not context.args:
            keyboard = [
                [InlineKeyboardButton(text="🔍 Buscar", callback_data="smenu|buscar")],
                [InlineKeyboardButton(text="➕ Agregar", callback_data="smenu|agregar")],
                [InlineKeyboardButton(text="📊 Ver estado", callback_data="smenu|estado")],
                [InlineKeyboardButton(text="🗑️ Borrar", callback_data="smenu|borrar")],
            ]
            await update.message.reply_text(
                "Elige una acción para series:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if len(context.args) < 1:
            await update.message.reply_text("Uso: /serie <buscar|agregar|estado|borrar> <valor>")
            return

        action = context.args[0].lower().strip()
        value, options = self._parse_value_and_options(context.args[1:])

        cfg = self.config_manager.config
        sonarr = SonarrClient(cfg.sonarr.base_url, cfg.sonarr.api_token)

        try:
            if action == "buscar":
                if not value:
                    await update.message.reply_text("Debes indicar texto para buscar")
                    return

                resolution, audio, _, _ = self._resolve_series_profiles(options)
                self.client_service.log_search(user_id, "serie", value)
                
                # Primero busca localmente en series ya agregadas
                local_results = await sonarr.search_local(value)
                
                if local_results:
                    msg = f"📺 Series encontradas localmente:\n\n"
                    keyboard = []
                    for s in local_results[:10]:
                        series_id = s.get('id')
                        title = s.get('title', 'Desconocida')
                        status = s.get('status', 'unknown')
                        msg += f"• {title} ({status})\n"
                        
                        keyboard.append([
                            InlineKeyboardButton(
                                text=f"Ver: {title[:35]}",
                                callback_data=f"sinfo|{series_id}",
                            ),
                            InlineKeyboardButton(
                                text="Borrar",
                                callback_data=f"sdel|{series_id}",
                            ),
                        ])
                    
                    await update.message.reply_text(
                        msg + "\n(O busca en la API)",
                        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    )
                    return
                
                # Si no hay locales, busca en la API
                results = await sonarr.search(value)
                top = [x for x in results if x.get("tvdbId")][:8]
                lines = [f"{x.get('title')} | tvdbId={x.get('tvdbId')}" for x in top]
                msg = (
                    f"Resultados en API (res={resolution}, audio={audio}):\n"
                    + ("\n".join(lines) if lines else "Sin resultados")
                )

                keyboard = [
                    [
                        InlineKeyboardButton(
                            text=f"Agregar: {x.get('title')[:40]}",
                            callback_data=f"sadd|{x.get('tvdbId')}|{resolution}|{audio}",
                        )
                    ]
                    for x in top
                ]
                self.client_service.log_activity(user_id, "serie.buscar", value)
                await update.message.reply_text(
                    msg,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                )
                return

            if action == "agregar":
                tvdb_id = int(value)
                resolution, audio, quality_profile_id, language_profile_id = self._resolve_series_profiles(options)
                data = await sonarr.add(
                    tvdb_id=tvdb_id,
                    quality_profile_id=quality_profile_id,
                    root_folder_path=cfg.defaults.series_root_folder,
                    language_profile_id=language_profile_id,
                    tags=cfg.defaults.series_add_tags,
                )
                self.client_service.log_activity(
                    user_id,
                    "serie.agregar",
                    f"tvdbId={tvdb_id} res={resolution} audio={audio} q={quality_profile_id}",
                )
                await update.message.reply_text(
                    f"Serie agregada: {data.get('title')} (res={resolution}, audio={audio})"
                )
                return

            if action == "estado":
                series_id = int(value)
                data = await sonarr.get(series_id)
                self.client_service.log_activity(user_id, "serie.estado", f"seriesId={series_id}")
                
                title = data.get('title', 'Desconocido')
                monitored = data.get('monitored', False)
                status = data.get('status', 'unknown')
                seasons = data.get('seasons', [])
                
                msg = f"📺 {title}\nEstado: {status}\nMonitoreada: {'Sí' if monitored else 'No'}\n\n"
                
                # Mostrar temporadas con botones
                keyboard = []
                if seasons:
                    msg += "Temporadas:\n"
                    season_buttons = []
                    for season in sorted(seasons, key=lambda x: x.get('seasonNumber', 0)):
                        season_num = season.get('seasonNumber', 0)
                        episode_count = season.get('statistics', {}).get('episodeCount', 0)
                        downloaded = season.get('statistics', {}).get('episodeFileCount', 0)
                        msg += f"  S{season_num:02d}: {downloaded}/{episode_count} episodios\n"
                        
                        season_buttons.append(
                            InlineKeyboardButton(
                                text=f"S{season_num:02d} ({downloaded}/{episode_count})",
                                callback_data=f"sstate|{series_id}|{season_num}",
                            )
                        )
                    
                    # Agrupar botones en filas de 2
                    for i in range(0, len(season_buttons), 2):
                        keyboard.append(season_buttons[i:i+2])

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            text="🔎 Buscar episodios faltantes",
                            callback_data=f"ssearch|{series_id}",
                        )
                    ]
                )

                msg += "\n¿Quieres buscar algún episodio? Usa los botones."
                
                await update.message.reply_text(
                    msg,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                )
                return

            if action == "borrar":
                series_id = int(value)
                await sonarr.delete(series_id)
                self.client_service.log_activity(user_id, "serie.borrar", f"seriesId={series_id}")
                await update.message.reply_text("Serie eliminada.")
                return

            await update.message.reply_text("Accion no valida para /serie")
        except ValueError:
            await update.message.reply_text("El valor numerico no es valido")
        except ArrClientError as exc:
            await update.message.reply_text(f"Error Sonarr: {exc}")

    async def on_pelicula(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._check_access(update)
        if not ok:
            return

        # Sin argumentos: mostrar menú de acciones
        if not context.args:
            keyboard = [
                [InlineKeyboardButton(text="🔍 Buscar", callback_data="mmenu|buscar")],
                [InlineKeyboardButton(text="➕ Agregar", callback_data="mmenu|agregar")],
                [InlineKeyboardButton(text="📊 Ver estado", callback_data="mmenu|estado")],
                [InlineKeyboardButton(text="🗑️ Borrar", callback_data="mmenu|borrar")],
            ]
            await update.message.reply_text(
                "Elige una acción para películas:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if len(context.args) < 1:
            await update.message.reply_text("Uso: /pelicula <buscar|agregar|estado|borrar> <valor>")
            return

        action = context.args[0].lower().strip()
        value, options = self._parse_value_and_options(context.args[1:])

        cfg = self.config_manager.config
        radarr = RadarrClient(cfg.radarr.base_url, cfg.radarr.api_token)

        try:
            if action == "buscar":
                if not value:
                    await update.message.reply_text("Debes indicar texto para buscar")
                    return

                resolution, audio, _ = self._resolve_movie_profiles(options)
                self.client_service.log_search(user_id, "pelicula", value)
                
                # Primero busca localmente en películas ya agregadas
                local_results = await radarr.search_local(value)
                
                if local_results:
                    msg = f"🎬 Películas encontradas localmente:\n\n"
                    keyboard = []
                    for m in local_results[:10]:
                        movie_id = m.get('id')
                        title = m.get('title', 'Desconocida')
                        year = m.get('year', '')
                        status = m.get('status', 'unknown')
                        msg += f"• {title} ({year}) - {status}\n"
                        
                        keyboard.append([
                            InlineKeyboardButton(
                                text=f"Ver: {title[:35]}",
                                callback_data=f"minfo|{movie_id}",
                            ),
                            InlineKeyboardButton(
                                text="Borrar",
                                callback_data=f"mdel|{movie_id}",
                            ),
                        ])
                    
                    await update.message.reply_text(
                        msg + "\n(O busca en la API)",
                        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    )
                    return
                
                # Si no hay locales, busca en la API
                results = await radarr.search(value)
                top = [x for x in results if x.get("tmdbId")][:8]
                lines = [f"{x.get('title')} | tmdbId={x.get('tmdbId')}" for x in top]
                msg = (
                    f"Resultados en API (res={resolution}, audio={audio}):\n"
                    + ("\n".join(lines) if lines else "Sin resultados")
                )

                keyboard = [
                    [
                        InlineKeyboardButton(
                            text=f"Agregar: {x.get('title')[:40]}",
                            callback_data=f"madd|{x.get('tmdbId')}|{resolution}|{audio}",
                        )
                    ]
                    for x in top
                ]
                self.client_service.log_activity(user_id, "pelicula.buscar", value)
                await update.message.reply_text(
                    msg,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                )
                return

            if action == "agregar":
                tmdb_id = int(value)
                resolution, audio, quality_profile_id = self._resolve_movie_profiles(options)
                data = await radarr.add(
                    tmdb_id=tmdb_id,
                    quality_profile_id=quality_profile_id,
                    root_folder_path=cfg.defaults.movies_root_folder,
                    tags=cfg.defaults.movies_add_tags,
                )
                self.client_service.log_activity(
                    user_id,
                    "pelicula.agregar",
                    f"tmdbId={tmdb_id} res={resolution} audio={audio} q={quality_profile_id}",
                )
                await update.message.reply_text(
                    f"Pelicula agregada: {data.get('title')} (res={resolution}, audio={audio})"
                )
                return

            if action == "estado":
                movie_id = int(value)
                data = await radarr.get(movie_id)
                self.client_service.log_activity(user_id, "pelicula.estado", f"movieId={movie_id}")
                
                title = data.get('title', 'Desconocida')
                year = data.get('year', '')
                monitored = data.get('monitored', False)
                status = data.get('status', 'unknown')
                file_info = data.get('movieFile', {})
                file_path = file_info.get('path', 'No descargada') if file_info else 'No descargada'
                
                msg = (
                    f"🎬 {title} ({year})\n"
                    f"Estado: {status}\n"
                    f"Monitoreada: {'Sí' if monitored else 'No'}\n"
                    f"Archivo: {file_path}\n"
                )
                
                await update.message.reply_text(msg)
                return

            if action == "borrar":
                movie_id = int(value)
                await radarr.delete(movie_id)
                self.client_service.log_activity(user_id, "pelicula.borrar", f"movieId={movie_id}")
                await update.message.reply_text("Pelicula eliminada.")
                return

            await update.message.reply_text("Accion no valida para /pelicula")
        except ValueError:
            await update.message.reply_text("El valor numerico no es valido")
        except ArrClientError as exc:
            await update.message.reply_text(f"Error Radarr: {exc}")

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()

        ok, user_id = await self._check_access(update)
        if not ok:
            return

        cfg = self.config_manager.config
        parts = query.data.split("|")

        if len(parts) == 2 and parts[0] == "tgtype":
            media_type = parts[1]
            query_text = (context.user_data.get("pending_query") or "").strip()
            if not query_text:
                await query.edit_message_text("No tengo texto pendiente. Escríbeme primero el nombre.")
                return

            await query.edit_message_text(f"Buscando '{query_text}' como {media_type}...")
            try:
                target_message = query.message
                if not target_message:
                    return

                if media_type == "serie":
                    await self._run_series_search_flow(target_message, context, user_id, query_text, force_api=False)
                elif media_type == "pelicula":
                    await self._run_movie_search_flow(target_message, context, user_id, query_text, force_api=False)
                else:
                    await target_message.reply_text("Tipo no válido")
            except ArrClientError as exc:
                if query.message:
                    await query.message.reply_text(f"Error: {exc}")
            return

        if len(parts) == 2 and parts[0] == "tgnew":
            media_type = parts[1]
            query_text = (context.user_data.get("pending_query") or "").strip()
            if not query_text:
                await query.edit_message_text("No tengo texto pendiente. Escríbeme primero el nombre.")
                return

            await query.edit_message_text(f"Buscando en API nuevas opciones para '{query_text}'...")
            try:
                target_message = query.message
                if not target_message:
                    return

                if media_type == "serie":
                    await self._run_series_search_flow(target_message, context, user_id, query_text, force_api=True)
                elif media_type == "pelicula":
                    await self._run_movie_search_flow(target_message, context, user_id, query_text, force_api=True)
                else:
                    await target_message.reply_text("Tipo no válido")
            except ArrClientError as exc:
                if query.message:
                    await query.message.reply_text(f"Error: {exc}")
            return

        # Navegación de carrusel de series
        if len(parts) == 3 and parts[0] == "snav":
            search_id = parts[1]
            direction = parts[2]
            
            results = context.user_data.get(f"series_search_{search_id}")
            current_index = context.user_data.get(f"series_search_{search_id}_index", 0)
            
            if not results:
                await query.edit_message_text("Los resultados de búsqueda expiraron.")
                return
            
            if direction == "prev" and current_index > 0:
                current_index -= 1
            elif direction == "next" and current_index < len(results) - 1:
                current_index += 1
            
            context.user_data[f"series_search_{search_id}_index"] = current_index
            
            try:
                await self._show_series_carousel_result(query.message, search_id, results, current_index, context, edit_existing=True)
            except Exception as exc:
                await query.edit_message_text(f"Error al mostrar resultado: {exc}")
            return

        if len(parts) == 2 and parts[0] in ("sq", "mq"):
            try:
                raw_id = int(parts[1])
            except ValueError:
                await query.edit_message_text("ID inválido")
                return

            defaults = cfg.defaults

            if parts[0] == "sq":
                audio = defaults.series_default_audio.lower()
                resolutions = self._resolution_options(
                    defaults.series_quality_profiles,
                    defaults.series_default_resolution,
                )
                keyboard = [
                    [
                        InlineKeyboardButton(
                            text=f"{res}/{audio}",
                            callback_data=f"sadd|{raw_id}|{res}|{audio}",
                        )
                    ]
                    for res in resolutions
                ]
                await query.edit_message_text(
                    "Elige calidad para la serie:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return

            audio = defaults.movies_default_audio.lower()
            resolutions = self._resolution_options(
                defaults.movies_quality_profiles,
                defaults.movies_default_resolution,
            )
            keyboard = [
                [
                    InlineKeyboardButton(
                        text=f"{res}/{audio}",
                        callback_data=f"madd|{raw_id}|{res}|{audio}",
                    )
                ]
                for res in resolutions
            ]
            await query.edit_message_text(
                "Elige calidad para la película:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        
        # Manejo de menús de acciones
        if len(parts) == 2 and parts[0] in ("smenu", "mmenu"):
            action_type = parts[0]
            action = parts[1]
            
            if action_type == "smenu":
                if action == "buscar":
                    await query.edit_message_text("📺 Escribe el nombre de la serie a buscar")
                elif action == "agregar":
                    await query.edit_message_text("📺 Escribe el tvdbId de la serie a agregar")
                elif action == "estado":
                    await query.edit_message_text("📺 Escribe el sonarrId para ver el estado")
                elif action == "borrar":
                    await query.edit_message_text("📺 Escribe el sonarrId para borrar")
            elif action_type == "mmenu":
                if action == "buscar":
                    await query.edit_message_text("🎬 Escribe el nombre de la película a buscar")
                elif action == "agregar":
                    await query.edit_message_text("🎬 Escribe el tmdbId de la película a agregar")
                elif action == "estado":
                    await query.edit_message_text("🎬 Escribe el radarrId para ver el estado")
                elif action == "borrar":
                    await query.edit_message_text("🎬 Escribe el radarrId para borrar")
            return
        
        # Manejo de info y borrar de series/películas locales
        if len(parts) == 2 and parts[0] in ("sinfo", "sdel", "minfo", "mdel", "ssearch", "sep"):
            try:
                action = parts[0]
                item_id = int(parts[1])
                
                if action == "sinfo":
                    sonarr = SonarrClient(cfg.sonarr.base_url, cfg.sonarr.api_token)
                    data = await sonarr.get(item_id)
                    
                    title = data.get('title', 'Desconocida')
                    status = data.get('status', 'unknown')
                    monitored = data.get('monitored', False)
                    seasons = data.get('seasons', [])
                    
                    msg = f"📺 {title}\nEstado: {status}\nMonitoreada: {'Sí' if monitored else 'No'}\n\n"
                    
                    keyboard = []
                    if seasons:
                        msg += "Temporadas:\n"
                        for season in sorted(seasons, key=lambda x: x.get('seasonNumber', 0)):
                            season_num = season.get('seasonNumber', 0)
                            episode_count = season.get('statistics', {}).get('episodeCount', 0)
                            downloaded = season.get('statistics', {}).get('episodeFileCount', 0)
                            msg += f"  S{season_num:02d}: {downloaded}/{episode_count}\n"

                            keyboard.append([
                                InlineKeyboardButton(
                                    text=f"Temporada S{season_num:02d}",
                                    callback_data=f"sstate|{item_id}|{season_num}",
                                )
                            ])

                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                text="🔎 Buscar episodios faltantes",
                                callback_data=f"ssearch|{item_id}",
                            )
                        ]
                    )

                    msg += "\n¿Quieres buscar algún episodio? Usa los botones."

                    await query.edit_message_text(
                        msg,
                        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    )
                    return
                
                elif action == "sdel":
                    sonarr = SonarrClient(cfg.sonarr.base_url, cfg.sonarr.api_token)
                    data = await sonarr.get(item_id)
                    title = data.get('title', 'Desconocida')
                    await sonarr.delete(item_id)
                    self.client_service.log_activity(user_id, "serie.borrar", f"seriesId={item_id}")
                    await query.edit_message_text(f"❌ Serie '{title}' eliminada")
                    return
                
                elif action == "minfo":
                    radarr = RadarrClient(cfg.radarr.base_url, cfg.radarr.api_token)
                    data = await radarr.get(item_id)
                    
                    title = data.get('title', 'Desconocida')
                    year = data.get('year', '')
                    status = data.get('status', 'unknown')
                    monitored = data.get('monitored', False)
                    file_info = data.get('movieFile', {})
                    file_path = file_info.get('path', 'No descargada') if file_info else 'No descargada'
                    
                    msg = (
                        f"🎬 {title} ({year})\n"
                        f"Estado: {status}\n"
                        f"Monitoreada: {'Sí' if monitored else 'No'}\n"
                        f"Archivo: {file_path}\n"
                    )
                    
                    await query.edit_message_text(msg)
                    return
                
                elif action == "mdel":
                    radarr = RadarrClient(cfg.radarr.base_url, cfg.radarr.api_token)
                    data = await radarr.get(item_id)
                    title = data.get('title', 'Desconocida')
                    await radarr.delete(item_id)
                    self.client_service.log_activity(user_id, "pelicula.borrar", f"movieId={item_id}")
                    await query.edit_message_text(f"❌ Película '{title}' eliminada")
                    return

                elif action == "ssearch":
                    sonarr = SonarrClient(cfg.sonarr.base_url, cfg.sonarr.api_token)
                    series = await sonarr.get(item_id)
                    await sonarr.search_series_missing(item_id)
                    title = series.get('title', 'Serie')
                    self.client_service.log_activity(user_id, "serie.search_missing", f"seriesId={item_id}")
                    await query.edit_message_text(
                        f"🔎 Búsqueda de episodios faltantes lanzada para '{title}'."
                    )
                    return

                elif action == "sep":
                    sonarr = SonarrClient(cfg.sonarr.base_url, cfg.sonarr.api_token)
                    await sonarr.search_episode(item_id)
                    self.client_service.log_activity(user_id, "serie.search_episode", f"episodeId={item_id}")
                    await query.edit_message_text(
                        "🔎 Búsqueda del episodio solicitada. Revisa la cola de Sonarr."
                    )
                    return
                    
            except (ValueError, ArrClientError) as exc:
                await query.edit_message_text(f"Error: {exc}")
            return
        
        # Manejo de temporadas de serie
        if len(parts) == 3 and parts[0] == "sstate":
            try:
                series_id = int(parts[1])
                season_num = int(parts[2])
                
                sonarr = SonarrClient(cfg.sonarr.base_url, cfg.sonarr.api_token)
                series_data = await sonarr.get(series_id)
                
                seasons = series_data.get('seasons', [])
                season = next((s for s in seasons if s.get('seasonNumber') == season_num), None)
                
                if not season:
                    await query.edit_message_text(f"Temporada {season_num} no encontrada")
                    return
                
                title = series_data.get('title', 'Desconocida')
                stats = season.get('statistics', {})
                episode_count = stats.get('episodeCount', 0)
                downloaded = stats.get('episodeFileCount', 0)
                
                msg = f"📺 {title} - Temporada {season_num}\n"
                msg += f"Episodios: {downloaded}/{episode_count}\n\n"

                episodes = await sonarr.list_episodes(series_id=series_id, season_number=season_num)
                missing = [e for e in episodes if not e.get("hasFile")]

                keyboard = []
                if missing:
                    msg += "Episodios faltantes:\n"
                    for ep in missing[:10]:
                        ep_num = int(ep.get("episodeNumber", 0) or 0)
                        ep_title = ep.get("title", "Sin título")
                        ep_id = ep.get("id")
                        msg += f"- E{ep_num:02d} {ep_title}\n"
                        if ep_id is not None:
                            keyboard.append(
                                [
                                    InlineKeyboardButton(
                                        text=f"Buscar S{season_num:02d}E{ep_num:02d}",
                                        callback_data=f"sep|{ep_id}",
                                    )
                                ]
                            )
                else:
                    msg += "No hay episodios faltantes en esta temporada."

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            text="🔎 Buscar episodios faltantes (serie)",
                            callback_data=f"ssearch|{series_id}",
                        )
                    ]
                )

                await query.edit_message_text(
                    msg,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                )
            except (ValueError, ArrClientError) as exc:
                await query.edit_message_text(f"Error: {exc}")
            return
        
        # Manejo de agregaciones desde búsqueda
        if len(parts) == 4:
            action, raw_id, resolution, audio = parts
            options = {"res": resolution, "audio": audio}

            try:
                if action == "sadd":
                    tvdb_id = int(raw_id)
                    _, _, quality_profile_id, language_profile_id = self._resolve_series_profiles(options)
                    sonarr = SonarrClient(cfg.sonarr.base_url, cfg.sonarr.api_token)
                    data = await sonarr.add(
                        tvdb_id=tvdb_id,
                        quality_profile_id=quality_profile_id,
                        root_folder_path=cfg.defaults.series_root_folder,
                        language_profile_id=language_profile_id,
                        tags=cfg.defaults.series_add_tags,
                    )
                    self.client_service.log_activity(
                        user_id,
                        "serie.agregar",
                        f"tvdbId={tvdb_id} res={resolution} audio={audio} q={quality_profile_id}",
                    )
                    await query.edit_message_text(
                        f"Serie agregada: {data.get('title')} (res={resolution}, audio={audio})"
                    )
                    return

                if action == "madd":
                    tmdb_id = int(raw_id)
                    _, _, quality_profile_id = self._resolve_movie_profiles(options)
                    radarr = RadarrClient(cfg.radarr.base_url, cfg.radarr.api_token)
                    data = await radarr.add(
                        tmdb_id=tmdb_id,
                        quality_profile_id=quality_profile_id,
                        root_folder_path=cfg.defaults.movies_root_folder,
                        tags=cfg.defaults.movies_add_tags,
                    )
                    self.client_service.log_activity(
                        user_id,
                        "pelicula.agregar",
                        f"tmdbId={tmdb_id} res={resolution} audio={audio} q={quality_profile_id}",
                    )
                    await query.edit_message_text(
                        f"Pelicula agregada: {data.get('title')} (res={resolution}, audio={audio})"
                    )
                    return

                await query.edit_message_text("Accion desconocida")
            except ValueError:
                await query.edit_message_text("El valor recibido no es valido")
            except ArrClientError as exc:
                await query.edit_message_text(f"Error: {exc}")
            return
        
        await query.edit_message_text("Accion invalida")
