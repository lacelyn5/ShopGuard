"""HTTP-level tests for the local dashboard API using an ephemeral loopback server."""
from __future__ import annotations

import json
import subprocess
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

from dashboard import server as dashboard


def _request(base_url, path, *, method="GET", payload=None, headers=None):
    data = None if payload is None else (
        payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    )
    request_headers = dict(headers or {})
    if data is not None and "Content-Type" not in request_headers:
        request_headers["Content-Type"] = "application/json"
    request = Request(base_url + path, data=data, headers=request_headers, method=method)
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as exc:
        response = exc
    except URLError as exc:
        pytest.fail(f"Dashboard request failed unexpectedly: {exc}")
    with response as result:
        body = result.read()
        content_type = result.headers.get("Content-Type", "")
        parsed = json.loads(body.decode("utf-8")) if "json" in content_type else body.decode("utf-8", errors="replace")
        return result.status, result.headers, parsed


@pytest.fixture

def dashboard_server(monkeypatch, tmp_path):
    """Start an isolated local HTTP server and restore process-wide dashboard state."""
    names = ("CURRENT_RUN", "LAST_RUN", "CURRENT_SCAN", "LAST_SCAN")
    previous = {name: getattr(dashboard, name) for name in names}
    reports = tmp_path / "reports"
    monkeypatch.setattr(dashboard, "REPORTS_DIR", reports)
    monkeypatch.setattr(dashboard, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(dashboard, "PROJECTS_FILE", reports / "test_projects.json")
    monkeypatch.setattr(dashboard, "BACKUPS_DIR", reports / "backups")
    for name in names:
        setattr(dashboard, name, None)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        yield base_url
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        for name, value in previous.items():
            setattr(dashboard, name, value)


@pytest.mark.unit
def test_health_and_dashboard_return_security_headers(dashboard_server):
    status, headers, body = _request(dashboard_server, "/health")
    assert status == 200
    assert body == {"ok": True, "service": "ShopGuard dashboard"}
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store"

    page_status, page_headers, html = _request(dashboard_server, "/")
    assert page_status == 200
    assert "ShopGuard QA Automation" in html
    assert "text/html" in page_headers["Content-Type"]


@pytest.mark.unit
def test_status_endpoint_exposes_fixed_test_groups_only(dashboard_server):
    status, _, body = _request(dashboard_server, "/api/status")
    assert status == 200
    assert {suite["id"] for suite in body["suites"]} == {"unit", "api_smoke", "ui_smoke", "regression"}
    assert all(isinstance(suite["command"], str) and "pytest" in suite["command"] for suite in body["suites"])
    assert all("python -c" not in suite["command"] for suite in body["suites"])
    assert body["running"] is False
    assert body["scan_running"] is False


@pytest.mark.unit
def test_unknown_get_route_returns_json_404(dashboard_server):
    status, _, body = _request(dashboard_server, "/not-a-route")
    assert status == 404
    assert body == {"error": "Not found"}


@pytest.mark.unit
def test_post_requires_json_content_type(dashboard_server):
    status, _, body = _request(
        dashboard_server, "/api/run", method="POST", payload=b'{"suite":"unit"}',
        headers={"Content-Type": "text/plain"},
    )
    assert status == 415
    assert "application/json" in body["error"]


@pytest.mark.unit
def test_post_rejects_oversized_body(dashboard_server):
    status, _, body = _request(
        dashboard_server, "/api/run", method="POST", payload=b" " * 8193,
        headers={"Content-Type": "application/json"},
    )
    assert status == 400
    assert body == {"error": "Invalid request size."}


@pytest.mark.unit
def test_post_rejects_wrong_field_types(dashboard_server):
    status, _, body = _request(dashboard_server, "/api/run", method="POST", payload={"suite": ["unit"]})
    assert status == 400
    assert body == {"error": "Choose a test group."}

    status, _, body = _request(dashboard_server, "/api/scan", method="POST", payload={"url": 123})
    assert status == 400
    assert body == {"error": "Enter a website address."}


@pytest.mark.unit
def test_post_rejects_invalid_json_and_non_object_payloads(dashboard_server):
    status, _, body = _request(
        dashboard_server, "/api/run", method="POST", payload=b'{bad json',
        headers={"Content-Type": "application/json"},
    )
    assert status == 400
    assert body["error"] == "Send valid JSON."

    status, _, body = _request(dashboard_server, "/api/run", method="POST", payload=["unit"])
    assert status == 400
    assert body["error"] == "Send a JSON object."


@pytest.mark.unit
def test_run_route_returns_runner_rejection_for_unknown_suite(dashboard_server, monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, "start_suite", lambda suite_id: (calls.append(suite_id) or False, "Unknown test group."))
    status, _, body = _request(dashboard_server, "/api/run", method="POST", payload={"suite": "python -c print(1)"})
    assert status == 400
    assert body == {"error": "Unknown test group."}
    assert calls == ["python -c print(1)"]


@pytest.mark.unit
def test_run_route_accepts_only_allowlisted_suite_id(dashboard_server, monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, "start_suite", lambda suite_id: (calls.append(suite_id) or True, "unit-test-run"))
    status, _, body = _request(dashboard_server, "/api/run", method="POST", payload={"suite": "unit"})
    assert status == 202
    assert body == {"accepted": True, "run_id": "unit-test-run"}
    assert calls == ["unit"]


@pytest.mark.unit
def test_run_route_maps_busy_state_to_http_409(dashboard_server, monkeypatch):
    monkeypatch.setattr(dashboard, "start_suite", lambda suite_id: (False, "A test or website check is already running. Wait for it to finish."))
    status, _, body = _request(dashboard_server, "/api/run", method="POST", payload={"suite": "unit"})
    assert status == 409
    assert "already running" in body["error"]


@pytest.mark.unit
def test_scan_route_rejects_loopback_before_starting_scan(dashboard_server):
    status, _, body = _request(dashboard_server, "/api/scan", method="POST", payload={"url": "http://127.0.0.1/"})
    assert status == 400
    assert "blocked" in body["error"].lower()


@pytest.mark.unit
def test_scan_route_returns_202_for_validated_target(dashboard_server, monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, "start_url_scan", lambda url: (calls.append(url) or True, "scan-test-id"))
    status, _, body = _request(dashboard_server, "/api/scan", method="POST", payload={"url": "https://example.com/"})
    assert status == 202
    assert body == {"accepted": True, "scan_id": "scan-test-id"}
    assert calls == ["https://example.com/"]


@pytest.mark.unit
def test_post_rejects_foreign_origin_and_host(dashboard_server, monkeypatch):
    monkeypatch.setattr(dashboard, "start_suite", lambda suite_id: pytest.fail("untrusted request must not run a suite"))
    status, _, body = _request(
        dashboard_server, "/api/run", method="POST", payload={"suite": "unit"},
        headers={"Origin": "http://evil.example"},
    )
    assert status == 403
    assert "local dashboard" in body["error"].lower()

    status, _, body = _request(
        dashboard_server, "/api/run", method="POST", payload={"suite": "unit"},
        headers={"Host": "evil.example"},
    )
    assert status == 403
    assert "local dashboard" in body["error"].lower()

    status, _, body = _request(
        dashboard_server, "/api/run", method="POST", payload={"suite": "unit"},
        headers={"Host": f"user@127.0.0.1:{dashboard_server.rsplit(':', 1)[1]}"},
    )
    assert status == 403
    assert "local dashboard" in body["error"].lower()

    status, _, body = _request(
        dashboard_server, "/api/run", method="POST", payload={"suite": "unit"},
        headers={"Host": f"127.0.0.1:{dashboard_server.rsplit(':', 1)[1]}/unexpected"},
    )
    assert status == 403
    assert "local dashboard" in body["error"].lower()


@pytest.mark.unit
def test_tail_never_reads_outside_reports_directory(tmp_path, monkeypatch):
    outside = tmp_path / "private.txt"
    outside.write_text("do not expose", encoding="utf-8")
    monkeypatch.setattr(dashboard, "REPORTS_DIR", tmp_path / "reports")
    assert dashboard._tail(str(outside)) == ""


@pytest.mark.unit
def test_timed_out_suite_is_recorded_as_failed_with_diagnostic(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    monkeypatch.setattr(dashboard, "REPORTS_DIR", reports)
    monkeypatch.setattr(dashboard, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(dashboard, "PROJECTS_FILE", reports / "test_projects.json")
    monkeypatch.setattr(dashboard, "BACKUPS_DIR", reports / "backups")
    monkeypatch.setattr(
        dashboard.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(args[0], timeout=1)),
    )
    monkeypatch.setattr(dashboard, "CURRENT_RUN", {
        "run_id": "unit-timeout-test", "suite_id": "unit", "name": "Local checks",
        "status": "running", "started_at": dashboard._now(), "log_path": "reports/dashboard_unit.log",
    })
    monkeypatch.setattr(dashboard, "LAST_RUN", None)
    dashboard._run_suite("unit", "unit-timeout-test")
    result = dashboard.LAST_RUN
    assert result is not None
    assert result["status"] == "failed"
    assert result["return_code"] == 124
    assert "time limit" in result["message"].lower()
    assert "TIMEOUT" in (reports / "dashboard_unit.log").read_text(encoding="utf-8")


@pytest.mark.unit
def test_projects_endpoint_seeds_builtin_example(dashboard_server):
    status, _, body = _request(dashboard_server, "/api/projects")
    assert status == 200
    assert len(body["projects"]) == 1
    assert body["projects"][0]["id"] == "toolshop-demo"
    assert body["projects"][0]["built_in"] is True


@pytest.mark.unit
def test_create_update_and_delete_custom_project(dashboard_server, monkeypatch):
    from dashboard import url_scanner

    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))
    payload = {
        "name": "Della Vita",
        "store_url": "https://shop.example.test/food",
        "api_url": "https://api.example.test",
        "api_path": "/api/health",
        "expected_status": 200,
    }
    status, _, created = _request(dashboard_server, "/api/projects", method="POST", payload=payload)
    assert status == 200
    assert created["saved"] is True
    project = next(item for item in created["projects"] if item["name"] == "Della Vita")
    assert project["api_path"] == "/api/health"
    assert project["built_in"] is False

    updated_payload = {**payload, "id": project["id"], "name": "Della Vita staging"}
    status, _, updated = _request(dashboard_server, "/api/projects", method="POST", payload=updated_payload)
    assert status == 200
    assert next(item for item in updated["projects"] if item["id"] == project["id"])["name"] == "Della Vita staging"

    status, _, deleted = _request(dashboard_server, "/api/projects/delete", method="POST", payload={"id": project["id"]})
    assert status == 200
    assert all(item["id"] != project["id"] for item in deleted["projects"])


