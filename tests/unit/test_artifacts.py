"""Validate distribution files without running tests against live servers."""
import json
import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
COLLECTION = json.loads((ROOT / "postman/ShopGuard.postman_collection.json").read_text(encoding="utf-8"))


@pytest.mark.unit
def test_postman_uses_schema_v21():
    assert "v2.1.0" in COLLECTION["info"]["schema"]


@pytest.mark.unit
def test_postman_has_multiple_folders():
    assert len(COLLECTION["item"]) >= 2


@pytest.mark.unit
def test_postman_has_at_least_ten_requests():
    assert sum(len(group["item"]) for group in COLLECTION["item"]) >= 10


@pytest.mark.unit
def test_postman_has_no_write_operations_except_demo_login():
    for group in COLLECTION["item"]:
        for item in group["item"]:
            req = item["request"]
            if req["method"] != "GET":
                assert req["method"] == "POST"
                assert req["url"]["raw"].endswith("/users/login")


@pytest.mark.unit
def test_each_postman_request_has_assertions():
    for group in COLLECTION["item"]:
        for item in group["item"]:
            assert any(ev["listen"] == "test" and ev["script"]["exec"] for ev in item["event"])


@pytest.mark.unit
def test_target_host_is_from_variable():
    for group in COLLECTION["item"]:
        for item in group["item"]:
            assert item["request"]["url"]["raw"].startswith("{{apiUrl}}/")


@pytest.mark.unit
def test_environment_values_only_contain_demo_hosts_and_accounts():
    env = json.loads((ROOT / "postman/Toolshop.postman_environment.json").read_text(encoding="utf-8"))
    mapping = {item["key"]: item["value"] for item in env["values"]}
    assert mapping["apiUrl"] == "https://api.practicesoftwaretesting.com"
    assert mapping["demoEmail"].endswith("@practicesoftwaretesting.com")


@pytest.mark.unit
@pytest.mark.parametrize("name", ["README.md", ".env.example", ".gitignore", "docs/TEST_PLAN.md", "docs/TEST_CASES.md", "docs/START_HERE_RU.md", ".github/workflows/tests.yml"])
def test_required_documentation_present(name):
    assert (ROOT / name).is_file()


@pytest.mark.unit
def test_postman_collection_has_documented_groups_and_request_count():
    groups = {group["name"]: group["item"] for group in COLLECTION["item"]}
    assert set(groups) == {"Catalog", "Authentication"}
    assert len(groups["Catalog"]) == 10
    assert len(groups["Authentication"]) == 4
    assert sum(len(items) for items in groups.values()) == 14


@pytest.mark.unit
def test_postman_dynamic_product_variables_are_set_before_use():
    requests = [item for group in COLLECTION["item"] for item in group["item"]]
    first = requests[0]
    script_text = "\n".join(
        line
        for event in first.get("event", [])
        if event["listen"] == "test"
        for line in event["script"].get("exec", [])
    )
    assert "productId" in script_text
    assert "productName" in script_text
    all_later_urls = "\n".join(item["request"]["url"]["raw"] for item in requests[1:])
    assert "{{productId}}" in all_later_urls
    assert "{{productName}}" in all_later_urls


@pytest.mark.unit
def test_postman_login_is_the_only_post_and_uses_demo_endpoint():
    requests = [item for group in COLLECTION["item"] for item in group["item"]]
    post_requests = [item for item in requests if item["request"]["method"] == "POST"]
    assert len(post_requests) == 1
    assert post_requests[0]["name"] == "13 - Demo customer sign-in"
    assert post_requests[0]["request"]["url"]["raw"] == "{{apiUrl}}/users/login"


@pytest.mark.unit
def test_live_workflow_is_opt_in_and_has_python_matrix():
    workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert "python-version: ['3.11', '3.12', '3.13', '3.14']" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.run_live_smoke" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.run_live_regression" in workflow
    assert "permissions:\n  contents: read" in workflow


@pytest.mark.unit
def test_dashboard_has_saved_project_runner_in_test_groups():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert 'id="project-runner-select"' in dashboard_html
    assert 'id="runner-browser-button"' in dashboard_html
    assert 'id="runner-api-button"' in dashboard_html
    assert "renderProjectRunner(safeProjects)" in dashboard_html
    assert "runTargetCheck(project.id, 'ui', project.name)" in dashboard_html
    assert "runTargetCheck(project.id, 'api', project.name)" in dashboard_html
    assert "The four built-in groups use the included demo shop" in dashboard_html

@pytest.mark.unit
def test_dashboard_navigation_matches_the_main_workflow_order():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    nav = dashboard_html.split('<nav class="nav" aria-label="Dashboard sections">', 1)[1].split("</nav>", 1)[0]
    hrefs = re.findall(r'href="#([a-z0-9-]+)"', nav)
    assert hrefs == ["dashboard-top", "suites", "projects", "url-scan", "analytics", "data-management", "evidence"]
    assert "runbook" not in hrefs
    assert "How to use" not in nav
    assert 'id="runbook"' not in dashboard_html
    assert "How to start" not in dashboard_html
    assert 'class="bottom-grid"' in dashboard_html
    assert ".bottom-grid { display: grid; grid-template-columns: minmax(0, 1fr);" in dashboard_html
    page_positions = [dashboard_html.index(f'id="{section_id}"') for section_id in hrefs]
    assert page_positions == sorted(page_positions)


