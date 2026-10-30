"""Configurable, read-only smoke checks for projects saved in the local dashboard.

One pytest case is generated for every configured Browser/API check, making a
project run produce a useful per-check JUnit summary. All web actions are GET or
HEAD and restricted to the configured public host.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import pytest
import requests
from playwright.sync_api import expect

MAX_TARGET_BROWSER_REQUESTS = 60
MAX_TARGET_API_RESPONSE_BYTES = 1_000_000

from dashboard.url_scanner import validate_public_url


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.fail(f"Missing {name}. Start this check from the ShopGuard dashboard.")
    return value


def _safe_api_path(value: str) -> str:
    parsed = urlsplit(value)
    if (
        not value.startswith("/") or value.startswith("//") or parsed.scheme
        or parsed.netloc or parsed.fragment or "\\" in parsed.path
        or any(part == ".." for part in parsed.path.split("/"))
        or any(ord(char) < 32 for char in value)
    ):
        pytest.fail("Configured API path must be a safe relative path such as /api/health.")
    return value


def _safe_browser_path(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if (
        not value.startswith("/") or value.startswith("//") or parsed.scheme
        or parsed.netloc or parsed.fragment or "\\" in parsed.path
        or any(part == ".." for part in parsed.path.split("/"))
        or any(ord(char) < 32 for char in value)
    ):
        pytest.fail("Configured browser path must be a safe relative path such as /products.")
    return value


def _load_configured_checks(env_name: str, legacy: dict) -> list[dict]:
    raw = os.getenv(env_name, "").strip()
    if raw:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            pytest.fail(f"Configured checks are not valid JSON: {exc}")
        if not isinstance(value, list) or not value or len(value) > 20:
            pytest.fail("Configured checks must be a non-empty list of at most 20 items.")
        return value
    return [legacy]


def _configured_browser_checks() -> list[dict]:
    return _load_configured_checks("SHOPGUARD_TARGET_BROWSER_CHECKS", {
        "id": "browser-1", "name": "Storefront",
        "path": os.getenv("SHOPGUARD_TARGET_BROWSER_PATH", ""),
        "expected_title": os.getenv("SHOPGUARD_TARGET_EXPECTED_TITLE", ""),
        "expected_h1": os.getenv("SHOPGUARD_TARGET_EXPECTED_H1", ""),
        "required_text": os.getenv("SHOPGUARD_TARGET_REQUIRED_TEXT", ""),
    })


def _configured_api_checks() -> list[dict]:
    raw = os.getenv("SHOPGUARD_TARGET_API_CHECKS", "").strip()
    if raw == "[]":
        return []  # Browser-only saved projects intentionally have no API cases.
    try:
        legacy_assertions = json.loads(os.getenv("SHOPGUARD_TARGET_API_JSON_ASSERTIONS", "[]"))
        legacy_status = int(os.getenv("SHOPGUARD_TARGET_EXPECTED_STATUS", "200"))
    except (TypeError, ValueError) as exc:
        pytest.fail(f"Legacy API check settings are invalid: {exc}")
    return _load_configured_checks("SHOPGUARD_TARGET_API_CHECKS", {
        "id": "api-1", "name": "API endpoint",
        "path": os.getenv("SHOPGUARD_TARGET_API_PATH", "/"),
        "expected_status": legacy_status,
        "expected_content_type": os.getenv("SHOPGUARD_TARGET_API_EXPECTED_CONTENT_TYPE", ""),
        "json_assertions": legacy_assertions,
    })


def _configured_json_assertions(value: object = None) -> list[dict]:
    if value is None:
        try:
            value = json.loads(os.getenv("SHOPGUARD_TARGET_API_JSON_ASSERTIONS", "[]"))
        except (TypeError, ValueError) as exc:
            pytest.fail(f"Configured JSON assertions are not valid JSON: {exc}")
    if not isinstance(value, list) or len(value) > 20:
        pytest.fail("Configured JSON assertions must be a list of at most 20 items.")
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or "expected" not in item:
            pytest.fail("Each JSON assertion needs a dotted field path and an expected value.")
        path = item["path"]
        if len(path) > 160 or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_-]*(?:\[(?:0|[1-9]\d*)\])?(?:\.[A-Za-z_][A-Za-z0-9_-]*(?:\[(?:0|[1-9]\d*)\])?)*", path
        ):
            pytest.fail("JSON assertion paths must use dotted object keys, for example data.status.")
        expected = item["expected"]
        if isinstance(expected, (dict, list)) or not (
            expected is None or isinstance(expected, (str, int, float, bool))
        ):
            pytest.fail("JSON assertions support string, number, true, false or null values.")
    return value


def _json_field_value(payload: object, field_path: str) -> object:
    current = payload
    path_parts = re.findall(r"([A-Za-z_][A-Za-z0-9_-]*)(?:\[(\d+)\])?", field_path)
    for key, index in path_parts:
        if not isinstance(current, dict) or key not in current:
            pytest.fail(f"JSON response is missing required field '{field_path}'.")
        current = current[key]
        if index:
            if not isinstance(current, list) or int(index) >= len(current):
                pytest.fail(f"JSON response is missing required field '{field_path}'.")
            current = current[int(index)]
    return current


def _same_json_value(actual: object, expected: object) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


def _validate_browser_request(url: str, method: str, primary_host: str) -> bool:
    """Allow only public GET/HEAD requests to the configured target host."""
    parsed = urlsplit(url)
    if parsed.scheme in {"data", "blob", "about"}:
        return True
    if parsed.scheme not in {"http", "https"} or method.upper() not in {"GET", "HEAD"}:
        return False
    try:
        safe_url = validate_public_url(url)
    except ValueError:
        return False
    return (urlsplit(safe_url).hostname or "").lower() == primary_host


def _artifact_prefix() -> Path | None:
    raw = os.getenv("SHOPGUARD_TARGET_ARTIFACT_PREFIX", "").strip()
    if not raw:
        return None
    prefix = Path(raw).resolve()
    reports = (Path.cwd() / "reports").resolve()
    if not prefix.parent.is_relative_to(reports):
        return None
    if not re.fullmatch(r"target_[A-Za-z0-9_-]{1,100}", prefix.name):
        return None
    prefix.parent.mkdir(parents=True, exist_ok=True)
    return prefix


def _write_evidence(kind: str, check: dict, details: dict, page=None) -> None:
    prefix = _artifact_prefix()
    if prefix is None:
        return
    check_id = re.sub(r"[^A-Za-z0-9_-]", "", str(check.get("id", "check")))[:40] or "check"
    payload = {
        "check_type": kind,
        "check_id": check_id,
        "check_name": str(check.get("name", "Unnamed check"))[:80],
        "captured_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "details": details,
    }
    evidence_path = prefix.with_name(f"{prefix.name}-{kind}-{check_id}.json")
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if page is not None:
        try:
            page.screenshot(path=str(prefix.with_name(f"{prefix.name}-{kind}-{check_id}.png")), full_page=True, animations="disabled")
        except Exception as exc:
            print(f"Failure screenshot unavailable: {exc.__class__.__name__}")


def pytest_generate_tests(metafunc):
    if "browser_check" in metafunc.fixturenames:
        checks = _configured_browser_checks()
        metafunc.parametrize("browser_check", checks, ids=[str(item.get("name", item.get("id", i))) for i, item in enumerate(checks)])
    if "api_check" in metafunc.fixturenames:
        checks = _configured_api_checks()
        if checks:
            metafunc.parametrize("api_check", checks, ids=[str(item.get("name", item.get("id", i))) for i, item in enumerate(checks)])
        else:
            metafunc.parametrize(
                "api_check",
                [pytest.param(None, id="no-api-check", marks=pytest.mark.skip(reason="No API checks configured for this project."))],
            )


@pytest.mark.target_ui
def test_registered_project_storefront(shop_page, browser_check):
    """Open one configured storefront page without clicking or submitting anything."""
    target_url = validate_public_url(_required_env("SHOPGUARD_TARGET_URL"))
    browser_path = _safe_browser_path(str(browser_check.get("path", "")))
    if browser_path:
        base = urlsplit(target_url)
        target_url = urlunsplit((base.scheme, base.netloc, urlsplit(browser_path).path, urlsplit(browser_path).query, ""))
    primary_host = (urlsplit(target_url).hostname or "").lower()
    request_count = 0
    response = None
    page_title = ""
    visible_h1: list[str] = []
    body_text = ""

    def guard_request(route):
        nonlocal request_count
        request_count += 1
        request = route.request
        if request_count <= MAX_TARGET_BROWSER_REQUESTS and _validate_browser_request(request.url, request.method, primary_host):
            route.continue_()
        else:
            route.abort("blockedbyclient")

    shop_page.context.route("**/*", guard_request)
    try:
        response = shop_page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
        shop_page.wait_for_timeout(250)
        assert response is not None, "The browser did not receive a main document response."
        assert 200 <= response.status < 400, f"Storefront returned HTTP {response.status} for {target_url}."
        expect(shop_page.locator("body")).to_be_visible()
        body_text = " ".join((shop_page.locator("body").inner_text(timeout=5000) or "").split())
        page_title = (shop_page.title() or "").strip()
        visible_h1 = [" ".join(value.split()) for value in shop_page.locator("h1:visible").all_inner_texts()]
        assert body_text, "The storefront body is empty."
        assert page_title or visible_h1, "The page has neither a document title nor a visible H1."
        expected_title = str(browser_check.get("expected_title", "")).strip()
        expected_h1 = str(browser_check.get("expected_h1", "")).strip()
        required_text = str(browser_check.get("required_text", "")).strip()
        if expected_title:
            assert expected_title.casefold() in page_title.casefold(), (
                f"Page title does not contain expected text '{expected_title}'. Actual title: '{page_title}'."
            )
        if expected_h1:
            assert any(expected_h1.casefold() in heading.casefold() for heading in visible_h1), (
                f"No visible H1 contains expected text '{expected_h1}'. Actual H1: {visible_h1[:5]}."
            )
        if required_text:
            assert required_text.casefold() in body_text.casefold(), (
                f"Page text does not contain required text '{required_text}'."
            )
        final_host = (urlsplit(validate_public_url(shop_page.url)).hostname or "").lower()
        assert final_host == primary_host, "The storefront navigated away from the configured host."
    except Exception as exc:
        _write_evidence("browser", browser_check, {
            "requested_url": target_url,
            "actual_url": shop_page.url,
            "http_status": response.status if response is not None else None,
            "expected": {
                "title_contains": browser_check.get("expected_title", ""),
                "h1_contains": browser_check.get("expected_h1", ""),
                "text_contains": browser_check.get("required_text", ""),
            },
            "actual": {"title": page_title, "visible_h1": visible_h1[:10]},
            "error": str(exc)[:1200],
        }, page=shop_page)
        raise


@pytest.mark.target_api
def test_registered_project_api_endpoint(api_check):
    """Send one GET request to one configured API endpoint and verify assertions."""
    api_base = validate_public_url(_required_env("SHOPGUARD_TARGET_API_URL"))
    api_path = _safe_api_path(str(api_check.get("path", "/")))
    try:
        expected_status = int(api_check.get("expected_status", 200))
    except (TypeError, ValueError) as exc:
        pytest.fail(f"Expected HTTP status is not a valid number: {exc}")
    assert 100 <= expected_status <= 599, "Expected HTTP status must be between 100 and 599."
    endpoint = urljoin(api_base.rstrip("/") + "/", api_path.lstrip("/"))
    assert (urlsplit(endpoint).hostname or "").lower() == (urlsplit(api_base).hostname or "").lower()
    response = None
    try:
        response = requests.get(
            endpoint,
            headers={"Accept": "application/json, text/plain, */*", "User-Agent": "ShopGuard-QA/1.0"},
            timeout=(5, 15), allow_redirects=False, stream=True,
        )
        assertions = _configured_json_assertions(api_check.get("json_assertions", []))
        expected_content_type = str(api_check.get("expected_content_type", "")).strip()
        content_type = response.headers.get("Content-Type", "").lower()
        assert response.status_code == expected_status, (
            f"GET {endpoint}: expected HTTP {expected_status}, received {response.status_code}."
        )
        if expected_content_type:
            assert expected_content_type.casefold() in content_type.casefold(), (
                f"Expected Content-Type to contain '{expected_content_type}', received '{content_type or 'missing'}'."
            )
        body = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            if len(body) + len(chunk) > MAX_TARGET_API_RESPONSE_BYTES:
                pytest.fail(f"API response exceeded the {MAX_TARGET_API_RESPONSE_BYTES}-byte safety limit.")
            body.extend(chunk)
        if "json" in content_type or assertions:
            json_payload = json.loads(bytes(body))
            for assertion in assertions:
                actual = _json_field_value(json_payload, assertion["path"])
                assert _same_json_value(actual, assertion["expected"]), (
                    f"JSON field '{assertion['path']}' expected {assertion['expected']!r}, received {actual!r}."
                )
    except (Exception, pytest.fail.Exception) as exc:
        _write_evidence("api", api_check, {
            "endpoint": endpoint,
            "expected": {
                "http_status": expected_status,
                "content_type_contains": api_check.get("expected_content_type", ""),
                "json_assertions": api_check.get("json_assertions", []),
            },
            "actual": {
                "http_status": response.status_code if response is not None else None,
                "content_type": response.headers.get("Content-Type", "") if response is not None else None,
            },
            "error": str(exc)[:1200],
        })
        raise
    finally:
        if response is not None:
            response.close()