@pytest.mark.unit
def test_project_endpoint_rejects_unsafe_api_path(dashboard_server, monkeypatch):
    from dashboard import url_scanner

    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))
    payload = {
        "name": "Unsafe path", "store_url": "https://shop.example.test",
        "api_url": "https://api.example.test", "api_path": "//evil.example/route",
        "expected_status": 200,
    }
    status, _, body = _request(dashboard_server, "/api/projects", method="POST", payload=payload)
    assert status == 400
    assert "relative api path" in body["error"].lower()


@pytest.mark.unit
def test_builtin_project_cannot_be_deleted(dashboard_server):
    status, _, body = _request(
        dashboard_server, "/api/projects/delete", method="POST", payload={"id": "toolshop-demo"}
    )
    assert status == 400
    assert "cannot be deleted" in body["error"].lower()


@pytest.mark.unit
def test_target_run_route_dispatches_selected_saved_project(dashboard_server, monkeypatch):
    calls = []
    monkeypatch.setattr(
        dashboard, "start_target_check",
        lambda target_id, check: (calls.append((target_id, check)) or True, "target-api-custom-1"),
    )
    status, _, body = _request(
        dashboard_server, "/api/target-run", method="POST",
        payload={"id": "custom-shop", "check": "api"},
    )
    assert status == 202
    assert body == {"accepted": True, "run_id": "target-api-custom-1"}
    assert calls == [("custom-shop", "api")]


