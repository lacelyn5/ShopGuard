# Requirements traceability

## Toolshop application under test

| Requirement | Evidence in code | Manual follow-up |
| --- | --- | --- |
| Catalog shows products | `tests/api/test_catalog.py` + `tests/ui/test_storefront.py` | Confirm pricing and product cards visually |
| Search returns matching product | API name search; UI search test | Inspect partial/empty phrases |
| Product detail is reachable | Dynamic API lookup and UI click | Verify image, description, price |
| Anonymous cannot access profile | `test_current_user_requires_auth` | Verify UI redirect behavior |
| Demo customer can authenticate | `test_demo_customer_login_and_read_profile` | Check logout/session behavior |
| Anonymous cannot fetch admin reports | `test_admin_only_report_denies_anonymous` | Review permission edge cases |
| Invalid login is rejected visibly | `test_login_with_invalid_credentials_is_rejected` | Confirm exact message against current target version |
| Test reports are reproducible | JUnit XML, trace and screenshot hooks | Add run date and evidence to execution log |
| Buggy environment discrepancies are investigated | `scripts/compare_environments.py` | Confirm by reproduction and specification before reporting |

## Registered test targets

| Requirement | Evidence in code | Manual follow-up |
| --- | --- | --- |
| Save, edit and delete local public target profiles | `tests/unit/test_dashboard_http.py::test_create_update_and_delete_custom_project`, `test_builtin_project_cannot_be_deleted` | Add a real target through the dashboard and restart it to confirm local persistence |
| Reject unsafe API paths and malformed expected statuses | `tests/unit/test_dashboard.py::test_project_api_path_rejects_absolute_and_traversal_paths`, `test_project_payload_requires_storefront_and_valid_api_status` | Try valid target configuration for an authorised public test site |
| Run a generic, read-only storefront browser smoke check | `tests/targets/test_registered_project.py::test_registered_project_storefront`, `tests/unit/test_registered_targets.py::test_browser_target_guard_allows_only_public_same_host_get_or_head` | Run against a public target and inspect browser evidence |
| Run a generic API GET endpoint check | `tests/targets/test_registered_project.py::test_registered_project_api_endpoint`, `tests/unit/test_registered_targets.py` | Configure a documented read-only endpoint and confirm expected status |
| Apply browser title, H1 and visible-text assertions on an optional same-host path | `tests/targets/test_registered_project.py::test_registered_project_storefront`, `tests/unit/test_dashboard.py::test_project_validator_saves_browser_and_api_assertions` | Configure a known page and verify one expected fragment plus one intentionally incorrect fragment |
| Apply API Content-Type and typed JSON field assertions | `tests/targets/test_registered_project.py`, `tests/unit/test_registered_targets.py` | Configure a documented JSON endpoint, then deliberately mismatch one value to observe a failed assertion |
| Keep per-project run history and serve only recorded local reports | `tests/unit/test_dashboard.py::test_run_history_keeps_records_per_target_and_limits_history`, `tests/unit/test_dashboard_http.py::test_artifact_route_serves_only_a_registered_local_run_file` | Run a project twice, restart the dashboard and confirm history and report links remain |
| Keep target-specific runs on fixed pytest node IDs with no shell execution | `tests/unit/test_dashboard.py::test_registered_target_runner_uses_fixed_pytest_case_and_env` | Run one browser and one API check from the dashboard |

## ShopGuard dashboard and scanner

| Requirement | Evidence in code | Manual follow-up |
| --- | --- | --- |
| Dashboard health and status API | `tests/unit/test_dashboard_http.py` | Run dashboard locally and confirm UI refresh behaviour |
| Dashboard rejects malformed requests | `test_post_requires_json_content_type`, `test_post_rejects_invalid_json_and_non_object_payloads`, `test_post_rejects_oversized_body`, `test_post_rejects_wrong_field_types` | Try manual malformed requests only on the local instance |
| Only fixed test groups can be started | `tests/unit/test_dashboard.py`, `test_run_route_returns_runner_rejection_for_unknown_suite` | Confirm the dashboard UI only offers documented groups |
| Dashboard local-origin request guard | `test_post_rejects_foreign_origin_and_host` | Verify dashboard works through `127.0.0.1` and `localhost` |
| Runner does not remain stuck after timeout | `test_timed_out_suite_is_recorded_as_failed_with_diagnostic` | Start a representative test group and inspect run status |
| Persisted log paths cannot read files outside reports | `test_tail_never_reads_outside_reports_directory` | Keep generated reports local and excluded from Git |
| Website scan blocks private targets and unsafe redirects | `tests/unit/test_url_scanner.py` | Use only websites you own or have permission to check |
| Scanner does not overstate unverified checks | `test_browser_failure_keeps_basic_html_results`, `test_no_same_host_links_are_reported_as_not_assessed`, `test_scan_marks_non_html_as_not_applicable_not_site_failure` | Review actual scan output and manually confirm warnings |
| Missing vs empty image alt is distinguished | `test_page_inspector_distinguishes_missing_alt_from_empty_decorative_alt` | Confirm whether affected images are informative or decorative |
| Browser/client blocks are not reported as JavaScript defects | `test_blocked_by_client_is_information_not_a_javascript_defect`, `test_console_errors_are_separate_from_uncaught_javascript_exceptions` | Reproduce a blocked request in a normal browser before raising a defect |
| Scan findings include actionable guidance | `test_scan_results_include_actionable_metadata`, `test_http_resource_404_is_a_potential_issue_with_recommended_follow_up`, `test_missing_meta_description_is_recommendation_not_a_functional_bug` | Confirm finding, severity and impact before creating a defect report |
| Storefront feature markers include stable test hooks, product/catalog, price, cart, add-to-cart and checkout indicators | `test_page_inspector_detects_toolshop_data_test_markers_and_commerce_controls`, `test_scan_reports_page_checks_without_network` | Run a real authorised storefront scan and confirm markers appear as INFO only; no controls should be activated |
| Productivity/article class names do not automatically identify a shop | `test_page_inspector_does_not_treat_productivity_class_as_a_store` | Review any unusual custom component names that may still require a site-specific detector |

A test mapping shows which code verifies each requirement; it is not a statement that all live tests have been executed against the external service.
