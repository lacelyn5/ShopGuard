"""Local ShopGuard dashboard, allow-listed pytest runner and read-only URL scanner.

The server binds to loopback only. It exposes no arbitrary command execution,
accepts only predefined test-suite identifiers, and restricts URL scans to
public HTTP(S) destinations with bounded read-only checks.
"""
from __future__ import annotations

import hashlib
import ipaddress
import io
import json
import math
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DASHBOARD_FILE = ROOT / "dashboard" / "index.html"
REPORTS_DIR = ROOT / "reports"
STATE_FILE = REPORTS_DIR / "dashboard_state.json"
PROJECTS_FILE = REPORTS_DIR / "test_projects.json"
BACKUPS_DIR = REPORTS_DIR / "backups"
HOST = "127.0.0.1"
PORT = 8765
MAX_RUN_HISTORY = 1000
MAX_BACKUP_BYTES = 20 * 1024 * 1024
MAX_BACKUP_ARTIFACT_BYTES = 15 * 1024 * 1024
AUTO_BACKUP_COUNT = 5
BACKUP_FORMAT_VERSION = 1
SUITE_TIMEOUT_SECONDS = {
    "unit": 120,
    "api_smoke": 180,
    "ui_smoke": 240,
    "regression": 360,
}

# This is an intentional allow-list. Never accept a command or pytest selector
# supplied directly by the browser.
SUITES: dict[str, dict[str, object]] = {
    "unit": {
        "name": "Local checks",
        "short": "Fast · no internet",
        "description": "Checks project settings, test rules and Postman files.",
        "args": ["-m", "unit"],
        "live": False,
        "warning": "These checks run on your computer. They do not open the demo shop.",
    },
    "api_smoke": {
        "name": "API checks",
        "short": "Online · read-only",
        "description": "Checks products, categories, brands and pages that should need a sign-in.",
        "args": ["-m", "api and smoke"],
        "live": True,
        "warning": "Uses the public demo API. Results depend on its availability and data.",
    },
    "ui_smoke": {
        "name": "Browser checks",
        "short": "Online · browser",
        "description": "Opens the demo shop and checks the product list, a product page and the login form.",
        "args": ["-m", "ui and smoke"],
        "live": True,
        "warning": "Opens the public demo shop in a browser. It does not place orders.",
    },
    "regression": {
        "name": "Full check (no changes)",
        "short": "Online · API + browser",
        "description": "Runs more API and browser tests. Skips tests that change the cart or use a login.",
        "args": ["-m", "(api or ui) and not stateful and not auth"],
        "live": True,
        "warning": "Runs several checks against the public demo shop and its API. It may take longer.",
    },
}

LOCK = threading.RLock()
PROJECTS_LOCK = threading.RLock()
RUN_HISTORY_LOCK = threading.RLock()
CURRENT_RUN: dict | None = None
LAST_RUN: dict | None = None
CURRENT_SCAN: dict | None = None
LAST_SCAN: dict | None = None



def _default_project() -> dict:
    return {
        "id": "toolshop-demo",
        "name": "Practice Software Testing",
        "store_url": "https://practicesoftwaretesting.com",
        "api_url": "https://api.practicesoftwaretesting.com",
        "api_path": "/products",
        "expected_status": 200,
        "browser_path": "",
        "expected_title": "",
        "expected_h1": "",
        "required_text": "",
        "api_expected_content_type": "",
        "api_json_assertions": [],
        "browser_checks": [{
            "id": "browser-home", "name": "Homepage", "path": "",
            "expected_title": "", "expected_h1": "", "required_text": "",
        }],
        "api_checks": [{
            "id": "api-products", "name": "Products", "path": "/products",
            "expected_status": 200, "expected_content_type": "", "json_assertions": [],
        }],
        "built_in": True,
    }


def _save_projects(projects: list[dict]) -> None:
    with PROJECTS_LOCK:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        temporary = PROJECTS_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps({"projects": projects}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(PROJECTS_FILE)


def load_projects() -> list[dict]:
    """Load local target profiles, creating the Toolshop example on first start."""
    with PROJECTS_LOCK:
        try:
            value = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
            items = value.get("projects", []) if isinstance(value, dict) else []
            if not isinstance(items, list):
                return []
            cleaned = []
            for item in items[:25]:
                if not isinstance(item, dict):
                    continue
                required = ("id", "name", "store_url", "api_url", "api_path", "expected_status")
                if not all(key in item for key in required):
                    continue
                if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", str(item["id"])):
                    continue
                try:
                    saved_assertions = _validate_json_assertions(item.get("api_json_assertions", []))
                except ValueError:
                    saved_assertions = []
                legacy = {
                    "browser_path": str(item.get("browser_path", ""))[:512],
                    "expected_title": str(item.get("expected_title", ""))[:200],
                    "expected_h1": str(item.get("expected_h1", ""))[:200],
                    "required_text": str(item.get("required_text", ""))[:200],
                    "api_path": str(item["api_path"])[:512],
                    "expected_status": int(item["expected_status"]),
                    "api_expected_content_type": str(item.get("api_expected_content_type", ""))[:120],
                    "api_json_assertions": saved_assertions,
                }
                try:
                    browser_checks = _validate_browser_checks(item.get("browser_checks"), legacy)
                    api_checks = _validate_api_checks(item.get("api_checks"), legacy, api_configured=bool(item["api_url"]))
                except ValueError:
                    # A malformed new-format check list must not prevent access to
                    # otherwise valid legacy profile fields.
                    browser_checks = _validate_browser_checks(None, legacy)
                    api_checks = _validate_api_checks(None, legacy, api_configured=bool(item["api_url"]))
                first_browser = browser_checks[0]
                first_api = api_checks[0] if api_checks else None
                cleaned.append({
                    "id": str(item["id"]), "name": str(item["name"])[:80],
                    "store_url": str(item["store_url"])[:2048],
                    "api_url": str(item["api_url"])[:2048] if item["api_url"] else "",
                    "api_path": first_api["path"] if first_api else legacy["api_path"],
                    "expected_status": first_api["expected_status"] if first_api else legacy["expected_status"],
                    "browser_path": first_browser["path"],
                    "expected_title": first_browser["expected_title"],
                    "expected_h1": first_browser["expected_h1"],
                    "required_text": first_browser["required_text"],
                    "api_expected_content_type": first_api["expected_content_type"] if first_api else "",
                    "api_json_assertions": first_api["json_assertions"] if first_api else [],
                    "browser_checks": browser_checks, "api_checks": api_checks,
                    "built_in": bool(item.get("built_in", False)),
                })
            return cleaned
        except FileNotFoundError:
            projects = [_default_project()]
            _save_projects(projects)
            return projects
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return []


def _validate_api_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Enter an API path, for example /products.")
    path = value.strip()
    if len(path) > 512 or any(ord(char) < 32 for char in path):
        raise ValueError("The API path is invalid or too long.")
    parsed = urlsplit(path)
    if (
        not path.startswith("/") or path.startswith("//") or parsed.scheme or parsed.netloc
        or parsed.fragment or "\\" in parsed.path
        or any(part == ".." for part in parsed.path.split("/"))
    ):
        raise ValueError("Use a relative API path beginning with one slash, such as /products.")
    return path


def _validate_relative_path(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a relative path beginning with one slash.")
    path = value.strip()
    if not path:
        return ""
    parsed = urlsplit(path)
    if (
        len(path) > 512 or not path.startswith("/") or path.startswith("//")
        or parsed.scheme or parsed.netloc or parsed.fragment or "\\" in parsed.path
        or any(part == ".." for part in parsed.path.split("/"))
        or any(ord(char) < 32 for char in path)
    ):
        raise ValueError(f"{label} must be a safe relative path such as /products.")
    return path


def _validate_json_field_path(value: object) -> str:
    if not isinstance(value, str) or len(value) > 160 or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_-]*(?:\[(?:0|[1-9]\d*)\])?(?:\.[A-Za-z_][A-Za-z0-9_-]*(?:\[(?:0|[1-9]\d*)\])?)*", value.strip()
    ):
        raise ValueError("JSON assertion paths must use dotted object keys, for example data.status.")
    return value.strip()


