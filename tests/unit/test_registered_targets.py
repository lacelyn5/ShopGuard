"""Deterministic checks for generic, locally registered target smoke tests."""
from __future__ import annotations

import pytest

from tests.targets import test_registered_project as target_checks


@pytest.mark.unit
def test_browser_target_guard_allows_only_public_same_host_get_or_head(monkeypatch):
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)

    assert target_checks._validate_browser_request(
        "https://shop.example.test/products", "GET", "shop.example.test"
    )
    assert target_checks._validate_browser_request(
        "https://shop.example.test/assets/site.css", "HEAD", "shop.example.test"
    )
    assert target_checks._validate_browser_request("data:image/png;base64,abc", "GET", "shop.example.test")
    assert not target_checks._validate_browser_request(
        "https://cdn.example.net/site.css", "GET", "shop.example.test"
    )
    assert not target_checks._validate_browser_request(
        "https://shop.example.test/cart", "POST", "shop.example.test"
    )
    assert not target_checks._validate_browser_request(
        "file:///etc/passwd", "GET", "shop.example.test"
    )


@pytest.mark.unit
def test_registered_api_check_uses_get_without_following_redirects(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "application/json; charset=utf-8"}

        @staticmethod
        def iter_content(chunk_size=8192):
            yield b'{"ok": true}'

        @staticmethod
        def close():
            return None

    captured = {}
    monkeypatch.setenv("SHOPGUARD_TARGET_API_URL", "https://api.example.test")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_PATH", "/api/health")
    monkeypatch.setenv("SHOPGUARD_TARGET_EXPECTED_STATUS", "200")
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(target_checks.requests, "get", fake_get)
    target_checks.test_registered_project_api_endpoint(target_checks._configured_api_checks()[0])

    assert captured["url"] == "https://api.example.test/api/health"
    assert captured["timeout"] == (5, 15)
    assert captured["allow_redirects"] is False


@pytest.mark.unit
def test_registered_api_check_reports_unexpected_http_status(monkeypatch):
    class FakeResponse:
        status_code = 503
        headers = {"Content-Type": "text/plain"}

        @staticmethod
        def iter_content(chunk_size=8192):
            yield b"service unavailable"

        @staticmethod
        def close():
            return None

    monkeypatch.setenv("SHOPGUARD_TARGET_API_URL", "https://api.example.test")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_PATH", "/health")
    monkeypatch.setenv("SHOPGUARD_TARGET_EXPECTED_STATUS", "200")
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)
    monkeypatch.setattr(target_checks.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(AssertionError, match="expected HTTP 200, received 503"):
        target_checks.test_registered_project_api_endpoint(target_checks._configured_api_checks()[0])


@pytest.mark.unit
def test_api_check_verifies_configured_json_fields_and_expected_content_type(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "application/json; charset=utf-8"}

        @staticmethod
        def iter_content(chunk_size=8192):
            yield b'{"status":"ok","data":{"active":true,"count":3}}'

        @staticmethod
        def close():
            return None

    monkeypatch.setenv("SHOPGUARD_TARGET_API_URL", "https://api.example.test")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_PATH", "/health")
    monkeypatch.setenv("SHOPGUARD_TARGET_EXPECTED_STATUS", "200")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_EXPECTED_CONTENT_TYPE", "application/json")
    monkeypatch.setenv(
        "SHOPGUARD_TARGET_API_JSON_ASSERTIONS",
        '[{"path":"status","expected":"ok"},{"path":"data.active","expected":true},{"path":"data.count","expected":3}]',
    )
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)
    monkeypatch.setattr(target_checks.requests, "get", lambda *args, **kwargs: FakeResponse())

    target_checks.test_registered_project_api_endpoint(target_checks._configured_api_checks()[0])


