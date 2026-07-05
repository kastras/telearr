from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.helpers import parse_value_and_options, profile_key, resolution_options, safe_reply_target


class TestHelpers:
    def test_safe_reply_target(self):
        update = MagicMock()
        update.effective_message = "test_message"
        assert safe_reply_target(update) == "test_message"

    def test_parse_value_and_options_basic(self):
        value, options = parse_value_and_options(["Breaking", "Bad"])
        assert value == "Breaking Bad"
        assert options == {}

    def test_parse_value_and_options_with_options(self):
        value, options = parse_value_and_options(["Breaking", "res=1080p", "audio=multi"])
        assert value == "Breaking"
        assert options == {"res": "1080p", "audio": "multi"}

    def test_parse_value_and_options_only_options(self):
        value, options = parse_value_and_options(["res=4k", "audio=es"])
        assert value == ""
        assert options == {"res": "4k", "audio": "es"}

    def test_parse_value_and_options_case_insensitive(self):
        value, options = parse_value_and_options(["Test", "RES=1080P"])
        assert options == {"res": "1080p"}

    def test_parse_value_and_options_empty(self):
        value, options = parse_value_and_options([])
        assert value == ""
        assert options == {}

    def test_profile_key(self):
        assert profile_key("1080p", "multi") == "1080p|multi"

    def test_profile_key_normalizes_case(self):
        assert profile_key("1080P", "Multi") == "1080p|multi"

    def test_resolution_options_from_map(self):
        result = resolution_options({"1080p|multi": 4, "720p|multi": 3}, "")
        assert "1080p" in result
        assert "720p" in result

    def test_resolution_options_with_default(self):
        result = resolution_options({"1080p|multi": 4}, "4k")
        assert "4k" in result
        assert "1080p" in result

    def test_resolution_options_empty_fallback(self):
        result = resolution_options({}, "")
        assert result == ["1080p"]

    def test_resolution_options_ordering(self):
        result = resolution_options({"4k|multi": 6, "1080p|multi": 4, "720p|multi": 3, "480p|multi": 2}, "")
        assert result == ["4k", "1080p", "720p", "480p"]