def _validate_json_assertions(value: object) -> list[dict]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Add no more than 20 JSON field assertions.")
    cleaned: list[dict] = []
    for item in value:
        if not isinstance(item, dict) or "expected" not in item:
            raise ValueError("Each JSON assertion needs a field path and expected value.")
        field_path = _validate_json_field_path(item.get("path"))
        expected = item.get("expected")
        if isinstance(expected, (dict, list)):
            raise ValueError("JSON assertions support string, number, true, false or null values.")
        if isinstance(expected, str):
            if len(expected) > 200 or any(ord(char) < 32 for char in expected):
                raise ValueError("JSON assertion values must be 200 characters or fewer.")
        elif isinstance(expected, float) and not math.isfinite(expected):
            raise ValueError("JSON assertion numbers must be finite.")
        elif expected is not None and not isinstance(expected, (bool, int, float)):
            raise ValueError("JSON assertions support string, number, true, false or null values.")
        cleaned.append({"path": field_path, "expected": expected})
    return cleaned


def _validate_check_id(value: object, prefix: str, used: set[str]) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        candidate = f"{prefix}-{secrets.token_hex(4)}"
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", candidate):
        raise ValueError("Check IDs may contain letters, numbers, underscores and hyphens only.")
    if candidate in used:
        raise ValueError("Each check in a project must have a unique ID.")
    used.add(candidate)
    return candidate


def _validate_browser_checks(value: object, legacy: dict | None = None) -> list[dict]:
    legacy = legacy or {}
    if value is None:
        value = [{
            "id": "browser-1", "name": "Storefront",
            "path": legacy.get("browser_path", ""),
            "expected_title": legacy.get("expected_title", ""),
            "expected_h1": legacy.get("expected_h1", ""),
            "required_text": legacy.get("required_text", ""),
        }]
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("Add between 1 and 20 browser checks to each project.")
    cleaned: list[dict] = []
    used: set[str] = set()
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise ValueError("Each browser check must be an object.")
        name = item.get("name", f"Browser check {index}")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
            raise ValueError("Browser check names are required and must be 60 characters or fewer.")
        path = _validate_relative_path(item.get("path", item.get("browser_path", "")), "Browser path")
        title = _validate_optional_text(item, "expected_title", "Expected page title")
        h1 = _validate_optional_text(item, "expected_h1", "Expected H1 heading")
        required = _validate_optional_text(item, "required_text", "Required page text")
        cleaned.append({
            "id": _validate_check_id(item.get("id"), "browser", used),
            "name": name.strip(), "path": path,
            "expected_title": title, "expected_h1": h1, "required_text": required,
        })
    return cleaned


def _validate_api_checks(value: object, legacy: dict | None = None, *, api_configured: bool = True) -> list[dict]:
    legacy = legacy or {}
    if not api_configured:
        if value not in (None, [], ""):
            raise ValueError("Add an API base URL before configuring API checks.")
        return []
    if value is None:
        value = [{
            "id": "api-1", "name": "API endpoint",
            "path": legacy.get("api_path", "/"),
            "expected_status": legacy.get("expected_status", 200),
            "expected_content_type": legacy.get("api_expected_content_type", ""),
            "json_assertions": legacy.get("api_json_assertions", []),
        }]
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("Add between 1 and 20 API checks when an API URL is configured.")
    cleaned: list[dict] = []
    used: set[str] = set()
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise ValueError("Each API check must be an object.")
        name = item.get("name", f"API check {index}")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
            raise ValueError("API check names are required and must be 60 characters or fewer.")
        path = _validate_api_path(item.get("path", item.get("api_path", "/")))
        try:
            expected_status = int(item.get("expected_status", legacy.get("expected_status", 200)))
        except (TypeError, ValueError) as exc:
            raise ValueError("Expected HTTP status must be between 100 and 599.") from exc
        if not 100 <= expected_status <= 599:
            raise ValueError("Expected HTTP status must be between 100 and 599.")
        content_type = _validate_optional_text(
            {"expected_content_type": item.get("expected_content_type", item.get("api_expected_content_type", ""))},
            "expected_content_type", "Expected API content type", 120,
        )
        assertions = _validate_json_assertions(item.get("json_assertions", item.get("api_json_assertions", [])))
        cleaned.append({
            "id": _validate_check_id(item.get("id"), "api", used),
            "name": name.strip(), "path": path, "expected_status": expected_status,
            "expected_content_type": content_type, "json_assertions": assertions,
        })
    return cleaned


def _validate_optional_text(payload: dict, field: str, label: str, limit: int = 200) -> str:
    value = payload.get(field, "")
    if value is None:
        value = ""
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValueError(f"{label} must be {limit} characters or fewer.")
    value = value.strip()
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} contains invalid characters.")
    return value


def validate_project_payload(payload: dict, existing: dict | None = None, *, url_validator=None) -> dict:
    """Validate a public, read-only test target. Never accept credentials or commands."""
    from dashboard.url_scanner import validate_public_url
    validate_url = url_validator or validate_public_url

    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ValueError("Project name is required (maximum 80 characters).")
    if any(ord(char) < 32 for char in name):
        raise ValueError("Project name contains invalid characters.")

    store_url = payload.get("store_url")
    if not isinstance(store_url, str) or not store_url.strip():
        raise ValueError("Storefront URL is required.")
    store_url = validate_url(store_url.strip())
    store_parts = urlsplit(store_url)
    if store_parts.query or store_parts.fragment:
        raise ValueError("Storefront URL must not contain a query string or fragment.")

    api_url_raw = payload.get("api_url", "")
    if api_url_raw is None:
        api_url_raw = ""
    if not isinstance(api_url_raw, str):
        raise ValueError("API base URL must be a URL or left empty.")
    api_url = ""
    api_path = ""
    expected_status = 200
    if api_url_raw.strip():
        api_url = validate_url(api_url_raw.strip())
        api_parts = urlsplit(api_url)
        if api_parts.query or api_parts.fragment:
            raise ValueError("API base URL must not contain a query string or fragment.")
        api_path = _validate_api_path(payload.get("api_path", "/"))
        try:
            expected_status = int(payload.get("expected_status", 200))
        except (TypeError, ValueError) as exc:
            raise ValueError("Expected HTTP status must be a number between 100 and 599.") from exc
        if not 100 <= expected_status <= 599:
            raise ValueError("Expected HTTP status must be between 100 and 599.")

    legacy = {
        "browser_path": payload.get("browser_path", ""),
        "expected_title": payload.get("expected_title", ""),
        "expected_h1": payload.get("expected_h1", ""),
        "required_text": payload.get("required_text", ""),
        "api_path": api_path or payload.get("api_path", "/"),
        "expected_status": expected_status,
        "api_expected_content_type": payload.get("api_expected_content_type", ""),
        "api_json_assertions": payload.get("api_json_assertions", []),
    }
    browser_checks = _validate_browser_checks(payload.get("browser_checks"), legacy)
    api_checks = _validate_api_checks(payload.get("api_checks"), legacy, api_configured=bool(api_url))
    first_browser = browser_checks[0]
    first_api = api_checks[0] if api_checks else None

    project_id = str((existing or {}).get("id") or secrets.token_hex(8))
    return {
        "id": project_id, "name": name.strip(),
        "store_url": store_url.rstrip("/"), "api_url": api_url.rstrip("/"),
        # Legacy top-level values mirror the first configured check for older clients.
        "api_path": first_api["path"] if first_api else api_path,
        "expected_status": first_api["expected_status"] if first_api else expected_status,
        "browser_path": first_browser["path"],
        "expected_title": first_browser["expected_title"],
        "expected_h1": first_browser["expected_h1"],
        "required_text": first_browser["required_text"],
        "api_expected_content_type": first_api["expected_content_type"] if first_api else "",
        "api_json_assertions": first_api["json_assertions"] if first_api else [],
        "browser_checks": browser_checks, "api_checks": api_checks,
        "built_in": bool((existing or {}).get("built_in", False)),
    }


