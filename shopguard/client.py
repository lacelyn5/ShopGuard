"""Thin HTTP client for GET-only public API checks and optional demo sign-in."""
from typing import Any

import requests


class ToolshopClient:
    def __init__(self, base_url: str, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = session if session is not None else requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "ShopGuard-QA/1.0 (education; low volume)"})

    def get(self, path: str, params: dict | None = None) -> requests.Response:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Only relative API routes are supported")
        return self.session.get(f"{self.base_url}{path}", params=params, timeout=(5, 20), allow_redirects=False)

    def post_json(self, path: str, payload: dict) -> requests.Response:
        if path != "/users/login":
            raise ValueError("Only the non-destructive public demo login endpoint is enabled")
        return self.session.post(f"{self.base_url}{path}", json=payload, timeout=(5, 20), allow_redirects=False)


def checked_json(response: requests.Response, status: int = 200) -> Any:
    assert response.status_code == status, (
        f"{response.request.method} {response.url}: expected {status}, got {response.status_code}. "
        f"Body: {response.text[:240]!r}"
    )
    assert "json" in response.headers.get("Content-Type", "").lower(), "not a JSON response"
    return response.json()
