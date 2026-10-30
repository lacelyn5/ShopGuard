"""Offline tests for the local dashboard's fixed test-suite runner."""
from pathlib import Path
import pytest

from dashboard.server import ROOT, SUITES, parse_junit_summary, start_suite


@pytest.mark.unit
def test_dashboard_assets_are_in_project():
    assert (ROOT / "dashboard" / "index.html").is_file()
    assert (ROOT / "dashboard" / "server.py").is_file()
    assert (ROOT / "dashboard" / "url_scanner.py").is_file()
    assert (ROOT / "scripts" / "run_dashboard_windows.bat").is_file()
    dashboard_html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert 'id="scan-form"' in dashboard_html
    assert 'id="project-form"' in dashboard_html
    assert 'id="project-list"' in dashboard_html
    assert "runTargetCheck" in dashboard_html
    assert "fetch('/api/scan'" in dashboard_html
    assert "ShopGuard QA Automation" in dashboard_html
    assert "Maksim Kernazhytski" in dashboard_html
    assert "findingLabels" in dashboard_html
    assert "Why it matters:" in dashboard_html
    assert "Next step:" in dashboard_html
    assert "scan-coverage" in dashboard_html
    assert "Review warnings" in dashboard_html
    assert "project-history" in dashboard_html
    assert "api-checks-editor" in dashboard_html
    assert "add-api-check" in dashboard_html
    assert "browser-checks-editor" in dashboard_html
    assert "add-browser-check" in dashboard_html
    assert "backup-create" in dashboard_html
    assert "backup-restore" in dashboard_html
    assert "analytics-list" in dashboard_html
    assert "Browser checks and assertions" in dashboard_html
    assert "Run history" in dashboard_html
    assert "Add project" in dashboard_html
    assert "Update project" in dashboard_html
    assert "scan-groups" in dashboard_html
    assert ".sidebar { position: sticky" in dashboard_html


@pytest.mark.unit
def test_runner_exposes_only_fixed_suite_ids():
    assert set(SUITES) == {"unit", "api_smoke", "ui_smoke", "regression"}
    assert all(isinstance(suite["args"], list) for suite in SUITES.values())
    assert all(";" not in " ".join(suite["args"]) for suite in SUITES.values())


@pytest.mark.unit
def test_live_suite_metadata_is_explicit():
    assert SUITES["unit"]["live"] is False
    assert SUITES["api_smoke"]["live"] is True
    assert SUITES["ui_smoke"]["live"] is True
    assert SUITES["regression"]["live"] is True


@pytest.mark.unit
def test_runner_rejects_unknown_suite_without_running_process():
    ok, message = start_suite("python -c import os")
    assert ok is False
    assert "Unknown test group" in message


@pytest.mark.unit
def test_parse_junit_summary_for_single_suite(tmp_path: Path):
    report = tmp_path / "results.xml"
    report.write_text(
        '<testsuite tests="5" failures="1" errors="1" skipped="1" time="2.5"></testsuite>',
        encoding="utf-8",
    )
    assert parse_junit_summary(report) == {
        "tests": 5, "failures": 1, "errors": 1, "skipped": 1, "passed": 2, "duration": 2.5
    }


@pytest.mark.unit
def test_parse_junit_summary_for_multiple_suites(tmp_path: Path):
    report = tmp_path / "results.xml"
    report.write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0" time="0.4"/>'
        '<testsuite tests="3" failures="1" errors="0" skipped="1" time="0.6"/></testsuites>',
        encoding="utf-8",
    )
    assert parse_junit_summary(report) == {
        "tests": 5, "failures": 1, "errors": 0, "skipped": 1, "passed": 3, "duration": 1.0
    }


@pytest.mark.unit
def test_parse_junit_summary_returns_none_for_missing_or_invalid_report(tmp_path: Path):
    assert parse_junit_summary(tmp_path / "missing.xml") is None
    report = tmp_path / "bad.xml"
    report.write_text("not xml", encoding="utf-8")
    assert parse_junit_summary(report) is None

@pytest.mark.unit
def test_url_scan_rejects_private_target_before_starting():
    from dashboard.server import start_url_scan

    ok, message = start_url_scan("http://127.0.0.1/")
    assert ok is False
    assert "blocked" in message.lower()


