from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

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
        app.add_handler(CallbackQueryHandler(self.on_callback))

        return app

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
        if len(parts) == 2 and parts[0] in ("sinfo", "sdel", "minfo", "mdel"):
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
                    
                    if seasons:
                        msg += "Temporadas:\n"
                        for season in sorted(seasons, key=lambda x: x.get('seasonNumber', 0)):
                            season_num = season.get('seasonNumber', 0)
                            episode_count = season.get('statistics', {}).get('episodeCount', 0)
                            downloaded = season.get('statistics', {}).get('episodeFileCount', 0)
                            msg += f"  S{season_num:02d}: {downloaded}/{episode_count}\n"
                    
                    await query.edit_message_text(msg)
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
                
                # Mostrar info de episodios si hay monitoreo
                msg += "Usa /serie estado <id> para ver mas detalles"
                
                await query.edit_message_text(msg)
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