@pytest.mark.unit
def test_api_check_fails_when_configured_json_value_does_not_match(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "application/json"}

        @staticmethod
        def iter_content(chunk_size=8192):
            yield b'{"status":"degraded"}'

        @staticmethod
        def close():
            return None

    monkeypatch.setenv("SHOPGUARD_TARGET_API_URL", "https://api.example.test")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_PATH", "/health")
    monkeypatch.setenv("SHOPGUARD_TARGET_EXPECTED_STATUS", "200")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_JSON_ASSERTIONS", '[{"path":"status","expected":"ok"}]')
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)
    monkeypatch.setattr(target_checks.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(AssertionError, match="JSON field 'status' expected 'ok', received 'degraded'"):
        target_checks.test_registered_project_api_endpoint(target_checks._configured_api_checks()[0])


@pytest.mark.unit
def test_api_check_fails_when_required_json_field_is_missing(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "application/json"}

        @staticmethod
        def iter_content(chunk_size=8192):
            yield b'{"status":"ok"}'

        @staticmethod
        def close():
            return None

    monkeypatch.setenv("SHOPGUARD_TARGET_API_URL", "https://api.example.test")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_PATH", "/health")
    monkeypatch.setenv("SHOPGUARD_TARGET_EXPECTED_STATUS", "200")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_JSON_ASSERTIONS", '[{"path":"data.active","expected":true}]')
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)
    monkeypatch.setattr(target_checks.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(pytest.fail.Exception, match="missing required field 'data.active'"):
        target_checks.test_registered_project_api_endpoint(target_checks._configured_api_checks()[0])


@pytest.mark.unit
def test_json_assertion_parser_rejects_unsafe_paths(monkeypatch):
    monkeypatch.setenv("SHOPGUARD_TARGET_API_JSON_ASSERTIONS", '[{"path":"data..status","expected":"x"}]')
    with pytest.raises(pytest.fail.Exception, match="dotted object keys"):
        target_checks._configured_json_assertions()


@pytest.mark.unit
def test_browser_path_must_be_relative_and_same_host_friendly():
    assert target_checks._safe_browser_path("/products?page=2") == "/products?page=2"
    assert target_checks._safe_browser_path("") == ""
    for value in ("https://elsewhere.example/", "//elsewhere.example/", "/../admin", "/safe/..\\admin", "/products#section"):
        with pytest.raises(pytest.fail.Exception):
            target_checks._safe_browser_path(value)


@pytest.mark.unit
def test_boolean_json_assertions_do_not_match_integer_values():
    assert target_checks._same_json_value(True, True)
    assert not target_checks._same_json_value(1, True)
    assert target_checks._same_json_value(3, 3.0)


@pytest.mark.unit
def test_json_field_lookup_supports_zero_based_array_indexes():
    payload = {"data": {"items": [{"id": 42}, {"id": 43}]}}
    assert target_checks._json_field_value(payload, "data.items[0].id") == 42
    assert target_checks._json_field_value(payload, "data.items[1].id") == 43
    with pytest.raises(pytest.fail.Exception, match="missing required field"):
        target_checks._json_field_value(payload, "data.items[2].id")


@pytest.mark.unit
def test_browser_smoke_check_applies_configured_page_assertions(monkeypatch):
    from types import SimpleNamespace

    class DummyLocator:
        def __init__(self, selector):
            self.selector = selector

        def inner_text(self, timeout=5000):
            return "Products · Free delivery · Welcome"

        def count(self):
            return 1 if self.selector == "h1:visible" else 1

        def all_inner_texts(self):
            return ["Products"]

    class DummyExpect:
        @staticmethod
        def to_be_visible():
            return None

    class DummyContext:
        def route(self, pattern, callback):
            self.pattern = pattern
            self.callback = callback

    class DummyPage:
        def __init__(self):
            self.context = DummyContext()
            self.url = "https://shop.example.test/products"
            self.opened_url = None

        def goto(self, url, **kwargs):
            self.opened_url = url
            return SimpleNamespace(status=200)

        @staticmethod
        def wait_for_timeout(milliseconds):
            return None

        @staticmethod
        def locator(selector):
            return DummyLocator(selector)

        @staticmethod
        def title():
            return "My Shop Online"

    monkeypatch.setenv("SHOPGUARD_TARGET_URL", "https://shop.example.test")
    monkeypatch.setenv("SHOPGUARD_TARGET_BROWSER_PATH", "/products")
    monkeypatch.setenv("SHOPGUARD_TARGET_EXPECTED_TITLE", "shop online")
    monkeypatch.setenv("SHOPGUARD_TARGET_EXPECTED_H1", "products")
    monkeypatch.setenv("SHOPGUARD_TARGET_REQUIRED_TEXT", "free delivery")
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)
    monkeypatch.setattr(target_checks, "expect", lambda locator: DummyExpect())
    page = DummyPage()

    target_checks.test_registered_project_storefront(page, target_checks._configured_browser_checks()[0])
    assert page.opened_url == "https://shop.example.test/products"


