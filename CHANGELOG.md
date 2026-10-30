# Changelog

## 1.9.4 - 2026-10-30

### Fixes
- Prevented duplicate confirmation dialogs and duplicate target-run requests by locking the run action before the confirmation window opens. Cancelling releases the lock; an accepted run stays locked while the dashboard reports it as active.
- The confirmation now resolves the saved project's actual name by its ID, so the built-in project is shown as “Practice Software Testing” instead of the generic word “project”.

### Validation
- Added offline regression checks for the confirmation lock, cancel/reset path and saved-project name resolution.
- No project data format, report format, backup format or server API was changed.


## 1.9.3 - 2026-10-30

### User experience
- Removed the in-dashboard “How to use / How to start” navigation item and short four-step card. Full setup and daily workflow guidance now lives in README.md, with a link to the detailed Russian guide.
- Removed the empty second column left beside Test log; the log panel now spans the available content width.
- Fixed scroll-aware sidebar state at the bottom of the page. Navigation targets are ordered by their actual DOM position, the active section is recomputed without prematurely stopping at a later target, and the final visible section is selected when the page reaches its bottom.
- Re-evaluates active navigation after hash changes, browser page restoration and viewport resizing.

### Compatibility
- No project schema, reports, run-history, backup format, API route or test execution behavior changed.

### Validation
- Added regression tests for the removed help panel, README quick-start guidance, full-width Test log and bottom-aware navigation selection.

## 1.9.2 - 2026-10-30

### User experience
- Reordered the dashboard into a clearer workflow and aligned sidebar navigation with the page sections.
- Added a dashboard Recent activity panel with direct links that expand the corresponding saved project's run history.
- Made Browser/API groups and each individual check collapsible; the newest check expands after it is added, while existing values remain in the form when sections are collapsed.
- Added visible counts and compact summaries for configured checks.
- Improved small metadata text, form labels, and keyboard focus visibility while retaining the existing color palette.
- Added scroll-aware active navigation and responsive spacing for mobile layouts.

### Compatibility
- No server routes, project schemas, run-history formats, reports, backup formats, or test execution behavior changed.
- Existing `reports/` data and saved projects remain compatible.

### Validation
- Added static UI regression tests for navigation order, recent-activity history links, collapsible editors, scroll-aware navigation, and readable metadata sizes.

## 1.9.1 - 2026-10-30

### User experience
- Reordered the sidebar and page sections into the same task flow: dashboard, test groups, projects, website scanner, analytics, data management and evidence/help.
- Added scroll-aware active navigation with keyboard focus styling and a mobile-friendly anchor offset.
- Added a dashboard Recent activity panel for the six latest saved-project runs, with direct links that open the matching project history.
- Made Browser/API check groups and individual check editors collapsible; summaries show check names, paths and configured counts.
- Increased the readability of small labels, descriptions, badges and form controls without changing the established color palette.
- Kept project data, run-history formats, test execution and backup APIs unchanged.

### Validation
- Added static UI regression checks for section order, recent activity, scroll-aware navigation, collapsible editors and readability rules.
- Existing project, backup, analytics, scanner and test-runner behavior remains covered by the existing unit suite.

## 1.9.0 - 2026-10-30
- Added local ZIP Backup & Restore under Data management. Backups include saved profiles, project run history, dashboard state and referenced logs/JUnit/JSON evidence/screenshots; the 15 MB evidence cap and any omitted artifact count are recorded in the manifest and shown in the UI. SHA-256 hashes and ZIP paths are validated before restore. `.env`, `.venv` and unrelated files are excluded; backups are capped at 20 MB. Five newest automatic backups are retained, created before project mutations and restore.
- Expanded each project to support up to 20 named Browser checks and 20 named API GET checks, with legacy profile migration and a Run all action in project cards and Test groups.
- Added bounded failure diagnostics from JUnit. Browser failures save JSON evidence and attempt a full-page screenshot; API failures save expected/actual status, content type, endpoint and assertion context. Artifacts are available from per-project run history and are confined to `reports/`.
- Added project analytics for the latest 30 runs: success rate, failed count, average duration, run-duration trend and latest-versus-previous duration comparison.
- Scaled registered-project runner timeout to the number and type of configured checks, capped at 1,000 seconds.
- Added offline coverage for backup round-trip/restore security, multi-check profiles and dispatch, API/Browser failure evidence, analytics, HTTP backup routes and timeout calculations.

## 1.8.7 - 2026-10-30
- Added a saved-project selector directly inside Test groups. Users can choose any of their locally saved public targets and run its configured Browser smoke or API smoke check without navigating to the Test projects cards.
- The selector refreshes when projects are added, edited or deleted; a newly added project becomes the current selection. API execution is disabled when the selected profile has no API URL.
- Kept the four built-in Toolshop pytest suites separate and explicitly labelled: their product, login and catalog scenarios are not incorrectly reused against arbitrary sites. Selected-project checks use the existing fixed, read-only target test cases and each project's saved assertions.
- Added offline coverage for the new selector wiring and the selected-target runner HTTP route.

