from __future__ import annotations

import pytest


@pytest.fixture
def sonarr_client():
    from app.arr_clients import SonarrClient
    return SonarrClient("http://sonarr:8989", "test-token")


@pytest.fixture
def radarr_client():
    from app.arr_clients import RadarrClient
    return RadarrClient("http://radarr:7878", "test-token")


@pytest.fixture
def base_client():
    from app.arr_clients import BaseArrClient
    return BaseArrClient("http://arr:5050", "token")


class TestBaseArrClient:
    @pytest.mark.asyncio
    async def test_missing_config_raises_error(self):
        from app.arr_clients import ArrClientError, BaseArrClient
        client = BaseArrClient("", "")
        with pytest.raises(ArrClientError, match="Falta configurar"):
            await client._request("GET", "/test")

    @pytest.mark.asyncio
    async def test_resolve_tag_names_to_ids_empty(self, base_client, httpx_mock):
        ids = await base_client.resolve_tag_names_to_ids([])
        assert ids == []

    @pytest.mark.asyncio
    async def test_resolve_tag_names_to_ids(self, base_client, httpx_mock):
        httpx_mock.add_response(
            url="http://arr:5050/api/v5/tag",
            json=[{"id": 1, "label": "tv"}, {"id": 2, "label": "movies"}],
        )
        ids = await base_client.resolve_tag_names_to_ids(["tv", "movies"])
        assert ids == [1, 2]

    @pytest.mark.asyncio
    async def test_resolve_tag_names_to_ids_case_insensitive(self, base_client, httpx_mock):
        httpx_mock.add_response(
            url="http://arr:5050/api/v5/tag",
            json=[{"id": 1, "label": "TV"}, {"id": 2, "label": "Movies"}],
        )
        ids = await base_client.resolve_tag_names_to_ids(["tv", "movies"])
        assert ids == [1, 2]

    @pytest.mark.asyncio
    async def test_resolve_tag_names_to_ids_numeric_fallback(self, base_client, httpx_mock):
        httpx_mock.add_response(
            url="http://arr:5050/api/v5/tag",
            json=[{"id": 1, "label": "tv"}],
        )
        ids = await base_client.resolve_tag_names_to_ids(["999"])
        assert ids == [999]

    @pytest.mark.asyncio
    async def test_resolve_tag_names_unknown_ignored(self, base_client, httpx_mock):
        httpx_mock.add_response(
            url="http://arr:5050/api/v5/tag",
            json=[{"id": 1, "label": "tv"}],
        )
        ids = await base_client.resolve_tag_names_to_ids(["nonexistent"])
        assert ids == []

    @pytest.mark.asyncio
    async def test_request_versioned_fallback_v3(self, base_client, httpx_mock):
        httpx_mock.add_response(
            url="http://arr:5050/api/v5/series",
            status_code=404,
            text="Not Found",
        )
        httpx_mock.add_response(
            url="http://arr:5050/api/v3/series",
            json=[{"id": 1, "title": "Series from v3"}],
        )
        result = await base_client._request_versioned("GET", "/series")
        assert result == [{"id": 1, "title": "Series from v3"}]

    @pytest.mark.asyncio
    async def test_request_versioned_raises_on_non_404_v5(self, base_client, httpx_mock):
        from app.arr_clients import ArrClientError
        httpx_mock.add_response(
            url="http://arr:5050/api/v5/series",
            status_code=500,
            text="Server Error",
        )
        with pytest.raises(ArrClientError, match="500"):
            await base_client._request_versioned("GET", "/series")