@pytest.mark.unit
def test_project_api_path_rejects_absolute_and_traversal_paths():
    from dashboard.server import _validate_api_path

    assert _validate_api_path("/products?page=1") == "/products?page=1"
    for value in ("https://example.com/products", "//example.com", "/../admin", "/safe/..\\admin", ""):
        with pytest.raises(ValueError):
            _validate_api_path(value)


@pytest.mark.unit
def test_project_payload_requires_storefront_and_valid_api_status(monkeypatch):
    from dashboard import url_scanner
    from dashboard.server import validate_project_payload

    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))
    with pytest.raises(ValueError, match="Storefront URL is required"):
        validate_project_payload({"name": "Missing storefront", "store_url": ""})
    with pytest.raises(ValueError, match="between 100 and 599"):
        validate_project_payload({
            "name": "Bad status", "store_url": "https://shop.example.test",
            "api_url": "https://api.example.test", "api_path": "/health", "expected_status": 99,
        })


@pytest.mark.unit
def test_registered_target_runner_uses_fixed_pytest_case_and_env(tmp_path, monkeypatch):
    import json
    import subprocess
    from types import SimpleNamespace

    from dashboard import server

    reports = tmp_path / "reports"
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    server._save_projects([{
        "id": "sample-1", "name": "Sample Store",
        "store_url": "https://shop.example.test", "api_url": "https://api.example.test",
        "api_path": "/health", "expected_status": 204, "built_in": False,
        "browser_path": "/products", "expected_title": "Shop", "expected_h1": "Products",
        "required_text": "In stock", "api_expected_content_type": "application/json",
        "api_json_assertions": [{"path": "status", "expected": "ok"}],
    }])
    started = server._now()
    monkeypatch.setattr(server, "CURRENT_RUN", {
        "run_id": "target-api-sample-1-123", "suite_id": "target_api",
        "name": "API check · Sample Store", "status": "running", "started_at": started,
        "log_path": "reports/target-api-sample-1-123.log",
    })
    monkeypatch.setattr(server, "LAST_RUN", None)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        Path(command[-1]).write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0" time="0.2"/>',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    server._run_target_check({
        "id": "sample-1", "name": "Sample Store", "store_url": "https://shop.example.test",
        "api_url": "https://api.example.test", "api_path": "/health", "expected_status": 204,
        "browser_path": "/products", "expected_title": "Shop", "expected_h1": "Products",
        "required_text": "In stock", "api_expected_content_type": "application/json",
        "api_json_assertions": [{"path": "status", "expected": "ok"}],
    }, "api", "target-api-sample-1-123")

    command = captured["command"]
    env = captured["kwargs"]["env"]
    assert "tests/targets/test_registered_project.py" in command
    assert env["SHOPGUARD_TARGET_URL"] == "https://shop.example.test"
    assert env["SHOPGUARD_TARGET_API_URL"] == "https://api.example.test"
    assert env["SHOPGUARD_TARGET_API_PATH"] == "/health"
    assert env["SHOPGUARD_TARGET_EXPECTED_STATUS"] == "204"
    assert env["SHOPGUARD_TARGET_API_JSON_ASSERTIONS"] == '[{"path": "status", "expected": "ok"}]'
    assert json.loads(env["SHOPGUARD_TARGET_API_CHECKS"])[0]["path"] == "/health"
    assert json.loads(env["SHOPGUARD_TARGET_BROWSER_CHECKS"])[0]["path"] == "/products"
    assert env["SHOPGUARD_TARGET_ARTIFACT_PREFIX"].endswith("target_target-api-sample-1-123")
    assert env["SHOPGUARD_TARGET_BROWSER_PATH"] == "/products"
    assert env["SHOPGUARD_TARGET_EXPECTED_TITLE"] == "Shop"
    assert env["SHOPGUARD_TARGET_EXPECTED_H1"] == "Products"
    assert env["SHOPGUARD_TARGET_REQUIRED_TEXT"] == "In stock"
    assert env["SHOPGUARD_TARGET_API_EXPECTED_CONTENT_TYPE"] == "application/json"
    assert captured["kwargs"]["shell"] is False
    assert server.LAST_RUN["status"] == "passed"
    assert server.LAST_RUN["summary"]["passed"] == 1
    assert server.CURRENT_RUN is None