@pytest.mark.unit
def test_target_run_rejects_unknown_project_and_missing_api(dashboard_server):
    status, _, body = _request(
        dashboard_server, "/api/target-run", method="POST", payload={"id": "missing", "check": "ui"}
    )
    assert status == 400
    assert "not found" in body["error"].lower()

    status, _, body = _request(
        dashboard_server, "/api/target-run", method="POST", payload={"id": "toolshop-demo", "check": "invalid"}
    )
    assert status == 400
    assert "browser" in body["error"].lower() and "api" in body["error"].lower()


@pytest.mark.unit
def test_status_endpoint_exposes_per_project_run_history(dashboard_server, monkeypatch, tmp_path):
    reports = tmp_path / "reports"
    monkeypatch.setattr(dashboard, "REPORTS_DIR", reports)
    dashboard._record_run_history({
        "run_id": "target-api-example-1",
        "target_id": "example",
        "target_name": "Example Shop",
        "check_type": "api",
        "status": "passed",
        "started_at": "2026-10-30T12:00:00+01:00",
        "duration": 0.45,
        "summary": {"tests": 1, "passed": 1, "failures": 0, "errors": 0, "skipped": 0},
        "log_path": "reports/target-api-example-1.log",
        "report_path": "reports/target-api-example-1.xml",
    })

    status, _, body = _request(dashboard_server, "/api/status")
    assert status == 200
    history = body["project_history"]["example"]
    assert len(history) == 1
    assert history[0]["check_type"] == "api"
    assert history[0]["status"] == "passed"
    assert history[0]["report_available"] is True


