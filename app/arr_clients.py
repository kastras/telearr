from __future__ import annotations

from typing import Any

import httpx


class ArrClientError(Exception):
    pass


class BaseArrClient:
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if not self.base_url or not self.api_token:
            raise ArrClientError("Falta configurar URL o API token")

        headers = {"X-Api-Key": self.api_token}
        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.request(method, url, headers=headers, params=params, json=json_body)
        if res.status_code >= 400:
            raise ArrClientError(f"{res.status_code}: {res.text[:200]}")
        if not res.content:
            return None
        return res.json()


class SonarrClient(BaseArrClient):
    async def list_all(self) -> list[dict[str, Any]]:
        """Lista todas las series agregadas localmente."""
        data = await self._request("GET", "/api/v3/series")
        return data if isinstance(data, list) else []

    async def search_local(self, term: str) -> list[dict[str, Any]]:
        """Busca en series agregadas localmente."""
        term_lower = term.lower()
        all_series = await self.list_all()
        return [s for s in all_series if term_lower in s.get("title", "").lower()]

    async def search(self, term: str) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/v3/series/lookup", params={"term": term})
        return data if isinstance(data, list) else []

    async def get(self, series_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/v3/series/{series_id}")

    async def delete(self, series_id: int) -> None:
        await self._request(
            "DELETE",
            f"/api/v3/series/{series_id}",
            params={"deleteFiles": "false", "addImportExclusion": "false"},
        )

    async def add(
        self,
        tvdb_id: int,
        quality_profile_id: int,
        root_folder_path: str,
        language_profile_id: int | None = None,
    ) -> dict[str, Any]:
        lookup = await self.search(f"tvdb:{tvdb_id}")
        if not lookup:
            raise ArrClientError("No se encontro la serie por tvdbId")

        candidate = next((x for x in lookup if x.get("tvdbId") == tvdb_id), lookup[0])
        payload = {
            "tvdbId": candidate["tvdbId"],
            "title": candidate["title"],
            "titleSlug": candidate.get("titleSlug") or candidate["title"].lower().replace(" ", "-"),
            "images": candidate.get("images", []),
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": True,
            "addOptions": {"searchForMissingEpisodes": True},
        }
        if language_profile_id is not None:
            payload["languageProfileId"] = language_profile_id
        return await self._request("POST", "/api/v3/series", json_body=payload)


class RadarrClient(BaseArrClient):
    async def list_all(self) -> list[dict[str, Any]]:
        """Lista todas las películas agregadas localmente."""
        data = await self._request("GET", "/api/v3/movie")
        return data if isinstance(data, list) else []

    async def search_local(self, term: str) -> list[dict[str, Any]]:
        """Busca en películas agregadas localmente."""
        term_lower = term.lower()
        all_movies = await self.list_all()
        return [m for m in all_movies if term_lower in m.get("title", "").lower()]

    async def search(self, term: str) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/v3/movie/lookup", params={"term": term})
        return data if isinstance(data, list) else []

    async def get(self, movie_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/v3/movie/{movie_id}")

    async def delete(self, movie_id: int) -> None:
        await self._request(
            "DELETE",
            f"/api/v3/movie/{movie_id}",
            params={"deleteFiles": "false", "addImportListExclusion": "false"},
        )

    async def add(self, tmdb_id: int, quality_profile_id: int, root_folder_path: str) -> dict[str, Any]:
        lookup = await self.search(f"tmdb:{tmdb_id}")
        if not lookup:
            raise ArrClientError("No se encontro la pelicula por tmdbId")

        candidate = next((x for x in lookup if x.get("tmdbId") == tmdb_id), lookup[0])
        payload = {
            "tmdbId": candidate["tmdbId"],
            "title": candidate["title"],
            "titleSlug": candidate.get("titleSlug") or candidate["title"].lower().replace(" ", "-"),
            "images": candidate.get("images", []),
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": True,
            "addOptions": {"searchForMovie": True},
        }
        return await self._request("POST", "/api/v3/movie", json_body=payload)