@pytest.mark.unit
def test_project_validator_saves_browser_and_api_assertions(monkeypatch):
    from dashboard import url_scanner
    from dashboard.server import validate_project_payload

    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))
    project = validate_project_payload({
        "name": "Configured Shop",
        "store_url": "https://shop.example.test",
        "browser_path": "/products",
        "expected_title": "Shop",
        "expected_h1": "Products",
        "required_text": "In stock",
        "api_url": "https://api.example.test",
        "api_path": "/health",
        "expected_status": 200,
        "api_expected_content_type": "application/json",
        "api_json_assertions": [
            {"path": "status", "expected": "ok"},
            {"path": "data.active", "expected": True},
        ],
    })
    assert project["browser_path"] == "/products"
    assert project["expected_title"] == "Shop"
    assert project["api_expected_content_type"] == "application/json"
    assert project["api_json_assertions"][1] == {"path": "data.active", "expected": True}


@pytest.mark.unit
def test_project_validator_rejects_unsafe_browser_path_and_bad_json_assertion(monkeypatch):
    from dashboard import url_scanner
    from dashboard.server import validate_project_payload

    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))
    base = {"name": "Safe Shop", "store_url": "https://shop.example.test"}
    with pytest.raises(ValueError, match="Browser path"):
        validate_project_payload({**base, "browser_path": "//another-host.example/"})
    with pytest.raises(ValueError, match="dotted object keys"):
        validate_project_payload({
            **base,
            "api_url": "https://api.example.test",
            "api_path": "/health",
            "api_json_assertions": [{"path": "data..status", "expected": "ok"}],
        })
    with pytest.raises(ValueError, match="no more than 20"):
        validate_project_payload({
            **base,
            "api_url": "https://api.example.test",
            "api_path": "/health",
            "api_json_assertions": [{"path": f"field{i}", "expected": i} for i in range(21)],
        })


@pytest.mark.unit
def test_run_history_keeps_records_per_target_and_limits_history(tmp_path, monkeypatch):
    from dashboard import server

    reports = tmp_path / "reports"
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    for index in range(205):
        server._record_run_history({
            "run_id": f"target-api-shop-{index}",
            "target_id": "shop",
            "target_name": "Shop",
            "check_type": "api",
            "status": "passed",
            "started_at": f"2026-10-30T10:{index:03d}:00+01:00",
            "log_path": f"reports/target-api-shop-{index}.log",
        })
    history = server.load_run_history()
    assert len(history) == 205
    assert history[0]["run_id"] == "target-api-shop-204"
    assert len(server._project_history_payload()["shop"]) == 205


@pytest.mark.unit
def test_run_history_retains_newest_1000_records_overall(tmp_path, monkeypatch):
    import json
    from dashboard import server

    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    existing = [
        {
            "run_id": f"run-{index}",
            "target_id": "shop",
            "started_at": f"2026-10-30T10:{index:04d}:00+01:00",
        }
        for index in range(server.MAX_RUN_HISTORY)
    ]
    (reports / "run_history.json").write_text(json.dumps({"runs": existing}), encoding="utf-8")

    server._record_run_history({
        "run_id": "run-newest",
        "target_id": "shop",
        "started_at": "2026-10-30T12:00:00+01:00",
    })

    history = server.load_run_history()
    assert len(history) == server.MAX_RUN_HISTORY
    assert history[0]["run_id"] == "run-newest"
    assert "run-0" not in {item["run_id"] for item in history}


@pytest.mark.unit
def test_run_artifact_only_serves_recorded_files_inside_reports(tmp_path, monkeypatch):
    from dashboard import server

    root = tmp_path
    reports = root / "reports"
    reports.mkdir()
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    log = reports / "run-1.log"
    log.write_text("safe log", encoding="utf-8")
    outside = root / "secret.log"
    outside.write_text("private", encoding="utf-8")
    server._record_run_history({
        "run_id": "run-1", "target_id": "shop", "log_path": "reports/run-1.log",
    })
    server._record_run_history({
        "run_id": "run-2", "target_id": "shop", "log_path": "secret.log",
    })
    artifact = server._run_artifact("run-1", "log")
    assert artifact is not None and artifact[0] == b"safe log"
    assert server._run_artifact("run-2", "log") is None
    assert server._run_artifact("run-1", "report") is None