@pytest.mark.unit
def test_removed_dashboard_tutorial_is_documented_in_readme():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Quick start and daily workflow" in readme
    assert "First launch on Windows" in readme
    assert "Typical workflow for another website" in readme
    assert "docs/START_HERE_RU.md" in readme
    assert "How to use" not in dashboard_html
    assert 'id="runbook"' not in dashboard_html
    assert 'id="evidence"' in dashboard_html


@pytest.mark.unit
def test_dashboard_has_recent_activity_for_saved_project_runs():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert 'id="recent-activity-list"' in dashboard_html
    assert "function renderRecentActivity(projects, projectHistory = {})" in dashboard_html
    assert "renderRecentActivity(data.projects, data.project_history)" in dashboard_html
    assert "data-open-project-history" in dashboard_html


@pytest.mark.unit
def test_project_check_editors_are_collapsible_at_group_and_check_level():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert 'id="browser-checks-manager"' in dashboard_html
    assert 'id="api-checks-manager"' in dashboard_html
    assert '<details class="check-editor-row" data-browser-check' in dashboard_html
    assert '<details class="check-editor-row" data-api-check' in dashboard_html
    assert "updateCheckManagerCounts()" in dashboard_html


@pytest.mark.unit
def test_dashboard_updates_active_navigation_when_scrolling():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert "function updateActiveNavOnScroll()" in dashboard_html
    assert "window.addEventListener('scroll'" in dashboard_html
    assert "window.requestAnimationFrame(() =>" in dashboard_html
    assert "aria-current" in dashboard_html
    assert "a.target.compareDocumentPosition(b.target)" in dashboard_html
    assert "const atPageBottom = maxScroll > 80 && window.scrollY >= maxScroll - 12;" in dashboard_html
    assert "navTargets.at(-1)?.link" in dashboard_html
    assert "window.addEventListener('pageshow', updateActiveNavOnScroll)" in dashboard_html


@pytest.mark.unit
def test_dashboard_readability_overrides_keep_small_ui_text_legible():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert ".project-field label { font-size: 12px; }" in dashboard_html
    assert ".scan-check p { font-size: 11px; }" in dashboard_html
    assert ".analytics-caption { font-size: 10px; }" in dashboard_html



@pytest.mark.unit
def test_project_check_editors_open_only_on_user_action_or_edit():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert '<details class="project-options check-manager" id="browser-checks-manager">' in dashboard_html
    assert '<details class="project-options check-manager" id="api-checks-manager">' in dashboard_html
    assert '<details class="check-editor-row" data-browser-check' in dashboard_html
    assert '<details class="check-editor-row" data-api-check' in dashboard_html
    assert "manager.open = keepManagerOpen" in dashboard_html
    assert "if (options.expandLatest)" in dashboard_html
    assert "firstBrowser.open = true" in dashboard_html


@pytest.mark.unit
def test_recent_activity_opens_matching_project_history():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert 'data-open-project-history="${escapeText(projectId)}"' in dashboard_html
    assert "card?.querySelector('.project-history')" in dashboard_html
    assert "if (history) history.open = true" in dashboard_html


@pytest.mark.unit
def test_active_navigation_is_driven_by_visible_page_sections():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert "const navTargets = navLinks" in dashboard_html
    assert "a.target.compareDocumentPosition(b.target)" in dashboard_html
    assert "const atPageBottom = maxScroll > 80 && window.scrollY >= maxScroll - 12;" in dashboard_html
    assert "const passed = navTargets.filter(({target}) => target.getBoundingClientRect().top <= activationLine);" in dashboard_html
    assert "requestAnimationFrame(() =>" in dashboard_html


@pytest.mark.unit
def test_small_metadata_has_legible_minimum_font_sizes():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert ".analytics-host, .analytics-metric span, .analytics-caption" in dashboard_html
    assert ".run-history-main, .run-history-links, .run-history-summary" in dashboard_html
    assert ".scan-summary-item span, .scan-group > summary span, .scan-meta span" in dashboard_html
    assert ".recent-activity-main small, .recent-activity-duration { font-size:11px; }" in dashboard_html


@pytest.mark.unit
def test_target_run_confirmation_is_protected_from_duplicate_clicks():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    runner = dashboard_html.split("async function runTargetCheck", 1)[1].split("function renderAnalytics", 1)[0]
    assert "let targetRunPending = false" in dashboard_html
    assert "if (busy || targetRunPending) return;" in runner
    assert runner.index("targetRunPending = true;") < runner.index("window.confirm(")
    assert "targetRunPending = false;" in runner
    assert "if (!confirmed)" in runner


@pytest.mark.unit
def test_target_run_confirmation_uses_saved_project_name():
    dashboard_html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    runner = dashboard_html.split("async function runTargetCheck", 1)[1].split("function renderAnalytics", 1)[0]
    assert "savedProjects.find((project) => project.id === projectId)" in runner
    assert "savedProject?.name" in runner
    assert "for ${resolvedProjectName}" in runner
    assert "ShopGuard 1.9.4" in dashboard_html
