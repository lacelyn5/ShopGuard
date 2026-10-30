# ShopGuard QA Automation

**Version 1.9.4 · Created by Maksim Kernazhytski**

ShopGuard QA Automation is a student project for practising software testing with Python, pytest and Playwright. It checks the public [Practice Software Testing / Toolshop](https://practicesoftwaretesting.com/) demo store, lets you save public test targets on your computer, and can make a short read-only scan of another website. It checks selected API endpoints and opens storefront pages in a browser to collect information about possible problems. It does not contain Toolshop's source code.

## Quick start and daily workflow

This is a learning project, not a commercial security product. The dashboard is intended to run locally on your own computer.

The dashboard intentionally stays focused on testing; setup and usage guidance lives here in the README rather than in a short in-app tutorial panel. For a simple Russian walkthrough, see [docs/START_HERE_RU.md](docs/START_HERE_RU.md). For publishing this project on GitHub, see [docs/GITHUB_PUBLISH_RU.md](docs/GITHUB_PUBLISH_RU.md).

**First launch on Windows**

1. Extract the project to a stable folder such as `C:\ShopGuard-QA-Automation`.
2. Run `scripts\setup_windows.bat` once. It creates `.venv`, installs Python dependencies and installs Chromium for Playwright.
3. Run `scripts\run_dashboard_windows.bat`. Keep its console window open and use the dashboard at `http://127.0.0.1:8765`.
4. Start with **Test groups → Local checks**. Then run the built-in API and Browser smoke groups to confirm the demo integration.

**Typical workflow for another website**

1. Open **Test projects** and add a public website you own or are authorised to test. Configure one or more read-only Browser checks and, if available, API GET checks.
2. Open **Test groups → Run checks for a saved project**, select the saved website and run Browser, API or all configured checks. Each configured check is recorded in that project's Run history.
3. Use **Website scanner** for a one-off read-only page inspection. It is separate from repeatable saved-project assertions and does not submit forms or change site data.
4. Review **Failure details**, logs, JUnit reports and screenshots from the project's history. Use **Analytics** to compare recent runs.
5. Open **Data management → Create backup** before major changes or when you want a copy outside the project folder. Download the ZIP and keep it somewhere safe.

The dashboard sidebar follows this workflow. It no longer contains a simplified “How to use” panel because the full setup, test-selection, scanner, project, evidence and backup instructions are maintained in this README and the Russian guide.

## What ShopGuard checks

| Layer | Tooling | Scope | How to run |
| --- | --- | --- | --- |
| Offline contracts | Python, pytest | Client rules, URL safety, schema validators, Postman distribution and dashboard HTTP routes | `python -m pytest -m unit` |
| REST API | Python, requests, pytest | Catalog, sorting, search, authorization | `python -m pytest -m "api and smoke"` |
| UI | Playwright (Chromium), pytest | Catalog, product details, login page | `python -m pytest -m "ui and smoke"` |
| Website URL check | Python, requests, Playwright Chromium | Page response, HTTPS, title, visible H1, metadata, image alt/loading, search controls, product/catalog and price markers, cart/add-to-cart/checkout controls, browser errors, failed resources and up to 3 same-host links | Enter a URL in the dashboard |
| Postman | Postman / optional Newman | 14 ordered HTTP checks with assertions | Import `postman/` files |
| Stateful (optional) | requests, pytest | Add a product to a fresh test cart | Explicit opt-in; see below |
| Local dashboard | Python stdlib, HTML/CSS/JS | Start baseline suites, configure multiple browser/API checks per target, inspect failures and evidence, review analytics, and back up local data | `scripts/run_dashboard_windows.bat` |

**Important:** Ordinary `pytest` runs only **offline tests**. Live tests are opt-in because this is a public, shared demonstration service. Test outcomes depend on the availability and changes of the external system; treat failures as evidence to investigate, not automatic proof of a product defect.

### Project structure

- `shopguard/` — API client, environment configuration and response-contract assertions.
- `pages/` — small Page Object helpers for repeatable browser actions.
- `tests/api/`, `tests/ui/`, `tests/unit/` — live API checks, live browser checks and deterministic offline checks.
- `dashboard/` — local test-suite runner, local test-target manager, HTTP API and bounded read-only website scanner.
- `tests/targets/` — generic read-only browser and API smoke checks for projects saved in the dashboard.
- `postman/` — importable Postman collection and public demo environment.
- `docs/` — test plan, cases, traceability, defect template and Russian quick-start.
- `.github/workflows/tests.yml` — offline Python matrix on every push/PR, with separately opt-in live checks.

The local dashboard accepts only fixed suite IDs and two fixed generic target-check cases; it does not accept shell commands or arbitrary pytest expressions from the browser. Saved target profiles stay in the ignored local `reports/test_projects.json` file. Its POST API requires JSON and checks loopback Host/Origin values. Target profiles and website scans reject local/private destinations. Generic browser checks use a temporary context and only GET/HEAD requests to the configured storefront host; generic API checks send one GET request without following redirects. This is a safety-conscious personal tool, not a hardened internet-facing service or a full security scanner.

## 1. Install and start

1. Unzip the directory, e.g. `C:\ShopGuard-QA-Automation`.
2. Double-click `scripts/setup_windows.bat` (creates `.venv`, installs packages and Chromium).
3. Double-click `scripts/run_unit_windows.bat` to verify the offline checks.
4. Double-click `scripts/run_api_windows.bat` for a small set of live API checks.
5. Double-click `scripts/run_ui_windows.bat` for small browser checks.
6. Once comfortable, run `scripts/run_regression_windows.bat` (live API and UI, excluding stateful/authenticated checks).

### Open the dashboard

ShopGuard includes a responsive local dashboard for starting the predefined test suites and inspecting the latest output. After setup, double-click `scripts/run_dashboard_windows.bat`. It starts the dashboard at `http://127.0.0.1:8765` and opens the page in your browser. Keep the separate server console open while using it; press `Ctrl+C` in that console to stop the server.

The dashboard runs only on your computer. It includes four fixed baseline Toolshop test groups plus a **Test projects** section where you can save up to 25 public targets. Each project can contain up to 20 named Browser checks and 20 named API GET checks. Browser checks configure a same-host path plus expected title, H1 and visible text. API checks configure a GET path, expected status, optional Content-Type fragment and typed JSON field/value assertions. In **Test groups → Run checks for a saved project**, select any saved target and run its Browser checks, API checks or all configured checks together. Each configured check is collected as a separate pytest case; the dashboard stores the combined run summary in that project's history. These generic target checks use the selected profile; they do not pretend to run Toolshop-specific product, login or checkout tests against another site. Registered-project browser checks remain GET/HEAD-only on the configured storefront host; API checks use GET and do not follow redirects. Expand **Run history** on a project card to see all retained runs, including failures, logs, JUnit reports, JSON evidence and browser screenshots when a check fails. Up to 1,000 of the newest target runs are retained overall across all projects on this computer. Old single-check profiles are migrated automatically into one Browser and, when configured, one API check. The dashboard does not run commands entered in the browser. Local checks work without internet. Online checks require permission to test the target and ask for confirmation. Logs, target profiles, run history, evidence and backups are saved in `reports/` (ignored by Git).

To start the dashboard manually from the project root:

```powershell
.\.venv\Scripts\python.exe dashboard\server.py
```

Then open `http://127.0.0.1:8765`. Stop with `Ctrl+C`.

For manual commands in PowerShell, run from the project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest -m unit -v
.\.venv\Scripts\python.exe -m pytest -m 'api and smoke' -v
.\.venv\Scripts\python.exe -m pytest -m 'ui and smoke' -v
```

Python 3.11 or newer is recommended. Internet is needed for packages, browser installation and live tests.

## Add and test another project

The **Test projects** section is separate from the built-in Toolshop regression suites. Use it to configure repeatable smoke checks against a public website without changing the baseline Toolshop tests.

1. Start the local dashboard and open **Test projects**.
2. Enter a project name and the public storefront URL (for example `https://shop.example.com`).
3. Under **Browser checks**, add one named check per page you want to inspect. Set a same-host relative path such as `/`, `/products` or `/contact`. Optionally configure expected title, visible H1 and required visible text. A project supports up to 20 Browser checks.
4. Optionally enter an API base URL. Under **API checks**, add one named check per read-only GET endpoint, such as `/api/health`, `/products` or `/categories`. Set the expected HTTP status (default `200`), optional Content-Type fragment (for example `application/json`) and JSON field assertions. A project supports up to 20 API checks.
5. JSON assertions use one `path = value` expression per line. Examples:

   ```text
   status = ok
   data.active = true
   meta.total = 3
   data.items[0].id = 42
   data.note = null
   ```

   Use dotted object paths and optional zero-based array indexes. Comparing whole objects or arrays is not supported. Unquoted words are strings; numbers, `true`, `false` and `null` retain their JSON types. Quoted strings are also accepted.
6. Click **Add project**. The profile is stored locally in `reports/test_projects.json`; it is not uploaded to Git. Existing single-check profiles are automatically migrated to one Browser check and, if an API URL exists, one API check.
7. Run checks from the project card or from **Test groups → Run checks for a saved project**. Choose Browser, API or **Run all checks**. Each configured check becomes a separate pytest case. Browser checks can inspect several pages; API checks can inspect several GET endpoints. A combined run is recorded as one history entry with a JUnit report and links to the available evidence.

Browser checks confirm a successful document response, visible body content and a title or visible H1, then verify any configured title/H1/text fragments (case-insensitive). Storefront requests are restricted to GET/HEAD on the configured host. API checks send GET requests, do not follow redirects, check the expected status and optional Content-Type fragment, and validate JSON syntax/field values when configured. Both are read-only: they do not sign in, submit forms, change a cart or place an order. Project-run timeouts scale with the configured check count and are capped at 1,000 seconds.

When a check fails, ShopGuard stores a concise failure summary from JUnit. Browser failures also attempt to save a full-page screenshot and JSON evidence with requested URL, actual URL, status, expected values, actual title/H1 and error. API failures save JSON evidence with the endpoint, expected status/content type/fields, actual status/content type and error. Open **Failure details** or **Screenshot** in Run history. Evidence is stored locally under `reports/` and should be reviewed for sensitive content before sharing.

Each project card has a collapsible **Run history** section with all retained runs for that project, including timestamp, check type, status, duration and a compact pytest summary. **Log** opens the text execution log; **JUnit** opens the XML report; **Failure details** and **Screenshot** open evidence when available. The dashboard stores up to 1,000 target runs in total across all projects in `reports/run_history.json`, so history survives a restart. The physical report files are not automatically removed when the history metadata limit is reached.

**Analytics** shows the latest 30 saved-project runs: pass rate, failed count, average duration, duration trend and the runtime difference between the latest and previous run. Analytics is descriptive; it does not establish why a run became slower or failed.

**Important limitation:** these are configurable smoke assertions, not store-specific end-to-end regression tests. They do not know how a particular store's search, filters, product details, basket or checkout should work. For those workflows, inspect the target's API and UI, then add dedicated pytest/Playwright tests and Page Objects. The four built-in API/UI/regression groups remain tied to the Practice Software Testing baseline and are not silently redirected when a new profile is added. API authentication and write operations are not configurable in the dashboard.

### Back up or restore local data

Open **Data management** in the dashboard. Click **Create backup** to create a ZIP locally (the browser does not download it automatically): ShopGuard stores the ZIP in `reports/backups/` and shows it in the local backup list; use **Download** to save a copy elsewhere. A backup contains saved project profiles, run history, dashboard state and referenced logs, JUnit reports, JSON evidence and screenshots, with SHA-256 integrity checks. Referenced evidence is capped at 15 MB per backup; the backup manifest and dashboard report how many referenced files were omitted if that cap is reached. It excludes `.env`, `.venv`, Python packages and unrelated files. The maximum backup size is 20 MB.

ShopGuard also creates an automatic backup before project additions/updates, deletions and restore operations. It retains the five newest automatic backups. Manual backups are not included in that automatic-retention limit. To restore, select a ShopGuard ZIP under **Restore backup** and confirm. ShopGuard validates the ZIP and all hashes, creates an automatic backup of the current data, and then restores the saved projects, history and included evidence. A malformed or incompatible archive is rejected. Keep a downloaded backup outside the project folder before replacing or deleting the whole project directory.

Profiles, analytics history, backups and evidence remain local to this computer and are excluded from Git via `reports/`. Do not put passwords, API keys or private tokens into project fields or share evidence without reviewing it.

## Check another public website

1. Start the dashboard and open **Check a website**.
2. Enter a public website address and confirm that you own it or have permission to check it.
3. Click **Check website** and wait for the results.
4. Review each `PASS`, `WARN`, `FAIL` and `INFO` item. Check a possible problem in the site before writing a defect report.

ShopGuard checks the initial HTTP response and HTTPS, then opens an eligible HTML page in a fresh temporary Chromium browser. It inspects the rendered page title, visible H1, meta description, image alt attributes, broken images, search-control presence, store-presence markers, uncaught JavaScript exceptions, console errors, failed same-host resources and up to three sampled same-host links. Store markers include stable `data-test` / `data-testid` / `data-cy` / `data-qa` attributes (including the Toolshop UI suite's `[data-test="product-name"]`), product/card selectors, price markers, cart/basket controls, add-to-cart labels, checkout/payment markers and Product/Offer structured metadata. The report includes evidence counts, coverage details plus a category, finding type, severity, confidence, impact and suggested next step for each check. Findings are sorted with failures and warnings first.

Result interpretation matters: `FAIL` is a stronger problem signal such as a confirmed sampled 404/410, `WARN` means a potential issue or an environment/network signal that needs review, and `INFO` can mean a recommendation, an untested behavior or a scanner limitation. An absent `alt` attribute is flagged, while `alt=""` is not automatically considered broken because empty alt text is valid for decorative images. Requests intentionally blocked by ShopGuard's safety rules are not counted as site failures. Browser reports like `ERR_BLOCKED_BY_CLIENT` are separated from uncaught JavaScript exceptions; HTTP status errors, network failures, and client-side blocks are shown differently.

For safety, the Website Check blocks local/private addresses, non-standard ports, unsafe redirects, state-changing browser methods and requests beyond a small limit. In addition to GET/HEAD, it permits bounded HTTP QUERY requests (safe and idempotent under RFC 10008) with a small JSON or form body, plus only the matching page-origin CORS preflight OPTIONS request. This allows read-only SPAs that use QUERY to load content without allowing POST/PUT/PATCH/DELETE. It uses a fresh browser without saved logins or cookies. It does **not** click buttons, sign in, submit forms, change the cart, place orders or test payments. Store feature results are INFO-level presence signals: a product marker is not proof that a product page works, and a cart control is not proof that adding/removing items works. If no markers are found, this does not prove that the site has no store features; they may live on another route, load later or use custom components. A short scan is not proof that the entire website is defect-free; reproduce potential issues before filing a bug.

## 2. Test selection

| Command | Meaning |
| --- | --- |
| `python -m pytest` | Offline contracts only |
| `python -m pytest -m "api and smoke" -v` | Small API check on the demo shop |
| `python -m pytest -m "ui and smoke" -v` | Small browser check on the demo shop |
| `python -m pytest -m "api and auth" -v` | Official public demo sign-in, no profile changes |
| `python -m pytest -m "(api or ui) and not stateful and not auth" -v` | More API and browser checks without cart changes or login tests |
| `python -m pytest -m "api and stateful" -v` | Opt-in, requires flag shown below |

For visible Chromium set `HEADED=true` in your terminal before the UI run (Windows CMD: `set HEADED=true`; PowerShell: `$env:HEADED='true'`). Screenshot `.png` and Playwright trace `.zip` for failed UI tests are saved into `reports/`, excluded by `.gitignore`.

### Tests that change the cart

`tests/api/test_cart_stateful.py` adds data to a new cart on a **shared public demo server**. It is disabled by default. Only run if you understand the effects, at a low rate, with:

```powershell
$env:SHOPGUARD_ALLOW_STATEFUL='I_UNDERSTAND_SHARED_DATA'
.\.venv\Scripts\python.exe -m pytest -m 'api and stateful' -v
```

Avoid registering private data, modifying shared accounts, deleting products or submitting large volumes of orders. CI never runs stateful checks. The baseline test suite performs no writes other than obtaining a demo login token.

## 3. Postman / Newman

Import `postman/ShopGuard.postman_collection.json` and `postman/Toolshop.postman_environment.json` into Postman. Select the environment. Run the **collection in its original order**: products first (sets dynamic product ID/name), then login (sets a demo access token), then current-profile read. All requests have assertions. Postman is an optional GUI dependency; the Python tests run without it.

With Node.js/Newman installed:

```powershell
npm install -g newman
newman run postman/ShopGuard.postman_collection.json -e postman/Toolshop.postman_environment.json
```

The public demo account/password in the environment are published by Toolshop's maintainers, **not private credentials**. If you replace them with private credentials, store those outside this repository.

### Optional enhanced reports

The built-in `--junitxml=reports/results.xml` option writes a machine-readable report. For an HTML report, optionally install `pytest-html` (`.\.venv\Scripts\python.exe -m pip install pytest-html`) and run with `--html=reports/results.html --self-contained-html`. For Allure, optionally install `allure-pytest`, collect with `--alluredir=reports/allure-results`, and open it using a separately installed Allure CLI. These plugins are deliberately not required for normal checks.

## 4. Compare normal and buggy environments

The read-only tool `python scripts/compare_environments.py` fetches product, category and brand summaries from baseline and intentionally buggy APIs, saving `reports/environment-comparison.json`. This produces **investigation leads**, not verified defect reports: both databases can have legitimate differences. Confirm a suspected defect manually using the [defect report template](docs/DEFECT_REPORT_TEMPLATE.md).

To target the buggy shop with live pytest, set both `SHOP_URL=https://with-bugs.practicesoftwaretesting.com` and `API_URL=https://api-with-bugs.practicesoftwaretesting.com` in a local `.env` based on `.env.example`. Do **not** expect the intentionally buggy version to pass all checks. Reset both variables to baseline when comparing.

## 5. CI and results

`.github/workflows/tests.yml` compiles Python sources and runs offline tests on Python 3.11, 3.12, 3.13 and 3.14 for every push/PR. A manual `workflow_dispatch` can optionally execute read-only API/browser smoke tests or the broader read-only regression selection with Chromium. Live results and screenshots/traces (if any) are uploaded as artifacts. Live checks are **not** scheduled to hit the shared public store, and a green offline workflow does not imply the external store is healthy.

The offline suite includes HTTP-level tests for the dashboard routes: status/health responses, JSON validation, unsupported content types, payload limits, unknown suite IDs, busy responses, Host/Origin checks and private URL rejection. Test-runner timeouts are recorded as failed runs rather than leaving the dashboard indefinitely in a running state.

When a browser check cannot run, image loading is reported as **INFO / not verified**, not as a pass. If no eligible same-host links exist, link health is reported as **not assessed**, not as a successful link check. This keeps scan output from overstating its coverage.

See `docs/TEST_PLAN.md` for scope and risk, `docs/TEST_CASES.md` for expected outcomes, and `docs/START_HERE_RU.md` for a Russian hands-on learning sequence. `docs/EXECUTION_LOG.md` starts blank until tests are run: do not mistake designed tests for executed tests.

## Target and attribution

Application under test: [Practice Software Testing (Toolshop)](https://github.com/testsmith-io/practice-software-testing), maintained by testsmith-io. API documentation: https://api.practicesoftwaretesting.com/api/documentation. Our tests are independent and do not redistribute the app. Toolshop's published materials carry their own license; see its repository.

ShopGuard source files are licensed under MIT; see [LICENSE](LICENSE).