@pytest.mark.unit
def test_load_projects_migrates_profiles_from_older_schema(tmp_path, monkeypatch):
    import json
    from dashboard import server

    reports = tmp_path / "reports"
    projects_file = reports / "test_projects.json"
    reports.mkdir()
    projects_file.write_text(json.dumps({"projects": [{
        "id": "legacy-shop", "name": "Legacy Shop",
        "store_url": "https://shop.example.test", "api_url": "",
        "api_path": "", "expected_status": 200, "built_in": False,
    }]}), encoding="utf-8")
    monkeypatch.setattr(server, "PROJECTS_FILE", projects_file)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)

    project = server.load_projects()[0]
    assert project["browser_path"] == ""
    assert project["expected_title"] == ""
    assert project["api_expected_content_type"] == ""
    assert project["api_json_assertions"] == []


@pytest.mark.unit
def test_project_validator_supports_multiple_browser_and_api_checks(monkeypatch):
    from dashboard import url_scanner
    from dashboard.server import validate_project_payload

    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))
    project = validate_project_payload({
        "name": "Multi-check Shop",
        "store_url": "https://shop.example.test",
        "api_url": "https://api.example.test",
        "browser_checks": [
            {"id": "home", "name": "Homepage", "path": "/", "expected_title": "Shop"},
            {"id": "products", "name": "Products", "path": "/products", "expected_h1": "Products"},
        ],
        "api_checks": [
            {"id": "health", "name": "Health", "path": "/health", "expected_status": 200},
            {"id": "catalog", "name": "Catalog", "path": "/products", "expected_status": 200,
             "expected_content_type": "application/json", "json_assertions": [{"path": "data[0].id", "expected": 1}]},
        ],
    })
    assert [item["id"] for item in project["browser_checks"]] == ["home", "products"]
    assert project["browser_checks"][1]["path"] == "/products"
    assert [item["id"] for item in project["api_checks"]] == ["health", "catalog"]
    assert project["api_checks"][1]["json_assertions"] == [{"path": "data[0].id", "expected": 1}]
    # Legacy top-level keys mirror the first check for compatibility.
    assert project["browser_path"] == "/"
    assert project["api_path"] == "/health"


@pytest.mark.unit
def test_project_validator_rejects_duplicate_check_ids_and_too_many_checks(monkeypatch):
    from dashboard import url_scanner
    from dashboard.server import validate_project_payload

    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))
    base = {"name": "Invalid checks", "store_url": "https://shop.example.test"}
    with pytest.raises(ValueError, match="unique ID"):
        validate_project_payload({**base, "browser_checks": [
            {"id": "same", "name": "One"}, {"id": "same", "name": "Two"},
        ]})
    with pytest.raises(ValueError, match="between 1 and 20"):
        validate_project_payload({**base, "browser_checks": [
            {"id": f"b-{index}", "name": f"Check {index}"} for index in range(21)
        ]})


@pytest.mark.unit
def test_project_analytics_compares_recent_run_duration_and_success_rate(tmp_path, monkeypatch):
    import json
    from dashboard import server

    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    (reports / "run_history.json").write_text(json.dumps({"runs": [
        {"run_id": "run-3", "target_id": "shop", "status": "failed", "duration": 5.0, "started_at": "2026-10-30T12:03:00+01:00", "check_type": "ui"},
        {"run_id": "run-2", "target_id": "shop", "status": "passed", "duration": 4.0, "started_at": "2026-10-30T12:02:00+01:00", "check_type": "all"},
        {"run_id": "run-1", "target_id": "shop", "status": "passed", "duration": 3.0, "started_at": "2026-10-30T12:01:00+01:00", "check_type": "api"},
    ]}), encoding="utf-8")

    result = server._project_analytics_payload()["shop"]
    assert result["total_runs"] == 3
    assert result["completed_runs"] == 3
    assert result["passed"] == 2
    assert result["failed"] == 1
    assert result["success_rate"] == 66.7
    assert result["average_duration"] == 4.0
    assert result["duration_delta"] == 1.0
    assert [item["run_id"] for item in result["trend"]] == ["run-1", "run-2", "run-3"]