@pytest.mark.unit
def test_api_check_rejects_wrong_expected_content_type(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "text/plain"}

        @staticmethod
        def iter_content(chunk_size=8192):
            yield b"ok"

        @staticmethod
        def close():
            return None

    monkeypatch.setenv("SHOPGUARD_TARGET_API_URL", "https://api.example.test")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_PATH", "/health")
    monkeypatch.setenv("SHOPGUARD_TARGET_EXPECTED_STATUS", "200")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_EXPECTED_CONTENT_TYPE", "application/json")
    monkeypatch.setenv("SHOPGUARD_TARGET_API_JSON_ASSERTIONS", "[]")
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)
    monkeypatch.setattr(target_checks.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(AssertionError, match="Expected Content-Type to contain 'application/json'"):
        target_checks.test_registered_project_api_endpoint(target_checks._configured_api_checks()[0])


@pytest.mark.unit
def test_configured_browser_and_api_checks_load_multiple_items(monkeypatch):
    monkeypatch.setenv("SHOPGUARD_TARGET_BROWSER_CHECKS", '[{"id":"home","name":"Home","path":"/"},{"id":"catalog","name":"Catalog","path":"/products"}]')
    monkeypatch.setenv("SHOPGUARD_TARGET_API_CHECKS", '[{"id":"health","name":"Health","path":"/health","expected_status":200,"json_assertions":[]},{"id":"products","name":"Products","path":"/products","expected_status":200,"json_assertions":[]}]')
    browser = target_checks._configured_browser_checks()
    api = target_checks._configured_api_checks()
    assert [item["id"] for item in browser] == ["home", "catalog"]
    assert [item["path"] for item in api] == ["/health", "/products"]


@pytest.mark.unit
def test_browser_failure_writes_json_evidence_and_screenshot(monkeypatch, tmp_path):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    class DummyLocator:
        def __init__(self, selector): self.selector = selector
        def inner_text(self, timeout=5000): return "Welcome"
        def count(self): return 1
        def all_inner_texts(self): return ["Welcome"]

    class DummyExpect:
        @staticmethod
        def to_be_visible(): return None

    class DummyContext:
        def route(self, pattern, callback): self.callback = callback

    class DummyPage:
        context = DummyContext()
        url = "https://shop.example.test/"
        def goto(self, url, **kwargs): return SimpleNamespace(status=200)
        def wait_for_timeout(self, milliseconds): return None
        def locator(self, selector): return DummyLocator(selector)
        def title(self): return "Actual title"
        def screenshot(self, path, **kwargs): Path(path).write_bytes(b"PNG test evidence")

    monkeypatch.chdir(tmp_path)
    prefix = tmp_path / "reports" / "target_run-test"
    monkeypatch.setenv("SHOPGUARD_TARGET_ARTIFACT_PREFIX", str(prefix))
    monkeypatch.setenv("SHOPGUARD_TARGET_URL", "https://shop.example.test")
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)
    monkeypatch.setattr(target_checks, "expect", lambda locator: DummyExpect())

    with pytest.raises(AssertionError, match="expected text"):
        target_checks.test_registered_project_storefront(DummyPage(), {
            "id": "home", "name": "Homepage", "path": "/", "expected_title": "Expected title",
        })
    evidence = json.loads((tmp_path / "reports" / "target_run-test-browser-home.json").read_text(encoding="utf-8"))
    assert evidence["details"]["actual"]["title"] == "Actual title"
    assert "Expected title" in evidence["details"]["error"]
    assert (tmp_path / "reports" / "target_run-test-browser-home.png").read_bytes() == b"PNG test evidence"


