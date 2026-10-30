"""Pytest fixtures. Live browsers are not launched by ordinary `pytest`."""
import os
import re
from pathlib import Path

import pytest
from shopguard.client import ToolshopClient
from shopguard.config import get_settings


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture
def client(settings):
    import requests
    session = requests.Session()
    c = ToolshopClient(settings.api_url, session)
    yield c
    session.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    rep = result.get_result()
    setattr(item, "rep_" + rep.when, rep)


@pytest.fixture
def shop_page(request):
    """Isolated browser context; save screenshot and tracing for failed UI tests."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=os.getenv("HEADED", "false").lower() != "true")
        context = browser.new_context(viewport={"width": 1400, "height": 900}, locale="en-US")
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(12000)
        try:
            yield page
        finally:
            result = getattr(request.node, "rep_call", None)
            failed = bool(result and result.failed)
            if failed:
                output = Path("reports")
                output.mkdir(exist_ok=True)
                name = re.sub(r"[^a-zA-Z0-9_-]+", "-", request.node.nodeid)[:130]
                try:
                    page.screenshot(path=str(output / f"{name}.png"), full_page=True)
                except Exception as exc:
                    print(f"Screenshot unavailable: {exc}")
                context.tracing.stop(path=str(output / f"{name}.zip"))
            else:
                context.tracing.stop()
            context.close()
            browser.close()