@pytest.mark.unit
def test_parse_junit_failures_extracts_failure_and_error_details(tmp_path):
    from dashboard.server import parse_junit_failures

    report = tmp_path / "failure.xml"
    report.write_text(
        '<testsuite tests="2"><testcase classname="target" name="title"><failure message="expected title">Expected X but got Y</failure></testcase>'
        '<testcase classname="target" name="api"><error message="connection refused">Trace line</error></testcase></testsuite>',
        encoding="utf-8",
    )
    values = parse_junit_failures(report)
    assert len(values) == 2
    assert values[0]["message"] == "expected title"
    assert "Expected X" in values[0]["details"]
    assert values[1]["message"] == "connection refused"


@pytest.mark.unit
def test_target_runner_all_dispatches_browser_and_api_checks(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from dashboard import server

    reports = tmp_path / "reports"
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    project = {
        "id": "multi-shop", "name": "Multi Shop", "store_url": "https://shop.example.test",
        "api_url": "https://api.example.test", "api_path": "/health", "expected_status": 200,
        "browser_checks": [
            {"id": "home", "name": "Homepage", "path": "/"},
            {"id": "catalog", "name": "Catalog", "path": "/products"},
        ],
        "api_checks": [
            {"id": "health", "name": "Health", "path": "/health", "expected_status": 200, "json_assertions": []},
            {"id": "catalog-api", "name": "Catalog API", "path": "/products", "expected_status": 200, "json_assertions": []},
        ],
    }
    started = server._now()
    monkeypatch.setattr(server, "CURRENT_RUN", {
        "run_id": "target-all-multi-shop-123", "suite_id": "target_all", "status": "running",
        "started_at": started, "log_path": "reports/target_all-multi-shop-123.log",
    })
    monkeypatch.setattr(server, "LAST_RUN", None)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        Path(command[-1]).write_text('<testsuite tests="4" failures="0" errors="0" skipped="0" time="0.8"/>', encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    server._run_target_check(project, "all", "target-all-multi-shop-123")
    assert "target_ui or target_api" in captured["command"]
    assert len(json.loads(captured["env"]["SHOPGUARD_TARGET_BROWSER_CHECKS"])) == 2
    assert len(json.loads(captured["env"]["SHOPGUARD_TARGET_API_CHECKS"])) == 2
    assert server.LAST_RUN["check_count"] == 4
    assert server.LAST_RUN["summary"]["passed"] == 4
    assert server.LAST_RUN["status"] == "passed"


@pytest.mark.unit
def test_backup_round_trip_restores_projects_history_and_referenced_artifacts(tmp_path, monkeypatch):
    import json
    from dashboard import server, url_scanner

    root = tmp_path / "app"
    reports = root / "reports"
    reports.mkdir(parents=True)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(server, "BACKUPS_DIR", reports / "backups")
    real_validate_public_url = url_scanner.validate_public_url
    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))

    project = server.validate_project_payload({
        "name": "Backup Shop", "store_url": "https://shop.example.com",
        "api_url": "https://api.example.com",
        "browser_checks": [{"id": "home", "name": "Home", "path": "/"}, {"id": "catalog", "name": "Catalog", "path": "/products"}],
        "api_checks": [{"id": "health", "name": "Health", "path": "/health", "expected_status": 200}],
    })
    server._save_projects([project])
    log_path = reports / "run.log"
    xml_path = reports / "run.xml"
    evidence_path = reports / "run-evidence.json"
    screenshot_path = reports / "run.png"
    log_path.write_text("original log", encoding="utf-8")
    xml_path.write_text('<testsuite tests="1"/>', encoding="utf-8")
    evidence_path.write_text('{"error":"expected"}', encoding="utf-8")
    screenshot_path.write_bytes(b"PNG original")
    server._record_run_history({
        "run_id": "backup-run-1", "target_id": project["id"], "target_name": project["name"],
        "check_type": "ui", "status": "failed", "started_at": "2026-10-30T12:00:00+01:00",
        "duration": 1.2, "log_path": "reports/run.log", "report_path": "reports/run.xml",
        "evidence_paths": ["reports/run-evidence.json"], "screenshot_paths": ["reports/run.png"],
    })
    backup = server._build_backup_bytes("test round-trip")

    server._save_projects([{**project, "name": "Changed Shop"}])
    log_path.unlink()
    # Restore must not depend on DNS; a later live run revalidates DNS before connecting.
    monkeypatch.setattr(url_scanner, "validate_public_url", real_validate_public_url)
    monkeypatch.setattr(url_scanner.socket, "getaddrinfo", lambda *args, **kwargs: pytest.fail("restore must not resolve DNS"))
    result = server._restore_backup_bytes(backup)

    assert result == {"projects_restored": 1, "runs_restored": 1, "artifacts_restored": 4, "omitted_artifacts_in_backup": 0}
    restored_project = server.load_projects()[0]
    assert restored_project["name"] == "Backup Shop"
    assert len(restored_project["browser_checks"]) == 2
    assert len(restored_project["api_checks"]) == 1
    restored_run = server.load_run_history()[0]
    assert restored_run["run_id"] == "backup-run-1"
    assert (reports / "run.log").read_text(encoding="utf-8") == "original log"
    assert (reports / "run.png").read_bytes() == b"PNG original"
    assert len(server.list_backups()) == 1  # pre-restore automatic snapshot