## 1.8.6 - 2026-10-30
- Clarified Website Check request coverage: attempted, allowed and blocked requests are reported separately, so blocked attempts do not make an allowed-request cap look exceeded.
- Reduced false-positive broken-image warnings: only observed image HTTP/network request failures are classified as warnings; images still loading or not verifiable at the snapshot are reported as INFO.
- Added unit coverage for unverified images, confirmed image failures and request-count presentation data.

## 1.8.5 - 2026-10-30
- Fixed Website Check missing Toolshop's dynamically loaded catalog: the Angular frontend uses the standardized HTTP QUERY method with a JSON request body to retrieve products, brands, categories and related data.
- Allowed bounded, public QUERY requests only when they originate from the scanned page; added a narrowly validated OPTIONS preflight for QUERY CORS. POST/PUT/PATCH/DELETE and general OPTIONS remain blocked.
- Added unit and Playwright-route integration coverage for allowed QUERY/preflight requests, missing/wrong origin, oversized bodies and blocked state-changing methods.
- Clarified documentation so generic saved-project browser smoke checks (GET/HEAD) are not confused with Website Check's safe QUERY support.

## 1.8.4 — Wire the dynamic product wait into the live scan

- Fixed a regression in 1.8.3: the bounded wait helper for asynchronously rendered product markers was defined and unit-tested but was not called by `_scan_in_browser`, so the live Website Check still inspected the DOM too early.
- The real browser scan now invokes the 5-second, read-only wait after the initial settle period and before collecting rendered DOM evidence.
- Added an integration-style offline test with a mocked Playwright page to ensure the browser scan actually calls the wait helper and returns its store evidence.
- Kept ordinary pages valid when no product marker appears; timeout remains a coverage limitation, not a site failure.

## 1.8.3 — Wait for asynchronously rendered product markers

- Fixed a timing gap in Website Check: the scanner previously inspected the rendered DOM only 900 ms after `DOMContentLoaded`, while the Toolshop UI suite explicitly waits for product cards to become visible.
- Added a bounded, read-only wait of up to 5 seconds for visible product/catalog markers such as `[data-test="product-name"]` before collecting DOM evidence.
- Ordinary/non-commerce pages continue after the timeout; the scanner does not click controls, submit forms or change state.
- Added offline tests for the product-marker wait and its timeout behavior.

## 1.8.2 — Stronger store-feature recognition