@pytest.mark.unit
def test_api_failure_writes_expected_and_actual_evidence(monkeypatch, tmp_path):
    import json

    class FakeResponse:
        status_code = 503
        headers = {"Content-Type": "text/plain"}
        def iter_content(self, chunk_size=8192): yield b"service unavailable"
        def close(self): return None

    monkeypatch.chdir(tmp_path)
    prefix = tmp_path / "reports" / "target_api-fail"
    monkeypatch.setenv("SHOPGUARD_TARGET_ARTIFACT_PREFIX", str(prefix))
    monkeypatch.setenv("SHOPGUARD_TARGET_API_URL", "https://api.example.test")
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)
    monkeypatch.setattr(target_checks.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(AssertionError, match="expected HTTP 200, received 503"):
        target_checks.test_registered_project_api_endpoint({
            "id": "health", "name": "Health", "path": "/health", "expected_status": 200,
        })
    evidence = json.loads((tmp_path / "reports" / "target_api-fail-api-health.json").read_text(encoding="utf-8"))
    assert evidence["details"]["expected"]["http_status"] == 200
    assert evidence["details"]["actual"]["http_status"] == 503


@pytest.mark.unit
def test_empty_api_check_list_is_valid_for_browser_only_target(monkeypatch):
    monkeypatch.setenv("SHOPGUARD_TARGET_API_CHECKS", "[]")
    assert target_checks._configured_api_checks() == []


@pytest.mark.unit
def test_pytest_generation_creates_one_case_per_configured_check(monkeypatch):
    class FakeMetafunc:
        fixturenames = ["browser_check"]

        def __init__(self):
            self.calls = []

        def parametrize(self, name, values, ids=None):
            self.calls.append((name, values, ids))

    monkeypatch.setenv("SHOPGUARD_TARGET_BROWSER_CHECKS", '[{"id":"home","name":"Home"},{"id":"catalog","name":"Catalog"}]')
    metafunc = FakeMetafunc()
    target_checks.pytest_generate_tests(metafunc)
    assert len(metafunc.calls) == 1
    assert metafunc.calls[0][0] == "browser_check"
    assert [value["id"] for value in metafunc.calls[0][1]] == ["home", "catalog"]


@pytest.mark.unit
def test_api_missing_json_field_writes_failure_evidence(monkeypatch, tmp_path):
    import json

    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "application/json"}

        @staticmethod
        def iter_content(chunk_size=8192):
            yield b'{"status":"ok"}'

        @staticmethod
        def close():
            return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHOPGUARD_TARGET_API_URL", "https://api.example.test")
    monkeypatch.setenv("SHOPGUARD_TARGET_ARTIFACT_PREFIX", str(tmp_path / "reports" / "target_api-missing"))
    monkeypatch.setattr(target_checks, "validate_public_url", lambda value: value)
    monkeypatch.setattr(target_checks.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(pytest.fail.Exception, match="missing required field"):
        target_checks.test_registered_project_api_endpoint({
            "id": "health", "name": "Health", "path": "/health", "expected_status": 200,
            "json_assertions": [{"path": "data.active", "expected": True}],
        })
    evidence = json.loads((tmp_path / "reports" / "target_api-missing-api-health.json").read_text(encoding="utf-8"))
    assert evidence["details"]["actual"]["http_status"] == 200
    assert "missing required field" in evidence["details"]["error"]


@pytest.mark.unit
def test_pytest_generation_creates_one_case_per_api_endpoint(monkeypatch):
    class FakeMetafunc:
        fixturenames = ["api_check"]

        def __init__(self):
            self.calls = []

        def parametrize(self, name, values, ids=None):
            self.calls.append((name, values, ids))

    monkeypatch.setenv("SHOPGUARD_TARGET_API_CHECKS", '[{"id":"health","name":"Health"},{"id":"catalog","name":"Catalog"}]')
    metafunc = FakeMetafunc()
    target_checks.pytest_generate_tests(metafunc)
    assert len(metafunc.calls) == 1
    assert metafunc.calls[0][0] == "api_check"
    assert [value["id"] for value in metafunc.calls[0][1]] == ["health", "catalog"]


@pytest.mark.unit
def test_pytest_generation_marks_api_case_skipped_for_browser_only_project(monkeypatch):
    class FakeMetafunc:
        fixturenames = ["api_check"]

        def __init__(self):
            self.calls = []

        def parametrize(self, name, values, ids=None):
            self.calls.append((name, values, ids))

    monkeypatch.setenv("SHOPGUARD_TARGET_API_CHECKS", "[]")
    metafunc = FakeMetafunc()
    target_checks.pytest_generate_tests(metafunc)
    assert len(metafunc.calls) == 1
    assert metafunc.calls[0][0] == "api_check"
    assert len(metafunc.calls[0][1]) == 1
    assert metafunc.calls[0][1][0].values[0] is None
    assert any(getattr(mark, "name", "") == "skip" for mark in metafunc.calls[0][1][0].marks)