def _safe_reports_relative(value: object) -> str | None:
    """Return a safe reports-relative file path, or None for untrusted paths."""
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    try:
        resolved = (ROOT / candidate).resolve()
        if not resolved.is_relative_to(REPORTS_DIR.resolve()) or not resolved.is_file():
            return None
    except (OSError, ValueError):
        return None
    return candidate.as_posix()


def _backup_source_files() -> tuple[dict[str, bytes], int]:
    files: dict[str, bytes] = {}
    omitted_artifacts = 0
    for label, path in (
        ("data/test_projects.json", PROJECTS_FILE),
        ("data/run_history.json", _history_file()),
        ("data/dashboard_state.json", STATE_FILE),
    ):
        try:
            if path.is_file():
                files[label] = path.read_bytes()
        except OSError:
            continue
    # A backup made before the first target run must still be restorable.
    # Keep explicit empty/default documents rather than omitting required files.
    files.setdefault(
        "data/test_projects.json",
        json.dumps({"projects": [_default_project()]}, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    files.setdefault("data/run_history.json", b'{"runs": []}')
    try:
        history = json.loads(files.get("data/run_history.json", b'{"runs":[]}').decode("utf-8"))
        runs = history.get("runs", []) if isinstance(history, dict) else []
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        runs = []
    artifact_paths: set[str] = set()
    for run in runs if isinstance(runs, list) else []:
        if not isinstance(run, dict):
            continue
        for key in ("log_path", "report_path", "evidence_path"):
            safe = _safe_reports_relative(run.get(key))
            if safe:
                artifact_paths.add(safe)
        for key in ("evidence_paths", "screenshot_paths"):
            values = run.get(key, [])
            if isinstance(values, list):
                artifact_paths.update(filter(None, (_safe_reports_relative(item) for item in values)))
    total_artifacts = 0
    for relative in sorted(artifact_paths):
        try:
            path = (ROOT / relative).resolve()
            size = path.stat().st_size
            if total_artifacts + size > MAX_BACKUP_ARTIFACT_BYTES:
                omitted_artifacts += 1
                continue
            total_artifacts += size
            files[f"artifacts/{relative}"] = path.read_bytes()
        except OSError:
            omitted_artifacts += 1
            continue
    return files, omitted_artifacts


def _build_backup_archive(reason: str = "manual") -> tuple[bytes, int]:
    files, omitted_artifacts = _backup_source_files()
    manifest = {
        "format": "shopguard-backup",
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": _now(),
        "reason": str(reason)[:80],
        "omitted_artifact_count": omitted_artifacts,
        "artifact_limit_bytes": MAX_BACKUP_ARTIFACT_BYTES,
        "files": {
            name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        },
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, data in files.items():
            archive.writestr(name, data)
    result = buffer.getvalue()
    if len(result) > MAX_BACKUP_BYTES:
        raise ValueError("Backup is larger than the 20 MB safety limit. Remove old reports or export without artifacts.")
    return result, omitted_artifacts


def _build_backup_bytes(reason: str = "manual") -> bytes:
    """Compatibility helper used by tests and internal callers needing raw ZIP bytes."""
    return _build_backup_archive(reason)[0]


def create_backup_file(*, automatic: bool = False, reason: str = "manual") -> dict:
    """Create a local ZIP backup of projects, run history and referenced evidence."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "auto" if automatic else "manual"
    filename = f"shopguard_{prefix}_{stamp}_{secrets.token_hex(3)}.zip"
    data, omitted_artifact_count = _build_backup_archive(reason)
    destination = BACKUPS_DIR / filename
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)
    if automatic:
        backups = sorted(BACKUPS_DIR.glob("shopguard_auto_*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in backups[AUTO_BACKUP_COUNT:]:
            try:
                old.unlink()
            except OSError:
                pass
    return {
        "filename": filename, "size": len(data), "created_at": _now(),
        "automatic": automatic, "omitted_artifact_count": omitted_artifact_count,
    }


def list_backups() -> list[dict]:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    values = []
    for path in sorted(BACKUPS_DIR.glob("shopguard_*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
        try:
            omitted_artifact_count = 0
            try:
                with zipfile.ZipFile(path, "r") as archive:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                    candidate = manifest.get("omitted_artifact_count", 0) if isinstance(manifest, dict) else 0
                    if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0:
                        omitted_artifact_count = candidate
            except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError):
                pass
            values.append({
                "filename": path.name, "size": path.stat().st_size,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "omitted_artifact_count": omitted_artifact_count,
            })
        except OSError:
            continue
    return values


def _restore_backup_bytes(data: bytes) -> dict:
    """Validate a ShopGuard backup completely before atomically replacing local data."""
    if not data or len(data) > MAX_BACKUP_BYTES:
        raise ValueError("Choose a non-empty backup ZIP no larger than 20 MB.")
    try:
        archive_buffer = io.BytesIO(data)
        with zipfile.ZipFile(archive_buffer, "r") as archive:
            infos = archive.infolist()
            if len(infos) > 1100:
                raise ValueError("Backup contains too many files.")
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                raise ValueError("Backup contains duplicate file names.")
            if any(item.is_dir() for item in infos):
                raise ValueError("Backup must contain files only.")
            if any(Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name for name in names):
                raise ValueError("Backup contains an unsafe file path.")
            if sum(item.file_size for item in infos) > MAX_BACKUP_BYTES:
                raise ValueError("Uncompressed backup is larger than the 20 MB safety limit.")
            if "manifest.json" not in names:
                raise ValueError("This ZIP is not a ShopGuard backup: manifest.json is missing.")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("format") != "shopguard-backup":
                raise ValueError("This ZIP is not a ShopGuard backup.")
            if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
                raise ValueError("This backup format version is not supported by this ShopGuard release.")
            omitted_artifacts_in_backup = manifest.get("omitted_artifact_count", 0)
            if not isinstance(omitted_artifacts_in_backup, int) or isinstance(omitted_artifacts_in_backup, bool) or omitted_artifacts_in_backup < 0:
                raise ValueError("Backup manifest contains an invalid omitted-artifact count.")
            declared = manifest.get("files")
            if not isinstance(declared, dict) or len(declared) > 1099:
                raise ValueError("Backup manifest is invalid.")
            if set(names) != set(declared) | {"manifest.json"}:
                raise ValueError("Backup contains files that are not listed in its manifest.")
            if any((item.external_attr >> 16) & 0o170000 == 0o120000 for item in infos):
                raise ValueError("Backup must not contain symbolic links.")
            payloads: dict[str, bytes] = {}
            for name, metadata in declared.items():
                if name not in names or name == "manifest.json" or not (
                    name in {"data/test_projects.json", "data/run_history.json", "data/dashboard_state.json"}
                    or name.startswith("artifacts/reports/")
                ):
                    raise ValueError("Backup manifest contains an unsupported file path.")
                if not isinstance(metadata, dict):
                    raise ValueError("Backup manifest entry is invalid.")
                body = archive.read(name)
                if metadata.get("size") != len(body) or metadata.get("sha256") != hashlib.sha256(body).hexdigest():
                    raise ValueError(f"Backup integrity check failed for {name}.")
                payloads[name] = body
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("The selected file is not a valid ShopGuard backup ZIP.") from exc

    required = {"data/test_projects.json", "data/run_history.json"}
    if not required.issubset(payloads):
        raise ValueError("Backup is incomplete: projects or run history are missing.")
    projects_doc = json.loads(payloads["data/test_projects.json"].decode("utf-8"))
    projects_raw = projects_doc.get("projects", []) if isinstance(projects_doc, dict) else None
    if not isinstance(projects_raw, list) or len(projects_raw) > 25:
        raise ValueError("Backup contains an invalid project list.")
    validated_projects = []
    seen_ids: set[str] = set()
    from dashboard.url_scanner import validate_public_url
    offline_url_validator = lambda value: validate_public_url(value, resolve_dns=False)
    for raw in projects_raw:
        if not isinstance(raw, dict) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", str(raw.get("id", ""))):
            raise ValueError("Backup contains an invalid project profile.")
        if raw["id"] in seen_ids:
            raise ValueError("Backup contains duplicate project IDs.")
        seen_ids.add(raw["id"])
        validated_projects.append(validate_project_payload(
            raw, {"id": raw["id"], "built_in": bool(raw.get("built_in"))},
            url_validator=offline_url_validator,
        ))

    history_doc = json.loads(payloads["data/run_history.json"].decode("utf-8"))
    runs = history_doc.get("runs", []) if isinstance(history_doc, dict) else None
    if not isinstance(runs, list) or len(runs) > MAX_RUN_HISTORY:
        raise ValueError("Backup contains an invalid or oversized run history.")
    valid_runs = []
    allowed_project_ids = seen_ids
    for run in runs:
        if not isinstance(run, dict) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", str(run.get("run_id", ""))):
            raise ValueError("Backup contains an invalid run history record.")
        target_id = run.get("target_id")
        if target_id and target_id not in allowed_project_ids:
            continue
        record = dict(run)
        for key in ("log_path", "report_path", "evidence_path"):
            path = record.get(key)
            if path and _safe_reports_relative_for_restore(path) not in {
                "reports/" + Path(name.removeprefix("artifacts/reports/")).as_posix()
                for name in payloads if name.startswith("artifacts/reports/")
            }:
                record[key] = None
        for key in ("evidence_paths", "screenshot_paths"):
            paths = record.get(key, [])
            if isinstance(paths, list):
                record[key] = [path for path in paths if _safe_reports_relative_for_restore(path) and any(
                    name == "artifacts/" + _safe_reports_relative_for_restore(path) for name in payloads
                )]
            else:
                record[key] = []
        valid_runs.append(record)

    state_payload = None
    if "data/dashboard_state.json" in payloads:
        state_doc = json.loads(payloads["data/dashboard_state.json"].decode("utf-8"))
        if not isinstance(state_doc, dict) or (state_doc.get("last_run") is not None and not isinstance(state_doc.get("last_run"), dict)):
            raise ValueError("Backup dashboard state is invalid.")
        state_payload = json.dumps(state_doc, ensure_ascii=False, indent=2).encode("utf-8")

    # Snapshot the currently installed data before replacing it.
    if PROJECTS_FILE.exists() or _history_file().exists() or STATE_FILE.exists():
        create_backup_file(automatic=True, reason="before restore")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_count = 0
    for name, body in payloads.items():
        if not name.startswith("artifacts/reports/"):
            continue
        relative = name.removeprefix("artifacts/")
        if not _safe_reports_relative_for_restore(relative):
            raise ValueError("Backup contains an unsafe artifact path.")
        destination = (ROOT / relative).resolve()
        if not destination.is_relative_to(REPORTS_DIR.resolve()):
            raise ValueError("Backup artifact path is outside reports/.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".restore-tmp")
        temporary.write_bytes(body)
        temporary.replace(destination)
        artifact_count += 1

    replacements = {
        PROJECTS_FILE: json.dumps({"projects": validated_projects}, ensure_ascii=False, indent=2).encode("utf-8"),
        _history_file(): json.dumps({"runs": valid_runs}, ensure_ascii=False, indent=2).encode("utf-8"),
    }
    if state_payload is not None:
        replacements[STATE_FILE] = state_payload
    for destination, body in replacements.items():
        temporary = destination.with_suffix(destination.suffix + ".restore-tmp")
        temporary.write_bytes(body)
        temporary.replace(destination)
    return {
        "projects_restored": len(validated_projects), "runs_restored": len(valid_runs),
        "artifacts_restored": artifact_count, "omitted_artifacts_in_backup": omitted_artifacts_in_backup,
    }


def _safe_reports_relative_for_restore(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or not normalized.startswith("reports/") or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def save_project(payload: dict) -> dict:
    with PROJECTS_LOCK:
        projects = load_projects()
        project_id = payload.get("id")
        existing = next((item for item in projects if item["id"] == project_id), None) if project_id else None
        if project_id and existing is None:
            raise ValueError("This test project no longer exists. Refresh the dashboard.")
        validated = validate_project_payload(payload, existing)
        if existing or projects:
            create_backup_file(automatic=True, reason="before project update or creation")
        if existing:
            projects = [validated if item["id"] == project_id else item for item in projects]
        else:
            if len(projects) >= 25:
                raise ValueError("You can save up to 25 test projects.")
            projects.append(validated)
        _save_projects(projects)
        return validated


def delete_project(project_id: str) -> None:
    with PROJECTS_LOCK:
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", project_id):
            raise ValueError("Choose a valid test project.")
        projects = load_projects()
        project = next((item for item in projects if item["id"] == project_id), None)
        if project is None:
            raise ValueError("Test project not found.")
        if project.get("built_in"):
            raise ValueError("The built-in Toolshop example cannot be deleted. You can edit it or add another project.")
        create_backup_file(automatic=True, reason="before project deletion")
        _save_projects([item for item in projects if item["id"] != project_id])


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_state() -> dict | None:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        run = value.get("last_run") if isinstance(value, dict) else None
        if not isinstance(run, dict):
            return None
        if run.get("status") == "running":
            run["status"] = "interrupted"
            run["ended_at"] = _now()
            run["message"] = "The dashboard stopped before this run could be recorded as complete."
        return run
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _persist_state() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"last_run": LAST_RUN}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)


def _history_file() -> Path:
    return REPORTS_DIR / "run_history.json"


def load_run_history() -> list[dict]:
    """Load recent registered-project runs. History is local and bounded."""
    with RUN_HISTORY_LOCK:
        try:
            value = json.loads(_history_file().read_text(encoding="utf-8"))
            runs = value.get("runs", []) if isinstance(value, dict) else []
            if not isinstance(runs, list):
                return []
            cleaned = [item for item in runs if isinstance(item, dict) and isinstance(item.get("run_id"), str)]
            cleaned.sort(key=lambda item: str(item.get("started_at", "")), reverse=True)
            return cleaned[:MAX_RUN_HISTORY]
        except (OSError, json.JSONDecodeError, TypeError):
            return []


def _record_run_history(run: dict) -> None:
    """Insert or update a target run, keeping the newest 1,000 records overall."""
    if not isinstance(run, dict) or not run.get("target_id") or not run.get("run_id"):
        return
    with RUN_HISTORY_LOCK:
        history_path = _history_file()
        try:
            value = json.loads(history_path.read_text(encoding="utf-8"))
            runs = value.get("runs", []) if isinstance(value, dict) else []
            if not isinstance(runs, list):
                runs = []
        except (OSError, json.JSONDecodeError, TypeError):
            runs = []
        snapshot = dict(run)
        replaced = False
        for index, item in enumerate(runs):
            if isinstance(item, dict) and item.get("run_id") == snapshot["run_id"]:
                runs[index] = snapshot
                replaced = True
                break
        if not replaced:
            runs.append(snapshot)
        runs = [item for item in runs if isinstance(item, dict)]
        runs.sort(key=lambda item: str(item.get("started_at", "")), reverse=True)
        runs = runs[:MAX_RUN_HISTORY]
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        temporary = history_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(history_path)


def _project_history_payload() -> dict[str, list[dict]]:
    """Return every retained run grouped by project; the UI can collapse long histories."""
    grouped: dict[str, list[dict]] = {}
    for run in load_run_history():
        project_id = run.get("target_id")
        if not isinstance(project_id, str):
            continue
        entries = grouped.setdefault(project_id, [])
        entries.append({
            "run_id": run.get("run_id"),
            "check_type": run.get("check_type"),
            "status": run.get("status"),
            "started_at": run.get("started_at"),
            "duration": run.get("duration"),
            "summary": run.get("summary"),
            "message": run.get("message"),
            "log_available": bool(run.get("log_path")),
            "report_available": bool(run.get("report_path")),
            "evidence_available": bool(run.get("evidence_paths") or run.get("evidence_path")),
            "screenshot_count": len(run.get("screenshot_paths", [])) if isinstance(run.get("screenshot_paths"), list) else 0,
            "failures": run.get("failures", [])[:5] if isinstance(run.get("failures"), list) else [],
        })
    return grouped


def _run_artifact(run_id: str, kind: str) -> tuple[bytes, str, str] | None:
    """Resolve recorded log/report/evidence/screenshot files strictly under reports/."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", run_id):
        return None
    match = re.fullmatch(r"(log|report|evidence|screenshot)(?:-(\d+))?", kind or "")
    if not match:
        return None
    artifact_kind, index_text = match.groups()
    run = next((item for item in load_run_history() if item.get("run_id") == run_id), None)
    if not run:
        return None
    if artifact_kind == "log":
        relative = run.get("log_path")
    elif artifact_kind == "report":
        relative = run.get("report_path")
    else:
        key = "evidence_paths" if artifact_kind == "evidence" else "screenshot_paths"
        values = run.get(key, [])
        if not isinstance(values, list):
            values = []
        if not values and artifact_kind == "evidence" and run.get("evidence_path"):
            values = [run["evidence_path"]]
        index = int(index_text or "0")
        relative = values[index] if index < len(values) else None
    if not isinstance(relative, str) or not relative:
        return None
    try:
        reports_root = REPORTS_DIR.resolve()
        candidate = (ROOT / relative).resolve()
        expected_suffix = {"log": ".log", "report": ".xml", "evidence": ".json", "screenshot": ".png"}[artifact_kind]
        size_limit = {"log": 250_000, "report": 1_000_000, "evidence": 100_000, "screenshot": 5_000_000}[artifact_kind]
        if candidate.suffix.lower() != expected_suffix or not candidate.is_relative_to(reports_root):
            return None
        if not candidate.is_file() or candidate.stat().st_size > size_limit:
            return None
        body = candidate.read_bytes()
        content_type = {
            "log": "text/plain; charset=utf-8", "report": "application/xml; charset=utf-8",
            "evidence": "application/json; charset=utf-8", "screenshot": "image/png",
        }[artifact_kind]
        return body, content_type, candidate.name
    except (OSError, ValueError):
        return None


def parse_junit_summary(report_path: Path) -> dict | None:
    """Return a small summary from pytest's JUnit XML report, if available."""
    if not report_path.is_file():
        return None
    try:
        root = ET.parse(report_path).getroot()
    except (ET.ParseError, OSError):
        return None
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    if not suites:
        return None
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    duration = 0.0
    for suite in suites:
        for key in totals:
            try:
                totals[key] += int(suite.attrib.get(key, "0"))
            except ValueError:
                pass
        try:
            duration += float(suite.attrib.get("time", "0"))
        except ValueError:
            pass
    totals["passed"] = max(0, totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"])
    totals["duration"] = round(duration, 2)
    return totals


def parse_junit_failures(report_path: Path, limit: int = 20) -> list[dict]:
    """Extract concise, bounded failure evidence from a pytest JUnit report."""
    if not report_path.is_file():
        return []
    try:
        root = ET.parse(report_path).getroot()
    except (ET.ParseError, OSError):
        return []
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    failures: list[dict] = []
    for suite in suites:
        for case in suite.findall("testcase"):
            node = case.find("failure")
            if node is None:
                node = case.find("error")
            if node is None:
                continue
            failures.append({
                "test": str(case.attrib.get("name", "test"))[:180],
                "classname": str(case.attrib.get("classname", ""))[:180],
                "message": str(node.attrib.get("message", "Test failed"))[:1000],
                "details": (node.text or "").strip()[-3000:],
            })
            if len(failures) >= limit:
                return failures
    return failures


def _tail(path: str | None, limit: int = 18000) -> str:
    """Read only dashboard log files from the reports directory.

    State is persisted locally, but still treat its stored path as untrusted input
    so a malformed state file cannot make the HTTP handler expose other files.
    """
    if not path:
        return ""
    try:
        reports_root = REPORTS_DIR.resolve()
        candidate = (ROOT / path).resolve()
        if candidate.suffix != ".log" or not candidate.is_relative_to(reports_root):
            return ""
        with candidate.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            return stream.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _run_suite(suite_id: str, run_id: str) -> None:
    global CURRENT_RUN, LAST_RUN
    suite = SUITES[suite_id]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = REPORTS_DIR / f"dashboard_{suite_id}.log"
    xml_path = REPORTS_DIR / f"dashboard_{suite_id}.xml"
    command = [sys.executable, "-m", "pytest", *suite["args"], "-v", "--junitxml", str(xml_path)]
    started = time.monotonic()
    return_code: int | None = None
    message = None
    try:
        # Avoid accidentally reading a stale JUnit report if pytest cannot start.
        try:
            xml_path.unlink(missing_ok=True)
        except OSError:
            pass
        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            log_file.write(f"ShopGuard dashboard run: {suite['name']}\nCommand: {subprocess.list2cmdline(command)}\n\n")
            log_file.flush()
            completed = subprocess.run(
                command,
                cwd=ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
                shell=False,
                timeout=SUITE_TIMEOUT_SECONDS[suite_id],
            )
            return_code = completed.returncode
    except subprocess.TimeoutExpired:
        return_code = 124
        message = f"Test group exceeded the {SUITE_TIMEOUT_SECONDS[suite_id]}-second time limit."
        with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
            log_file.write(f"\nTIMEOUT: {message}\n")
    except OSError as exc:
        message = f"Could not start pytest: {exc.__class__.__name__}: {exc}"
        with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
            log_file.write(f"\n{message}\n")

    summary = parse_junit_summary(xml_path)
    if return_code is None:
        status = "error"
    elif return_code == 0:
        status = "passed"
    else:
        status = "failed"
    finished = time.monotonic()
    with LOCK:
        if CURRENT_RUN is None or CURRENT_RUN.get("run_id") != run_id:
            return
        LAST_RUN = {
            "run_id": run_id,
            "suite_id": suite_id,
            "name": suite["name"],
            "status": status,
            "started_at": CURRENT_RUN["started_at"],
            "ended_at": _now(),
            "duration": round(finished - started, 2),
            "return_code": return_code,
            "summary": summary,
            "log_path": str(log_path.relative_to(ROOT)).replace("\\", "/"),
            "report_path": str(xml_path.relative_to(ROOT)).replace("\\", "/") if xml_path.exists() else None,
            "message": message,
        }
        CURRENT_RUN = None
        _persist_state()


def _safe_settings() -> dict:
    try:
        # Import here so a malformed optional .env does not prevent the dashboard
        # from serving its UI and showing the configuration error.
        from shopguard.config import get_settings
        settings = get_settings()
        return {"shop_url": settings.shop_url, "api_url": settings.api_url, "warning": None}
    except Exception as exc:  # surfaced as a local configuration warning
        return {"shop_url": None, "api_url": None, "warning": str(exc)}


def _project_analytics_payload() -> dict[str, dict]:
    """Aggregate recent registered-project runs for the local analytics panel."""
    grouped: dict[str, list[dict]] = {}
    for run in load_run_history():
        project_id = run.get("target_id")
        if not isinstance(project_id, str):
            continue
        grouped.setdefault(project_id, []).append(run)
    analytics: dict[str, dict] = {}
    for project_id, runs in grouped.items():
        runs.sort(key=lambda item: str(item.get("started_at", "")), reverse=True)
        recent = runs[:30]
        completed = [item for item in recent if item.get("status") in {"passed", "failed", "error"}]
        passed = sum(1 for item in completed if item.get("status") == "passed")
        failed = sum(1 for item in completed if item.get("status") == "failed")
        errors = sum(1 for item in completed if item.get("status") == "error")
        durations = [float(item["duration"]) for item in completed if isinstance(item.get("duration"), (int, float)) and math.isfinite(float(item["duration"]))]
        latest = recent[0] if recent else None
        previous = recent[1] if len(recent) > 1 else None
        latest_duration = latest.get("duration") if latest else None
        previous_duration = previous.get("duration") if previous else None
        duration_delta = None
        if isinstance(latest_duration, (int, float)) and isinstance(previous_duration, (int, float)):
            duration_delta = round(float(latest_duration) - float(previous_duration), 2)
        analytics[project_id] = {
            "total_runs": len(recent), "completed_runs": len(completed),
            "passed": passed, "failed": failed, "errors": errors,
            "success_rate": round((passed / len(completed)) * 100, 1) if completed else None,
            "average_duration": round(sum(durations) / len(durations), 2) if durations else None,
            "latest_status": latest.get("status") if latest else None,
            "latest_duration": latest_duration, "previous_duration": previous_duration,
            "duration_delta": duration_delta,
            "trend": [{
                "run_id": item.get("run_id"), "status": item.get("status"),
                "duration": item.get("duration"), "started_at": item.get("started_at"),
                "check_type": item.get("check_type"),
            } for item in reversed(recent)],
        }
    return analytics


def status_payload() -> dict:
    with LOCK:
        current = dict(CURRENT_RUN) if CURRENT_RUN else None
        last = dict(LAST_RUN) if LAST_RUN else None
    active = current or last
    log_tail = _tail(active.get("log_path") if active else None)
    if current:
        # During an active run, its log path is added when the run is scheduled.
        log_tail = _tail(current.get("log_path"))
    with LOCK:
        current_scan = dict(CURRENT_SCAN) if CURRENT_SCAN else None
        last_scan = dict(LAST_SCAN) if LAST_SCAN else None
    return {
        "running": current is not None,
        "current_run": current,
        "last_run": last,
        "scan_running": current_scan is not None,
        "current_scan": current_scan,
        "last_scan": last_scan,
        "log_tail": log_tail,
        "suites": [
            {
                "id": key,
                "name": value["name"],
                "short": value["short"],
                "description": value["description"],
                "live": value["live"],
                "warning": value["warning"],
                "command": f".venv\\Scripts\\python.exe -m pytest {subprocess.list2cmdline(value['args'])} -v",
            }
            for key, value in SUITES.items()
        ],
        "targets": _safe_settings(),
        "projects": load_projects(),
        "project_history": _project_history_payload(),
        "project_analytics": _project_analytics_payload(),
        "backups": list_backups(),
        "automatic_backups_kept": AUTO_BACKUP_COUNT,
    }


def start_suite(suite_id: str) -> tuple[bool, str]:
    global CURRENT_RUN, LAST_RUN
    if suite_id not in SUITES:
        return False, "Unknown test group."
    with LOCK:
        if CURRENT_RUN is not None or CURRENT_SCAN is not None:
            return False, "A test or website check is already running. Wait for it to finish."
        run_id = f"{suite_id}-{int(time.time() * 1000)}"
        suite = SUITES[suite_id]
        log_path = REPORTS_DIR / f"dashboard_{suite_id}.log"
        CURRENT_RUN = {
            "run_id": run_id,
            "suite_id": suite_id,
            "name": suite["name"],
            "status": "running",
            "started_at": _now(),
            "log_path": str(log_path.relative_to(ROOT)).replace("\\", "/"),
            "warning": suite["warning"],
        }
        LAST_RUN = dict(CURRENT_RUN)
        _persist_state()
        worker = threading.Thread(target=_run_suite, args=(suite_id, run_id), daemon=True)
        worker.start()
    return True, run_id


def _target_check_timeout(check_type: str, browser_checks: list[dict], api_checks: list[dict]) -> int:
    """Scale the subprocess timeout with the configured number of sequential checks."""
    browser_count = len(browser_checks) if check_type in {"ui", "all"} else 0
    api_count = len(api_checks) if check_type in {"api", "all"} else 0
    estimate = 30 + browser_count * 25 + api_count * 20
    return min(1000, max(180, estimate))


def _run_target_check(project: dict, check_type: str, run_id: str) -> None:
    """Run all configured read-only checks of one type for the selected project."""
    global CURRENT_RUN, LAST_RUN
    target_id = project["id"]
    safe_run_id = re.sub(r"[^a-zA-Z0-9_-]", "", run_id)[:80]
    log_path = REPORTS_DIR / f"target_{safe_run_id}.log"
    xml_path = REPORTS_DIR / f"target_{safe_run_id}.xml"
    artifact_prefix = REPORTS_DIR / f"target_{safe_run_id}"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    browser_checks = project.get("browser_checks") or [{
        "id": "browser-1", "name": "Storefront", "path": project.get("browser_path", ""),
        "expected_title": project.get("expected_title", ""), "expected_h1": project.get("expected_h1", ""),
        "required_text": project.get("required_text", ""),
    }]
    api_checks = project.get("api_checks") or ([{
        "id": "api-1", "name": "API endpoint", "path": project.get("api_path", "/"),
        "expected_status": project.get("expected_status", 200),
        "expected_content_type": project.get("api_expected_content_type", ""),
        "json_assertions": project.get("api_json_assertions", []),
    }] if project.get("api_url") else [])
    if check_type == "ui":
        marker = "target_ui"
    elif check_type == "api":
        marker = "target_api"
    else:
        marker = "target_ui or target_api" if api_checks else "target_ui"
    args = ["-m", marker, "tests/targets/test_registered_project.py", "-v", "--junitxml", str(xml_path)]
    command = [sys.executable, "-m", "pytest", *args]
    env = os.environ.copy()
    env.update({
        "SHOPGUARD_TARGET_NAME": project["name"],
        "SHOPGUARD_TARGET_URL": project["store_url"],
        "SHOPGUARD_TARGET_API_URL": project.get("api_url", ""),
        "SHOPGUARD_TARGET_API_PATH": project.get("api_path", "/"),
        "SHOPGUARD_TARGET_EXPECTED_STATUS": str(project.get("expected_status", 200)),
        "SHOPGUARD_TARGET_BROWSER_PATH": project.get("browser_path", ""),
        "SHOPGUARD_TARGET_EXPECTED_TITLE": project.get("expected_title", ""),
        "SHOPGUARD_TARGET_EXPECTED_H1": project.get("expected_h1", ""),
        "SHOPGUARD_TARGET_REQUIRED_TEXT": project.get("required_text", ""),
        "SHOPGUARD_TARGET_API_EXPECTED_CONTENT_TYPE": project.get("api_expected_content_type", ""),
        "SHOPGUARD_TARGET_API_JSON_ASSERTIONS": json.dumps(project.get("api_json_assertions", []), ensure_ascii=False),
        "SHOPGUARD_TARGET_BROWSER_CHECKS": json.dumps(browser_checks, ensure_ascii=False),
        "SHOPGUARD_TARGET_API_CHECKS": json.dumps(api_checks, ensure_ascii=False),
        "SHOPGUARD_TARGET_ARTIFACT_PREFIX": str(artifact_prefix.resolve()),
        "SHOPGUARD_TARGET_RUN_ID": safe_run_id,
    })
    started = time.monotonic()
    return_code: int | None = None
    message = None
    timeout = _target_check_timeout(check_type, browser_checks, api_checks)
    try:
        xml_path.unlink(missing_ok=True)
        for old_artifact in REPORTS_DIR.glob(f"{artifact_prefix.name}-*"):
            try:
                old_artifact.unlink()
            except OSError:
                pass
        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            log_file.write(
                f"ShopGuard target checks: {project['name']} ({check_type.upper()})\n"
                f"Storefront: {project['store_url']}\nAPI: {project.get('api_url') or 'not configured'}\n"
                f"Browser checks: {len(browser_checks)} · API checks: {len(api_checks)}\n"
                f"Command: {subprocess.list2cmdline(command)}\n\n"
            )
            log_file.flush()
            completed = subprocess.run(
                command, cwd=ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT,
                check=False, shell=False, timeout=timeout,
            )
            return_code = completed.returncode
    except subprocess.TimeoutExpired:
        return_code = 124
        message = f"Target checks exceeded the {timeout}-second time limit."
        with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
            log_file.write(f"\nTIMEOUT: {message}\n")
    except OSError as exc:
        message = f"Could not start pytest: {exc.__class__.__name__}: {exc}"
        with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
            log_file.write(f"\n{message}\n")

    summary = parse_junit_summary(xml_path)
    failures = parse_junit_failures(xml_path)
    evidence_paths = sorted(str(path.relative_to(ROOT)).replace("\\", "/") for path in REPORTS_DIR.glob(f"{artifact_prefix.name}-*.json"))
    screenshot_paths = sorted(str(path.relative_to(ROOT)).replace("\\", "/") for path in REPORTS_DIR.glob(f"{artifact_prefix.name}-*.png"))
    status = "error" if return_code is None else "passed" if return_code == 0 else "failed"
    finished = time.monotonic()
    with LOCK:
        if CURRENT_RUN is None or CURRENT_RUN.get("run_id") != run_id:
            return
        LAST_RUN = {
            "run_id": run_id, "suite_id": f"target_{check_type}",
            "check_type": check_type, "check_count": (len(browser_checks) if check_type == "ui" else len(api_checks) if check_type == "api" else len(browser_checks) + len(api_checks)),
            "name": f"{check_type.upper()} checks · {project['name']}",
            "target_id": target_id, "target_name": project["name"],
            "status": status, "started_at": CURRENT_RUN["started_at"], "ended_at": _now(),
            "duration": round(finished - started, 2), "return_code": return_code,
            "summary": summary, "failures": failures,
            "evidence_paths": evidence_paths, "screenshot_paths": screenshot_paths,
            "log_path": str(log_path.relative_to(ROOT)).replace("\\", "/"),
            "report_path": str(xml_path.relative_to(ROOT)).replace("\\", "/") if xml_path.exists() else None,
            "message": message,
        }
        CURRENT_RUN = None
        _persist_state()
        _record_run_history(LAST_RUN)


def start_target_check(target_id: str, check_type: str) -> tuple[bool, str]:
    global CURRENT_RUN, LAST_RUN
    if check_type not in {"ui", "api", "all"}:
        return False, "Choose browser, API or all project checks."
    project = next((item for item in load_projects() if item["id"] == target_id), None)
    if project is None:
        return False, "Test project not found. Refresh the dashboard."
    if check_type == "api" and not project.get("api_url"):
        return False, "Add an API base URL and API path before running API checks."
    if check_type == "all" and not project.get("browser_checks") and not project.get("browser_path", "") and not project.get("store_url"):
        return False, "Configure at least one browser check for this project."
    try:
        from dashboard.url_scanner import validate_public_url
        validate_public_url(project["store_url"])
        if project.get("api_url"):
            validate_public_url(project["api_url"])
        _validate_browser_checks(project.get("browser_checks"), project)
        if check_type in {"api", "all"} and project.get("api_url"):
            _validate_api_checks(project.get("api_checks"), project, api_configured=True)
        elif check_type == "api":
            return False, "Add an API base URL before running API checks."
    except Exception as exc:
        return False, f"The saved target is no longer valid: {exc}"
    with LOCK:
        if CURRENT_RUN is not None or CURRENT_SCAN is not None:
            return False, "A test or website check is already running. Wait for it to finish."
        run_id = f"target-{check_type}-{target_id}-{int(time.time() * 1000)}"
        CURRENT_RUN = {
            "run_id": run_id, "suite_id": f"target_{check_type}",
            "check_type": check_type,
            "name": f"{check_type.upper()} checks · {project['name']}",
            "target_id": target_id, "target_name": project["name"],
            "check_count": (len(project.get("browser_checks", [])) if check_type == "ui" else len(project.get("api_checks", [])) if check_type == "api" else len(project.get("browser_checks", [])) + len(project.get("api_checks", []))),
            "status": "running", "started_at": _now(),
            "log_path": f"reports/target_{run_id}.log",
            "warning": "Read-only check. The target website must be public and you must have permission to test it.",
        }
        LAST_RUN = dict(CURRENT_RUN)
        _persist_state()
        _record_run_history(CURRENT_RUN)
        worker = threading.Thread(target=_run_target_check, args=(dict(project), check_type, run_id), daemon=True)
        worker.start()
    return True, run_id


def _run_url_scan(scan_id: str, target_url: str) -> None:
    global CURRENT_SCAN, LAST_SCAN
    from dashboard.url_scanner import scan_public_url

    started = time.monotonic()
    try:
        result = scan_public_url(target_url)
        status = "completed"
        error = None
    except Exception as exc:
        result = None
        status = "error"
        error = str(exc) or exc.__class__.__name__
    finished = time.monotonic()
    with LOCK:
        if CURRENT_SCAN is None or CURRENT_SCAN.get("scan_id") != scan_id:
            return
        LAST_SCAN = {
            "scan_id": scan_id,
            "name": "Website check",
            "status": status,
            "started_at": CURRENT_SCAN["started_at"],
            "ended_at": _now(),
            "duration": round(finished - started, 2),
            "url": target_url,
            "result": result,
            "error": error,
        }
        CURRENT_SCAN = None


def start_url_scan(target_url: str) -> tuple[bool, str]:
    global CURRENT_SCAN
    from dashboard.url_scanner import ScanInputError, validate_public_url

    try:
        normalized_url = validate_public_url(target_url)
    except ScanInputError as exc:
        return False, str(exc)
    with LOCK:
        if CURRENT_RUN is not None or CURRENT_SCAN is not None:
            return False, "A test or website check is already running. Wait for it to finish."
        scan_id = f"url-scan-{int(time.time() * 1000)}"
        CURRENT_SCAN = {
            "scan_id": scan_id,
            "name": "Website check",
            "status": "running",
            "started_at": _now(),
            "url": normalized_url,
        }
        worker = threading.Thread(target=_run_url_scan, args=(scan_id, normalized_url), daemon=True)
        worker.start()
    return True, scan_id


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "ShopGuardDashboard/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send(self, status: int, body: bytes, content_type: str, extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        for header_name, header_value in (extra_headers or {}).items():
            if header_name.lower() not in {"content-type", "content-length", "set-cookie"}:
                self.send_header(header_name, header_value)
        # The dashboard currently uses inline CSS and JavaScript. Keep those two
        # allowances explicit while blocking plugins, framing and cross-origin API calls.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
            "font-src 'self' data:; connect-src 'self'; form-action 'self'; "
            "base-uri 'self'; object-src 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # A browser may close the tab while a response is being written.
            pass

    def _trusted_local_request(self) -> bool:
        """Reject DNS-rebinding Host headers and cross-origin browser POSTs."""
        try:
            peer = ipaddress.ip_address(self.client_address[0])
            if not peer.is_loopback:
                return False
            host_header = self.headers.get("Host", "")
            host = urlsplit("//" + host_header)
            hostname = (host.hostname or "").lower()
            if (
                hostname not in {"127.0.0.1", "localhost", "::1"}
                or host.username is not None
                or host.password is not None
                or host.path not in {"", "/"}
                or host.query
                or host.fragment
            ):
                return False
            if host.port != self.server.server_port:
                return False
            origin_value = self.headers.get("Origin")
            if not origin_value:
                return True  # CLI and local scripts may not send Origin.
            origin = urlsplit(origin_value)
            origin_host = (origin.hostname or "").lower()
            return (
                origin.scheme == "http"
                and origin_host == hostname
                and origin.port == self.server.server_port
                and origin.username is None
                and origin.password is None
                and origin.path in {"", "/"}
                and not origin.query
                and not origin.fragment
            )
        except (ValueError, TypeError):
            return False

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed_request = urlsplit(self.path)
        path = parsed_request.path
        if path in {"/", "/index.html"}:
            try:
                self._send(200, DASHBOARD_FILE.read_bytes(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, b"Dashboard file is missing.", "text/plain; charset=utf-8")
        elif path == "/api/status":
            self._json(200, status_payload())
        elif path == "/api/projects":
            self._json(200, {"projects": load_projects()})
        elif path == "/api/backup/list":
            if not self._trusted_local_request():
                self._json(403, {"error": "Requests must come from the local dashboard."})
                return
            self._json(200, {"backups": list_backups(), "automatic_backups_kept": AUTO_BACKUP_COUNT})
        elif path == "/api/backup/download":
            if not self._trusted_local_request():
                self._json(403, {"error": "Requests must come from the local dashboard."})
                return
            name = parse_qs(parsed_request.query, keep_blank_values=True).get("name", [""])[0]
            if not re.fullmatch(r"shopguard_(?:auto|manual)_\d{8}_\d{6}_[a-f0-9]{6}\.zip", name):
                self._json(400, {"error": "Choose a valid ShopGuard backup."})
                return
            candidate = (BACKUPS_DIR / name).resolve()
            if not candidate.is_relative_to(BACKUPS_DIR.resolve()) or not candidate.is_file() or candidate.stat().st_size > MAX_BACKUP_BYTES:
                self._json(404, {"error": "Backup file not found."})
                return
            body = candidate.read_bytes()
            self._send(200, body, "application/zip", {"Content-Disposition": f'attachment; filename="{name}"'})
        elif path == "/api/artifact":
            if not self._trusted_local_request():
                self._json(403, {"error": "Requests must come from the local dashboard."})
                return
            params = parse_qs(parsed_request.query, keep_blank_values=True)
            run_id = params.get("run_id", [""])[0]
            kind = params.get("kind", [""])[0]
            artifact = _run_artifact(run_id, kind)
            if artifact is None:
                self._json(404, {"error": "Run artifact not found."})
            else:
                body, content_type, filename = artifact
                self._send(200, body, content_type)
        elif path == "/health":
            self._json(200, {"ok": True, "service": "ShopGuard dashboard"})
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlsplit(self.path).path
        if path not in {"/api/run", "/api/scan", "/api/projects", "/api/projects/delete", "/api/target-run", "/api/backup/create", "/api/backup/restore"}:
            self._json(404, {"error": "Not found"})
            return
        if not self._trusted_local_request():
            self._json(403, {"error": "Requests must come from the local dashboard."})
            return
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if path == "/api/backup/restore":
            if media_type not in {"application/zip", "application/octet-stream"}:
                self._json(415, {"error": "Upload a ShopGuard backup ZIP file."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > MAX_BACKUP_BYTES:
                    self._json(400, {"error": "Backup upload must be between 1 byte and 20 MB."})
                    return
                result = _restore_backup_bytes(self.rfile.read(length))
                global LAST_RUN
                with LOCK:
                    LAST_RUN = _read_state()
                self._json(200, {"restored": True, **result})
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc) or "Could not restore this backup."})
            return
        if media_type != "application/json":
            self._json(415, {"error": "Content-Type must be application/json."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 8192:
                self._json(400, {"error": "Invalid request size."})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "Send valid JSON."})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": "Send a JSON object."})
            return

        if path == "/api/backup/create":
            try:
                backup = create_backup_file(automatic=False, reason="manual user backup")
            except (OSError, ValueError) as exc:
                self._json(400, {"error": str(exc) or "Could not create backup."})
                return
            self._json(200, {"created": True, "backup": backup})
            return

        if path == "/api/projects":
            try:
                project = save_project(payload)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, {"saved": True, "project": project, "projects": load_projects()})
            return

        if path == "/api/projects/delete":
            try:
                delete_project(payload.get("id"))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, {"deleted": True, "projects": load_projects()})
            return

        if path == "/api/target-run":
            target_id = payload.get("id")
            check_type = payload.get("check")
            if not isinstance(target_id, str) or not isinstance(check_type, str):
                self._json(400, {"error": "Choose a test project and check type."})
                return
            ok, message = start_target_check(target_id, check_type)
            if not ok:
                status = 409 if "already running" in message.lower() else 400
                self._json(status, {"error": message})
                return
            self._json(202, {"accepted": True, "run_id": message})
            return

        if path == "/api/run":
            if not isinstance(payload.get("suite"), str):
                self._json(400, {"error": "Choose a test group."})
                return
            ok, message = start_suite(payload["suite"])
            if not ok:
                status = 409 if "already running" in message.lower() else 400
                self._json(status, {"error": message})
                return
            self._json(202, {"accepted": True, "run_id": message})
            return

        if not isinstance(payload.get("url"), str):
            self._json(400, {"error": "Enter a website address."})
            return
        ok, message = start_url_scan(payload["url"])
        if not ok:
            status = 409 if "already running" in message.lower() else 400
            self._json(status, {"error": message})
            return
        self._json(202, {"accepted": True, "scan_id": message})



def main() -> None:
    global LAST_RUN
    LAST_RUN = _read_state()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if LAST_RUN and LAST_RUN.get("status") == "interrupted":
        _persist_state()
    try:
        server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    except OSError as exc:
        raise SystemExit(f"Could not start ShopGuard dashboard at http://{HOST}:{PORT}: {exc}") from exc
    print("=" * 62)
    print("ShopGuard QA Automation")
    print(f"Open http://{HOST}:{PORT} in your browser")
    print("Bound to 127.0.0.1 only. Press Ctrl+C to stop.")
    print("=" * 62)
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\nStopping ShopGuard dashboard...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