@pytest.mark.unit
def test_artifact_route_serves_only_a_registered_local_run_file(dashboard_server, monkeypatch, tmp_path):
    root = tmp_path / "project"
    reports = root / "reports"
    reports.mkdir(parents=True)
    monkeypatch.setattr(dashboard, "ROOT", root)
    monkeypatch.setattr(dashboard, "REPORTS_DIR", reports)
    (reports / "target-run.log").write_text("ShopGuard run log", encoding="utf-8")
    (reports / "target-run.xml").write_text('<testsuite tests="1"/>', encoding="utf-8")
    dashboard._record_run_history({
        "run_id": "target-run",
        "target_id": "shop",
        "log_path": "reports/target-run.log",
        "report_path": "reports/target-run.xml",
    })

    status, headers, body = _request(dashboard_server, "/api/artifact?run_id=target-run&kind=log")
    assert status == 200
    assert "text/plain" in headers["Content-Type"]
    assert body == "ShopGuard run log"

    status, headers, body = _request(dashboard_server, "/api/artifact?run_id=target-run&kind=report")
    assert status == 200
    assert "application/xml" in headers["Content-Type"]
    assert '<testsuite tests="1"/>' in body

    status, _, body = _request(dashboard_server, "/api/artifact?run_id=unknown&kind=log")
    assert status == 404
    assert body == {"error": "Run artifact not found."}


@pytest.mark.unit
def test_backup_create_list_download_and_restore_routes(dashboard_server, monkeypatch):
    import zipfile
    from io import BytesIO
    from urllib.request import Request, urlopen
    from dashboard import url_scanner

    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))
    status, _, seeded = _request(dashboard_server, "/api/projects")
    assert status == 200
    assert seeded["projects"][0]["id"] == "toolshop-demo"

    status, _, created = _request(dashboard_server, "/api/backup/create", method="POST", payload={})
    assert status == 200
    backup_name = created["backup"]["filename"]

    status, _, listed = _request(dashboard_server, "/api/backup/list")
    assert status == 200
    assert any(item["filename"] == backup_name for item in listed["backups"])

    request = Request(dashboard_server + "/api/backup/download?name=" + backup_name, method="GET")
    with urlopen(request, timeout=3) as response:
        backup_bytes = response.read()
        assert response.headers.get("Content-Type") == "application/zip"
        assert zipfile.is_zipfile(BytesIO(backup_bytes))

    custom = {
        "name": "Temporary Shop", "store_url": "https://shop.example.test",
        "browser_checks": [{"id": "home", "name": "Home", "path": "/"}],
    }
    status, _, changed = _request(dashboard_server, "/api/projects", method="POST", payload=custom)
    assert status == 200
    assert any(item["name"] == "Temporary Shop" for item in changed["projects"])

    restore = Request(
        dashboard_server + "/api/backup/restore", data=backup_bytes,
        headers={"Content-Type": "application/zip"}, method="POST",
    )
    with urlopen(restore, timeout=3) as response:
        restored = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert restored["restored"] is True
        assert restored["projects_restored"] == 1

    status, _, after_restore = _request(dashboard_server, "/api/projects")
    assert status == 200
    assert [item["id"] for item in after_restore["projects"]] == ["toolshop-demo"]


@pytest.mark.unit
def test_backup_routes_reject_untrusted_origin_and_wrong_restore_content_type(dashboard_server):
    status, _, body = _request(
        dashboard_server, "/api/backup/list", headers={"Host": "evil.example"}
    )
    assert status == 403
    assert "local dashboard" in body["error"].lower()

    status, _, body = _request(
        dashboard_server, "/api/backup/restore", method="POST", payload=b"PK-not-a-zip",
        headers={"Content-Type": "text/plain"},
    )
    assert status == 415
    assert "backup zip" in body["error"].lower()
