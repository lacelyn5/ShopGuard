# Functional test cases

| ID | Layer | Scenario | Expected result | Automated path |
| --- | --- | --- | --- | --- |
| API-01 | API | GET product list | HTTP 200, pagination object, nonempty products | `test_product_listing_response` |
| API-02 | API | GET categories and brands | HTTP 200, JSON arrays | `test_categories_endpoint`, `test_brands_endpoint` |
| API-03 | API | Fetch dynamically discovered ID | ID matches list item, valid product schema | `test_fetch_existing_product_by_dynamic_id` |
| API-04 | API | Search by existing name | Search includes previously discovered item | `test_product_search_for_existing_name` |
| API-05 | API | Ascending/descending price sort | Prices correctly ordered | `test_price_ascending_sort`, `test_price_descending_sort` |
| API-06 | API | Anonymous account access | HTTP 401 | `test_current_user_requires_auth` |
| API-07 | API | Anonymous admin report | HTTP 401 | `test_admin_only_report_denies_anonymous` |
| API-08 | API | Sign in official demo user | 200 access token and profile email matches | `test_demo_customer_login_and_read_profile` |
| UI-01 | UI | Home page | Product cards visible | `test_homepage_loads_with_products` |
| UI-02 | UI | Product detail | Navigation to product route, visible name | `test_product_detail_opens` |
| UI-03 | UI | Search known product | Search results contain known product | `test_search_for_present_product` |
| UI-04 | UI | Search unlikely phrase | No matching product cards | `test_search_for_unlikely_text_shows_no_matches` |
| UI-05 | UI | Login form | Email/password/button visible | `test_login_page_fields_visible` |
| UI-06 | UI | Invalid login | User remains unauthenticated and a visible rejection message appears | `test_login_with_invalid_credentials_is_rejected` |
| API-09 | API | Create isolated cart and add product | New cart can be retrieved; add-item request accepted | `test_new_cart_can_hold_one_demo_product` (opt-in only) |
| DASH-01 | Dashboard HTTP | Health, dashboard page and status | 200 responses, expected content and security headers | `test_health_and_dashboard_return_security_headers`, `test_status_endpoint_exposes_fixed_test_groups_only` |
| DASH-02 | Dashboard HTTP | Invalid JSON, wrong content type, large payload or field type | Request rejected with a useful 4xx response | `test_post_requires_json_content_type`, `test_post_rejects_invalid_json_and_non_object_payloads`, `test_post_rejects_oversized_body`, `test_post_rejects_wrong_field_types` |
| DASH-03 | Dashboard HTTP | Unknown suite and concurrent request | Unknown suite rejected; active-run conflict maps to HTTP 409 | `test_run_route_returns_runner_rejection_for_unknown_suite`, `test_run_route_maps_busy_state_to_http_409` |
| DASH-04 | Dashboard HTTP | Cross-origin Host/Origin request | Request rejected before a suite can start | `test_post_rejects_foreign_origin_and_host` |
| DASH-05 | Dashboard HTTP | Request to scan a loopback URL | Rejected before network scan begins | `test_scan_route_rejects_loopback_before_starting_scan` |
| DASH-06 | Dashboard runner | Suite exceeds time limit | Run is recorded as failed with diagnostic text | `test_timed_out_suite_is_recorded_as_failed_with_diagnostic` |
| TARGET-01 | Target profiles | Add, edit and delete a custom test project | Profile is saved locally and can be updated/removed; built-in example is protected | `test_create_update_and_delete_custom_project`, `test_builtin_project_cannot_be_deleted` |
| TARGET-02 | Target profiles | Configure an API endpoint with an unsafe path or status | Invalid absolute/traversal paths and status values are rejected | `test_project_api_path_rejects_absolute_and_traversal_paths`, `test_project_payload_requires_storefront_and_valid_api_status` |
| TARGET-03 | Browser smoke | Open a saved public storefront | Temporary browser receives a successful document and finds basic page content; same-host GET/HEAD only; state-changing methods are blocked | `test_registered_project_storefront`, `test_browser_target_guard_allows_only_public_same_host_get_or_head` |
| TARGET-04 | API smoke | GET a configured API path | Expected HTTP status is checked; JSON syntax is checked when response declares JSON; redirects are not followed | `test_registered_project_api_endpoint`, `tests/unit/test_registered_targets.py` |
| TARGET-05 | Browser assertions | Configure a browser path, expected title, H1 or visible text | Path stays on the configured host; configured text fragments must appear case-insensitively | `test_registered_project_storefront`, `test_browser_path_must_be_relative_and_same_host_friendly` |
| TARGET-06 | API assertions | Configure expected content type and JSON fields | Content type contains the configured fragment; dotted fields exist and match typed expected values | `test_api_check_verifies_configured_json_fields_and_expected_content_type`, `test_api_check_fails_when_configured_json_value_does_not_match`, `test_api_check_fails_when_required_json_field_is_missing` |
| TARGET-07 | Run history and artifacts | Complete repeated checks for a saved target | History is stored locally, capped at 1,000 total, exposes every retained run per project and only serves artifacts recorded under `reports/` | `test_run_history_keeps_records_per_target_and_limits_history`, `test_run_history_retains_newest_1000_records_overall`, `test_run_artifact_only_serves_recorded_files_inside_reports` |
| SCAN-01 | Website scan | Browser scan unavailable while HTML contains images | Image loading is marked not verified, not PASS | `test_browser_failure_keeps_basic_html_results` |
| SCAN-02 | Website scan | No eligible same-host links | Link health is marked INFO / not assessed | `test_no_same_host_links_are_reported_as_not_assessed` |
| SCAN-03 | Website scan | Distinguish missing alt from empty decorative alt | Missing `alt` is a potential accessibility issue; `alt=""` is recorded as an informational case | `test_page_inspector_distinguishes_missing_alt_from_empty_decorative_alt` |
| SCAN-04 | Website scan | Browser reports `ERR_BLOCKED_BY_CLIENT` | Classified as an environment/client-blocking signal, not as an uncaught JS exception | `test_blocked_by_client_is_information_not_a_javascript_defect` |
| SCAN-05 | Website scan | Browser logs an application console error | Console diagnostics are separate from uncaught JavaScript exceptions and include a reproduction step | `test_console_errors_are_separate_from_uncaught_javascript_exceptions` |
| SCAN-06 | Website scan | Scan a successful non-HTML URL | HTML-specific checks are not applicable; response is not labelled a site failure solely for being JSON | `test_scan_marks_non_html_as_not_applicable_not_site_failure` |
| SCAN-07 | Website scan | Report missing image alt attribute | Finding contains type, severity, confidence, impact and a suggested next step | `test_scan_results_include_actionable_metadata` |
| SCAN-08 | Website scan | A same-host resource returns HTTP 404 | Reported as a potential issue with a follow-up action rather than a generic browser/network warning | `test_http_resource_404_is_a_potential_issue_with_recommended_follow_up` |
| SCAN-09 | Website scan | Missing meta description | Shown as a low-severity SEO recommendation, not a functional bug | `test_missing_meta_description_is_recommendation_not_a_functional_bug` |
| SCAN-10 | Website scan | Rendered storefront exposes stable product/price/cart test hooks and controls | Store markers are reported as INFO with marker counts; no control is activated | `test_page_inspector_detects_toolshop_data_test_markers_and_commerce_controls`, `test_dynamic_product_wait_uses_stable_toolshop_markers`, `test_dynamic_product_wait_treats_timeout_as_no_observed_marker`, `test_scan_reports_page_checks_without_network` |
| SCAN-11 | Website scan | Ordinary page uses a `productivity` class but no commerce markers | The scanner does not classify the class name as a product/catalog marker | `test_page_inspector_does_not_treat_productivity_class_as_a_store` |

**Manual investigations still to be performed:**

- M-01: Empty search string; expected list behavior according to current specification.
- M-02: Keyboard-only navigation and visible focus on login and catalog controls.
- M-03: Responsive layout at 375 × 812 and 768 × 1024 viewport.
- M-04: Product price/cart quantity consistency after editing quantity in a throwaway session.
- M-05: Invalid form messages have clear text and labels.
- M-06: Baseline versus buggy storefront: repeat exact steps under the same conditions.

These entries are **test definitions, not claims that the website passed**.
