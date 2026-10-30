# Test plan — ShopGuard and Toolshop v5

## Objective
Verify ShopGuard's local contracts and dashboard HTTP behaviour, then run a focused set of customer-visible flows and public API checks against the independently hosted Toolshop v5 training environment.

## Scope
- **API:** listing, pagination, product details, search, sorting, categories, brands, authentication/authorization.
- **UI:** landing page, product detail, search, authentication form, invalid credential rejection.
- **Postman:** ordered API assertions that share dynamic product identifiers and the public demo token.
- **Local dashboard:** health/status routes, JSON request validation, allow-listed suite selection, origin guards, request-size limits and timeout reporting.
- **Registered test targets:** local profiles for up to 25 public storefronts, same-host browser smoke checks with configurable path/title/H1/text assertions, and optional GET-only API checks with expected status, content type and typed JSON field assertions. Run history is collapsible per project; the dashboard retains up to 1,000 newest target-run records overall.
- **Website scanner:** public URL allow-list checks, redirect validation, bounded HTML/browser inspection, store-presence markers from HTML and rendered DOM (`data-test`/`data-testid` hooks, product/catalog, price, cart, add-to-cart, checkout/payment and Product/Offer metadata), separate classification of JavaScript exceptions, console errors, HTTP failures, network failures and intentionally blocked requests; actionable finding metadata and coverage reporting.
- **Manual exploration:** cart behavior, form validation, keyboard focus, responsive layout, and intentionally buggy deployment (investigation only until reproduced).

## Registered-target limitations
- Generic target checks are smoke checks only. They do not infer product schemas or store-specific behavior. Website-scan store markers are presence hints only and do not prove that search, product details, cart, checkout or payment workflows function.
- Storefront UI checks do not sign in, click controls, submit forms, change carts or place orders. They assert a successful document response, basic page content and any configured text fragments on the selected path.
- API target checks perform one GET request, do not follow redirects and do not attach credentials. They can compare simple JSON values by dotted object path and zero-based array index; full schemas, authentication and write operations remain out of scope.
- Saved target profiles and up to 1,000 run-history records are local under `reports/` and are intentionally excluded from Git. The dashboard can display every retained run for a saved project.

## Out of scope in default runs
- Real payment processing, security penetration tests, high-volume performance testing, admin writes, changing demo passwords, modifying shared users.
- External database verification: no access is assumed to Toolshop's hosted database; don't claim SQL validation against production.
- Checkout and order placement on the shared public environment (manual review only unless an isolated instance is available).

## Environments
- Baseline UI: `https://practicesoftwaretesting.com`
- Baseline API: `https://api.practicesoftwaretesting.com`
- Intentionally buggy UI: `https://with-bugs.practicesoftwaretesting.com`
- Intentionally buggy API: `https://api-with-bugs.practicesoftwaretesting.com`

Version, server seed, availability and live UI selectors may change independently of these tests.

## Test design techniques
- Equivalence partitions: logged-in versus anonymous user; valid versus invalid credentials.
- Boundary conditions: page parameter and price ordering (more cases should be added when specifications are known).
- State transitions: product catalog -> detail; login form -> account access or rejection.
- Risk-based priority: read-only smoke on every manual environment check, regression after changes, state-changing scenarios only with opt-in.

## Entry criteria
- Python dependencies installed; Playwright Chromium installed for UI; target reachable; baseline test account only if running `auth` tests.

## Exit criteria
- Unit checks pass; no untriaged critical smoke failure; UI/API checks executed and recorded with timestamps; reproducible failures documented with steps and evidence.

## Scanner result interpretation
- `FAIL` is reserved for stronger signals (for example, a main-page HTTP failure or a sampled internal 404/410).
- `WARN` means a possible defect or an environment/network signal that requires verification; it is not proof of a product defect.
- `INFO` includes behavior not tested by the read-only scanner, optional recommendations, and coverage/safety limitations.
- `ERR_BLOCKED_BY_CLIENT`, requests deliberately rejected by ShopGuard, and canceled requests during teardown must not be described as uncaught JavaScript errors or target-site defects.
- Each scan check should provide category, finding type, severity, confidence, impact, and a next step. Confidence describes the scanner's signal, not a guarantee of the product's correctness.

## Failure triage
1. Determine network outage, unexpected test environment, locator change, or behavior regression.
2. Rerun *one* failing test, not the full suite repeatedly.
3. Capture expected vs actual, screenshots/traces, timestamp, target URL, browser version.
4. Reproduce manually and on baseline/buggy deployments where relevant.
5. Create a defect report only when the behavior is sufficiently verified.

## Data policy
Shared public data. Never put personal email, passwords or payment details in test input. The published demo credentials are reused only for educational sign-in checks; do not change their state. No load testing.