@pytest.mark.unit
def test_backup_restore_rejects_invalid_zip_without_touching_profiles(tmp_path, monkeypatch):
    import json
    from dashboard import server

    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(server, "BACKUPS_DIR", reports / "backups")
    original = '{"projects":[]}'
    (reports / "test_projects.json").write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="valid ShopGuard backup"):
        server._restore_backup_bytes(b"not a ZIP archive")
    assert (reports / "test_projects.json").read_text(encoding="utf-8") == original


@pytest.mark.unit
def test_automatic_backups_keep_only_newest_configured_count(tmp_path, monkeypatch):
    from dashboard import server

    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(server, "BACKUPS_DIR", reports / "backups")
    server._save_projects([server._default_project()])
    for index in range(server.AUTO_BACKUP_COUNT + 2):
        server.create_backup_file(automatic=True, reason=f"test {index}")
    automatic = list((reports / "backups").glob("shopguard_auto_*.zip"))
    assert len(automatic) == server.AUTO_BACKUP_COUNT


@pytest.mark.unit
def test_backup_file_manifest_contains_sha256_and_excludes_environment_files(tmp_path, monkeypatch):
    import io
    import json
    import zipfile
    from dashboard import server

    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    server._save_projects([server._default_project()])
    data = server._build_backup_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "shopguard-backup"
        assert "data/test_projects.json" in manifest["files"]
        assert all(".env" not in name and ".venv" not in name for name in manifest["files"])


@pytest.mark.unit
def test_backup_created_before_first_target_run_contains_restorable_empty_history(tmp_path, monkeypatch):
    import json
    from dashboard import server, url_scanner

    root = tmp_path / "app"
    reports = root / "reports"
    reports.mkdir(parents=True)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(server, "BACKUPS_DIR", reports / "backups")
    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))
    project = server.validate_project_payload({"name": "Fresh Shop", "store_url": "https://shop.example.test"})
    server._save_projects([project])

    backup = server._build_backup_bytes("before first run")
    (reports / "test_projects.json").write_text('{"projects": []}', encoding="utf-8")
    result = server._restore_backup_bytes(backup)

    assert result["projects_restored"] == 1
    assert result["runs_restored"] == 0
    assert server.load_projects()[0]["name"] == "Fresh Shop"
    assert json.loads((reports / "run_history.json").read_text(encoding="utf-8")) == {"runs": []}


@pytest.mark.unit
def test_target_check_timeout_scales_with_configured_checks():
    from dashboard.server import _target_check_timeout

    browser = [{"id": f"b{i}"} for i in range(20)]
    api = [{"id": f"a{i}"} for i in range(20)]
    assert _target_check_timeout("ui", browser[:2], api) == 180
    assert _target_check_timeout("ui", browser, api) == 530
    assert _target_check_timeout("api", browser, api[:3]) == 180
    assert _target_check_timeout("all", browser, api) == 930