class TestSonarrClient:
    @pytest.mark.asyncio
    async def test_list_all(self, sonarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/series",
            json=[{"id": 1, "title": "Test Series"}],
        )
        result = await sonarr_client.list_all()
        assert result == [{"id": 1, "title": "Test Series"}]

    @pytest.mark.asyncio
    async def test_search_local(self, sonarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/series",
            json=[
                {"id": 1, "title": "Breaking Bad"},
                {"id": 2, "title": "Better Call Saul"},
            ],
        )
        result = await sonarr_client.search_local("breaking")
        assert len(result) == 1
        assert result[0]["title"] == "Breaking Bad"

    @pytest.mark.asyncio
    async def test_search_api(self, sonarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/series/lookup?term=test",
            json=[{"id": 10, "title": "Test Show", "tvdbId": 100}],
        )
        result = await sonarr_client.search("test")
        assert result == [{"id": 10, "title": "Test Show", "tvdbId": 100}]

    @pytest.mark.asyncio
    async def test_get(self, sonarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/series/1",
            json={"id": 1, "title": "Series Detail"},
        )
        result = await sonarr_client.get(1)
        assert result["title"] == "Series Detail"

    @pytest.mark.asyncio
    async def test_delete(self, sonarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/series/1?deleteFiles=false&addImportListExclusion=false",
            status_code=200,
        )
        await sonarr_client.delete(1)

    @pytest.mark.asyncio
    async def test_add_raises_already_exists(self, sonarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/series",
            json=[{"id": 1, "tvdbId": 100, "title": "Existing"}],
        )
        from app.arr_clients import ArrAlreadyExistsError
        with pytest.raises(ArrAlreadyExistsError):
            await sonarr_client.add(100, 4, "/tv")

    @pytest.mark.asyncio
    async def test_add_success(self, sonarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/series",
            json=[],
        )
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/series/lookup?term=tvdb%3A200",
            json=[{"tvdbId": 200, "title": "New Show", "titleSlug": "new-show", "images": []}],
        )
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/series",
            status_code=201,
            json={"id": 5, "title": "New Show"},
        )
        result = await sonarr_client.add(200, 4, "/tv")
        assert result["id"] == 5

    @pytest.mark.asyncio
    async def test_list_episodes(self, sonarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://sonarr:8989/api/v5/episode?seriesId=1",
            json=[{"id": 1, "episodeNumber": 1}],
        )
        result = await sonarr_client.list_episodes(1)
        assert result == [{"id": 1, "episodeNumber": 1}]


class TestRadarrClient:
    @pytest.mark.asyncio
    async def test_list_all(self, radarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://radarr:7878/api/v5/movie",
            json=[{"id": 1, "title": "Test Movie"}],
        )
        result = await radarr_client.list_all()
        assert result == [{"id": 1, "title": "Test Movie"}]

    @pytest.mark.asyncio
    async def test_search_local(self, radarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://radarr:7878/api/v5/movie",
            json=[
                {"id": 1, "title": "The Matrix"},
                {"id": 2, "title": "Matrix Reloaded"},
            ],
        )
        result = await radarr_client.search_local("matrix")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_search_api(self, radarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://radarr:7878/api/v5/movie/lookup?term=inception",
            json=[{"id": 10, "title": "Inception", "tmdbId": 100}],
        )
        result = await radarr_client.search("inception")
        assert result == [{"id": 10, "title": "Inception", "tmdbId": 100}]

    @pytest.mark.asyncio
    async def test_get(self, radarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://radarr:7878/api/v5/movie/1",
            json={"id": 1, "title": "Movie Detail"},
        )
        result = await radarr_client.get(1)
        assert result["title"] == "Movie Detail"

    @pytest.mark.asyncio
    async def test_delete(self, radarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://radarr:7878/api/v5/movie/1?deleteFiles=false&addImportListExclusion=false",
            status_code=200,
        )
        await radarr_client.delete(1)

    @pytest.mark.asyncio
    async def test_add_raises_already_exists(self, radarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://radarr:7878/api/v5/movie",
            json=[{"id": 1, "tmdbId": 100, "title": "Existing Movie"}],
        )
        from app.arr_clients import ArrAlreadyExistsError
        with pytest.raises(ArrAlreadyExistsError):
            await radarr_client.add(100, 3, "/movies")

    @pytest.mark.asyncio
    async def test_add_success(self, radarr_client, httpx_mock):
        httpx_mock.add_response(
            url="http://radarr:7878/api/v5/movie",
            json=[],
        )
        httpx_mock.add_response(
            url="http://radarr:7878/api/v5/movie/lookup?term=tmdb%3A200",
            json=[{"tmdbId": 200, "title": "New Movie", "titleSlug": "new-movie", "images": []}],
        )
        httpx_mock.add_response(
            url="http://radarr:7878/api/v5/movie",
            status_code=201,
            json={"id": 5, "title": "New Movie"},
        )
        result = await radarr_client.add(200, 3, "/movies")
        assert result["id"] == 5