- Expanded read-only store-presence detection across HTML and the rendered browser DOM.
- Recognises stable test hooks including `data-test="product-name"` (already used by ShopGuard's Toolshop UI tests), product/card markers, price attributes, cart/basket controls, add-to-cart labels, checkout/payment markers and Product/Offer structured metadata.
- Reports each detected category with marker counts while keeping the result at INFO: presence does not prove that the workflow works, and the scanner still does not click controls or change site data.
- Reworded the no-signal result so it no longer implies that the website has no store features; it explains that markers may be on other routes, load later or use unsupported custom components.
- Added offline regression tests for Toolshop-style data-test attributes, cart/price/checkout markers, report evidence and protection against a `productivity` false positive.

## 1.8.1 — Navigation, collapsible results and expanded history

- Made the desktop sidebar sticky and added a compact sticky horizontal navigation on smaller screens.
- Grouped website-scan findings into collapsible Failed, Warnings, Info and Passed sections; warnings and failures open first for faster triage.
- Made each project's run history collapsible and available in full instead of showing only the latest eight entries.
- Increased local run-history metadata retention from 200 to 1,000 newest runs overall across all projects; existing history files are read and retained on upgrade.
- Clarified the project form actions: **Add project** creates a separate card, **Update project** edits the selected card, and **Reset form / Cancel edit** clears the form state.
- Added tests for full per-project history exposure and the 1,000-run retention limit.

## 1.8.0 — Per-project history and configurable checks

- Added persistent per-project run history (latest 8 shown per project, 200 retained locally) with status, timing, pytest summary and direct log/JUnit links.
- Added configurable browser path, expected page-title fragment, visible H1 fragment and required visible page text.
- Added configurable API content-type fragment and up to 20 typed JSON field/value assertions using dotted object paths and zero-based array indexes.
- Kept target checks read-only: same-host browser GET/HEAD and API GET only; no credentials, form submissions or write operations.
- Added input validation and offline tests for assertion values, dotted JSON paths, browser-path safety, history retention and report-path confinement.
- Updated README and Russian quick-start instructions with profile examples and local-history behavior.

## 1.7.0 — Register and smoke-test multiple projects

- Added a dashboard section to save, edit and delete up to 25 public storefront profiles with optional API endpoints.
- Added generic read-only Playwright browser checks and bounded GET-only API checks for each saved profile.
- Kept existing Toolshop-specific regression groups unchanged; custom targets are clearly described as generic smoke checks.
- Added offline HTTP integration and security tests for project profile management and target execution.
- Expanded the CI Python matrix to 3.14 and updated documentation.

## 1.6.0 — Multiple saved test targets

- Added a local Test projects area to save, edit and remove up to 25 public storefront/API profiles without changing the built-in Toolshop baseline suites.
- Added a generic read-only Playwright storefront smoke check for each saved target, with same-host GET/HEAD request routing and basic page-content assertions.
- Added a configurable GET-only API endpoint smoke check with an expected HTTP status and JSON syntax validation when applicable.
- Added local profile persistence under the ignored `reports/test_projects.json`; no credentials or arbitrary commands are stored or accepted.
- Added loopback-protected dashboard routes for listing, saving, deleting and running registered targets, plus offline HTTP integration tests.
- Documented the boundary between generic smoke checks and store-specific API/UI regression tests.

## 1.5.0 — More accurate website scan findings

- Added structured scan metadata: category, finding type, severity, confidence, impact and recommended next step.
- Prioritized failures and warnings in the scan report and added explicit coverage indicators for browser inspection, sampled links, browser request count and HTML truncation.
- Separated uncaught JavaScript exceptions from console errors, HTTP resource failures, network request failures and client-side blocked resources.
- Excluded requests intentionally blocked by ShopGuard safety policy from target-site failure findings; cancelled requests during navigation/teardown are ignored.
- Treated non-HTML URLs as out of scope for page structure checks instead of flagging them as a site failure by themselves.
- Distinguished missing image alt attributes from empty alt attributes, which can be valid for decorative images.
- Reclassified missing meta descriptions as low-severity SEO recommendations and added actionable guidance for common findings.
- Added offline regression tests for classification, recommendations, non-HTML response handling and structured scan metadata.

## 1.4.0 — Portfolio hardening and stronger validation

- Added HTTP-level integration tests for dashboard health/status/routes, JSON validation, content-type checks, payload limits, allow-listed suite handling, busy responses and private URL rejection.
- Added loopback Host/Origin validation for dashboard POST routes and security headers for the local UI/API.
- Added explicit time limits for dashboard test-suite runs; timeouts are recorded as failed runs with a diagnostic instead of leaving a run stuck.
- Restricted persisted log-tail reads to `.log` files under the reports directory.
- Strengthened invalid-login UI coverage to require a visible rejection message, not only a login-route URL assertion.
- Corrected scanner output so image loading is not marked as passed when the browser check did not run, and link health is not marked passed when no eligible links were found.
- Expanded CI to Python 3.11–3.13 and updated GitHub Actions to Node.js 24-compatible major versions. Live smoke and regression runs remain manually opt-in.
- Updated test cases, traceability and README to describe dashboard-level coverage and current scanner limitations accurately.

## 1.3.0 — Browser checks and simpler dashboard text

- Added a short Playwright/Chromium check for the page as it appears after JavaScript runs.
- Added checks for visible H1 headings, rendered page metadata, image alt text, images that fail to load, search fields, JavaScript errors and failed same-site resources.
- Added a request limit and browser checks that block private/local destinations, non-GET requests and cross-site main-page redirects. The browser uses a fresh context without saved login data.
- Changed the image check to INFO when the page has no images, instead of treating it as a successful accessibility check.
- Simplified labels and instructions in the dashboard and added author credit for Maksim Kernazhytski.
- Added offline tests for browser-result handling and request filtering.

## 1.2.0 — Public website URL Quick Scan

- Added a dashboard form to scan a public website by URL without changing site data.
- Added bounded checks for HTTP response, HTTPS, page title, H1, meta description, image alt text, up to three same-host links, and basic e-commerce signals.
- Added URL safety checks for local/private/reserved IPs, non-HTTP(S) schemes, credentials, non-standard ports and unsafe redirects.
- Added a consent checkbox and confirmation before scanning a site.
- Added offline unit tests for URL validation, HTML inspection and scan reporting.
- Documented that the original URL scanner only checked the returned HTML; v1.3 adds a short browser check but still does not sign in, click buttons, change carts, check out or test payments.

## 1.1.0 — Local dashboard and runner hardening

- Added a responsive local ShopGuard dashboard with test-suite cards, current-run metrics, live log output and a Windows quick-start panel.
- Added a loopback-only Python dashboard server with a fixed allow-list of four pytest suites; browser requests cannot supply arbitrary shell commands or pytest selectors.
- Added JUnit XML summary parsing and persistent latest-run status under the ignored `reports/` directory.
- Added a Windows launcher for the dashboard and Russian quick-start instructions.
- Added offline tests for the dashboard runner and JUnit summary parser.
- Updated CI syntax compilation to include the dashboard package.

## 1.0.0 — Initial QA automation suite

- Added pytest-based offline contracts, live API checks and Playwright browser checks for the public Practice Software Testing Toolshop.
- Added Postman collection/environment, test plan, test cases, defect report template and GitHub Actions workflow.