@pytest.mark.unit
def test_restore_rejects_invalid_dashboard_state_before_writing_artifacts(tmp_path, monkeypatch):
    from dashboard import server, url_scanner

    root = tmp_path / "app"
    reports = root / "reports"
    reports.mkdir(parents=True)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(server, "BACKUPS_DIR", reports / "backups")
    monkeypatch.setattr(url_scanner, "validate_public_url", lambda value, **kwargs: value.rstrip("/"))

    project = server.validate_project_payload({"name": "State Test", "store_url": "https://shop.example.test"})
    server._save_projects([project])
    server._record_run_history({
        "run_id": "state-test-run", "target_id": project["id"], "status": "failed",
        "started_at": "2026-10-30T12:00:00+01:00", "log_path": "reports/evidence.log",
    })
    (reports / "evidence.log").write_text("evidence body", encoding="utf-8")
    (reports / "dashboard_state.json").write_text("[]", encoding="utf-8")
    backup = server._build_backup_bytes("invalid state document")
    (reports / "evidence.log").unlink()

    with pytest.raises(ValueError, match="dashboard state is invalid"):
        server._restore_backup_bytes(backup)
    assert not (reports / "evidence.log").exists()


@pytest.mark.unit
def test_backup_manifest_reports_artifacts_omitted_by_size_cap(tmp_path, monkeypatch):
    import io
    import json
    import zipfile
    from dashboard import server

    root = tmp_path / "app"
    reports = root / "reports"
    reports.mkdir(parents=True)
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(server, "BACKUPS_DIR", reports / "backups")
    monkeypatch.setattr(server, "MAX_BACKUP_ARTIFACT_BYTES", 4)
    server._save_projects([server._default_project()])
    (reports / "a.log").write_text("12345", encoding="utf-8")
    (reports / "b.log").write_text("12", encoding="utf-8")
    server._record_run_history({
        "run_id": "cap-run", "target_id": server.load_projects()[0]["id"],
        "status": "failed", "started_at": "2026-10-30T12:00:00+01:00",
        "log_path": "reports/a.log", "report_path": "reports/b.log",
    })

    created = server.create_backup_file(reason="artifact cap test")
    assert created["omitted_artifact_count"] == 1
    backup_path = reports / "backups" / created["filename"]
    with zipfile.ZipFile(io.BytesIO(backup_path.read_bytes())) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["omitted_artifact_count"] == 1
        assert "artifacts/reports/b.log" in manifest["files"]
        assert "artifacts/reports/a.log" not in manifest["files"]


@pytest.mark.unit
def test_target_runner_all_uses_only_browser_marker_when_project_has_no_api(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from dashboard import server

    reports = tmp_path / "reports"
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "REPORTS_DIR", reports)
    monkeypatch.setattr(server, "STATE_FILE", reports / "dashboard_state.json")
    monkeypatch.setattr(server, "PROJECTS_FILE", reports / "test_projects.json")
    project = {
        "id": "browser-only", "name": "Browser only", "store_url": "https://shop.example.test",
        "api_url": "", "browser_path": "", "api_path": "", "expected_status": 200,
        "browser_checks": [{"id": "home", "name": "Home", "path": "/"}], "api_checks": [],
    }
    monkeypatch.setattr(server, "CURRENT_RUN", {
        "run_id": "target-all-browser-only-123", "suite_id": "target_all", "status": "running",
        "started_at": server._now(), "log_path": "reports/target_all-browser-only-123.log",
    })
    monkeypatch.setattr(server, "LAST_RUN", None)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        Path(command[-1]).write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" time="0.2"/>', encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    server._run_target_check(project, "all", "target-all-browser-only-123")
    assert "target_ui" in captured["command"]
    assert "target_ui or target_api" not in captured["command"]
    assert json.loads(captured["env"]["SHOPGUARD_TARGET_API_CHECKS"]) == []
    assert server.LAST_RUN["check_count"] == 1
    assert server.LAST_RUN["status"] == "passed"