class TestTelegramBotService:
    @pytest.fixture
    def service(self):
        from app.telegram_bot import TelegramBotService

        config_manager = MagicMock()
        config_manager.config.defaults.series_default_resolution = "1080p"
        config_manager.config.defaults.series_default_audio = "multi"
        config_manager.config.defaults.movies_default_resolution = "4k"
        config_manager.config.defaults.movies_default_audio = "multi"
        config_manager.config.defaults.series_quality_profile_id = 1
        config_manager.config.defaults.movies_quality_profile_id = 1
        config_manager.config.defaults.series_quality_profiles = {
            "1080p|multi": 4,
            "720p|multi": 3,
        }
        config_manager.config.defaults.movies_quality_profiles = {
            "4k|multi": 6,
            "1080p|multi": 5,
        }
        config_manager.config.defaults.series_language_profiles = {
            "multi": 1,
        }
        config_manager.config.defaults.series_add_tags = []
        config_manager.config.defaults.movies_add_tags = []
        config_manager.config.defaults.series_root_folder = "/tv"
        config_manager.config.defaults.movies_root_folder = "/movies"
        config_manager.config.sonarr.base_url = "http://sonarr:8989"
        config_manager.config.sonarr.api_token = "token"
        config_manager.config.radarr.base_url = "http://radarr:7878"
        config_manager.config.radarr.api_token = "token"
        config_manager.config.telegram.bot_token = "bot:token"

        client_service = MagicMock()
        client_service.get_client_state.return_value = {
            "approved": 1,
            "blocked": 0,
            "telegram_user_id": 123,
            "username": "test",
        }

        return TelegramBotService(config_manager, client_service)

    def test_resolve_series_profiles_default(self, service):
        res, audio, qid, lid = service._resolve_series_profiles({})
        assert res == "1080p"
        assert audio == "multi"
        assert qid == 4
        assert lid == 1

    def test_resolve_series_profiles_custom(self, service):
        res, audio, qid, lid = service._resolve_series_profiles({"res": "720p", "audio": "multi"})
        assert res == "720p"
        assert qid == 3

    def test_resolve_series_profiles_fallback_when_no_match(self, service):
        res, audio, qid, lid = service._resolve_series_profiles({"res": "480p", "audio": "unknown"})
        assert qid == 1
        assert lid is None

    def test_resolve_movie_profiles_default(self, service):
        res, audio, qid = service._resolve_movie_profiles({})
        assert res == "4k"
        assert audio == "multi"
        assert qid == 6

    def test_resolve_movie_profiles_custom(self, service):
        res, audio, qid = service._resolve_movie_profiles({"res": "1080p"})
        assert qid == 5

    @pytest.mark.asyncio
    async def test_check_access_approved_user(self, service):
        update = MagicMock()
        update.effective_user.id = 123
        update.effective_user.username = "test"
        update.effective_user.first_name = "Test"
        update.effective_user.last_name = "User"

        ok, user_id = await service._check_access(update)
        assert ok is True
        assert user_id == 123

    @pytest.mark.asyncio
    async def test_check_access_blocked_user(self, service):
        service.client_service.get_client_state.return_value = {
            "approved": 0,
            "blocked": 1,
            "telegram_user_id": 456,
        }
        update = MagicMock()
        update.effective_user.id = 456
        update.effective_user.username = "blocked"
        update.effective_user.first_name = "Blocked"
        update.effective_user.last_name = "User"
        message = AsyncMock()
        message.reply_text = AsyncMock()
        update.effective_message = message

        ok, user_id = await service._check_access(update)
        assert ok is False

    @pytest.mark.asyncio
    async def test_check_access_unapproved_user(self, service):
        service.client_service.get_client_state.return_value = {
            "approved": 0,
            "blocked": 0,
            "telegram_user_id": 789,
        }
        service.client_service.create_pair_token.return_value = ("test-token", "2099-01-01T00:00:00+00:00")

        update = MagicMock()
        update.effective_user.id = 789
        update.effective_user.username = "unapproved"
        update.effective_user.first_name = "Unapproved"
        update.effective_user.last_name = "User"
        message = AsyncMock()
        message.reply_text = AsyncMock()
        update.effective_message = message

        ok, user_id = await service._check_access(update)
        assert ok is False

    def test_callback_dispatcher_has_all_handlers(self, service):
        handlers = service._callback_handlers
        expected_prefixes = [
            "tgtype", "tgnew", "snav", "mnav", "sq", "mq",
            "smenu", "mmenu", "sinfo", "sdel", "minfo", "mdel",
            "ssearch", "sep", "sstate", "sadd", "madd",
        ]
        for prefix in expected_prefixes:
            assert prefix in handlers, f"Missing handler for {prefix}"

    @pytest.mark.asyncio
    async def test_on_callback_invalid_action(self, service):
        update = MagicMock()
        query = AsyncMock()
        query.data = "invalid|action"
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.username = "test"

        context = MagicMock()

        await service.on_callback(update, context)
        query.answer.assert_called_with("Acción inválida")

    @pytest.mark.asyncio
    async def test_cb_type_select_series(self, service):
        update = MagicMock()
        query = AsyncMock()
        query.data = "tgtype|serie"
        query.message = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.username = "test"

        context = MagicMock()
        context.user_data = {"pending_query": "Breaking Bad"}

        with patch.object(service, "_run_series_search_flow", new=AsyncMock()) as mock_flow:
            await service._cb_type_select(update, context, 123)
            mock_flow.assert_called_once()

    @pytest.mark.asyncio
    async def test_cb_quality_select_series(self, service):
        update = MagicMock()
        query = AsyncMock()
        query.data = "sq|100"
        query.message = AsyncMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query

        await service._cb_quality_select(update, MagicMock(), 123)
        query.message.reply_text.assert_called_once()
        call_args = query.message.reply_text.call_args[0]
        assert "Elige calidad para la serie" in call_args[0]

    @pytest.mark.asyncio
    async def test_cb_quality_select_movie(self, service):
        update = MagicMock()
        query = AsyncMock()
        query.data = "mq|200"
        query.message = AsyncMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query

        await service._cb_quality_select(update, MagicMock(), 123)
        query.message.reply_text.assert_called_once()
        call_args = query.message.reply_text.call_args[0]
        assert "Elige calidad para la película" in call_args[0]

    @pytest.mark.asyncio
    async def test_cb_menu_action_smenu(self, service):
        update = MagicMock()
        query = AsyncMock()
        query.data = "smenu|buscar"
        update.callback_query = query

        await service._cb_menu_action(update, MagicMock(), 123)
        query.edit_message_text.assert_called_with("📺 Escribe el nombre de la serie a buscar")

    @pytest.mark.asyncio
    async def test_cb_menu_action_mmenu(self, service):
        update = MagicMock()
        query = AsyncMock()
        query.data = "mmenu|borrar"
        update.callback_query = query

        await service._cb_menu_action(update, MagicMock(), 123)
        query.edit_message_text.assert_called_with("🎬 Escribe el radarrId para borrar")

    def test_build_application(self, service):
        app = service.build_application()
        assert app is not None

    @pytest.mark.asyncio
    async def test_on_start_approved(self, service):
        update = MagicMock()
        update.effective_user.id = 123
        update.message = AsyncMock()

        await service.on_start(update, MagicMock())
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_help(self, service):
        update = MagicMock()
        update.message = AsyncMock()

        await service.on_help(update, MagicMock())
        update.message.reply_text.assert_called_once()
        assert "/serie buscar" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_free_text_triggers_type_selection(self, service):
        update = MagicMock()
        update.effective_user.id = 123
        update.effective_user.username = "test"
        update.effective_user.first_name = "Test"
        message = AsyncMock()
        message.text = "Dark"
        update.effective_message = message

        await service.on_free_text(update, MagicMock())
        message.reply_text.assert_called_once()
        args = message.reply_text.call_args[1]
        assert "reply_markup" in args
