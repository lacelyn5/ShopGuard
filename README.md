ShopGuard QA Automation
Version 1.9.4 · Created by Maksim Kernazhytski
ShopGuard is a student QA automation project built with Python, pytest, Playwright and requests. I created it to practise software testing and build a practical framework for checking web applications.
The project focuses on the public Practice Software Testing / Toolshop demo store. It includes API and browser tests, a local dashboard for running checks, configurable read-only checks for other public websites, test reports and local backups.
ShopGuard does not contain Toolshop's source code. It is a testing tool, not a commercial security product or a full security scanner.
Features
API testing — checks selected REST API endpoints, response status codes, data and authorization behaviour.
UI testing — uses Playwright and Chromium to check storefront pages and selected user-interface elements.
Offline tests — validates local application logic, URL safety, schemas, dashboard routes and other contracts without relying on the demo store.
Local dashboard — runs predefined test groups, manages saved website targets and displays test history and evidence.
Read-only website scanner — performs a bounded inspection of a public website without logging in, submitting forms or changing data.
Postman collection — includes 14 ordered HTTP requests with assertions.
Reports and backups — keeps logs, JUnit reports, screenshots, evidence, saved project profiles and backups on the local computer.
Quick start (Windows)
Requirements: Python 3.11 or newer and an internet connection for installing dependencies, downloading Chromium and running live tests.
Extract the project to a stable folder, for example `C:\\ShopGuard-QA-Automation`.
Run `scripts\\setup\_windows.bat`. It creates a virtual environment, installs Python dependencies and installs Chromium for Playwright.
Run `scripts\\run\_dashboard\_windows.bat`.
Keep the server console open and open http://127.0.0.1:8765 in your browser.
Start with Test groups → Local checks. Then try the built-in API and Browser smoke groups to check the demo integration.
To run the offline tests without opening the dashboard:
```powershell
.\\.venv\\Scripts\\python.exe -m pytest -m unit -v
```
For a simple Russian walkthrough, see `docs/START\_HERE\_RU.md`.
What can be tested?
Test layer	Tools	Scope	Run
Offline checks	Python, pytest	Local rules, validators, dashboard routes and URL-safety checks	`python -m pytest -m unit`
REST API	requests, pytest	Selected catalog, search, sorting and authorization endpoints	`python -m pytest -m "api and smoke" -v`
Browser UI	Playwright, pytest	Catalog, product details and login page	`python -m pytest -m "ui and smoke" -v`
Website scanner	requests, Playwright	Bounded, read-only inspection of a public page	Enter a URL in the dashboard
Postman	Postman / optional Newman	14 ordered HTTP requests with assertions	Import files from `postman/`
Ordinary `pytest` runs the offline suite only. Live checks are opt-in because the demo store is a shared public service and can change or become unavailable. A failed live check should be investigated; it is not automatically proof of a defect in the application.
Dashboard
The dashboard runs locally at `http://127.0.0.1:8765`. It provides:
predefined Toolshop test groups;
saved public website targets with configurable Browser checks and API GET checks;
run history, logs, JUnit reports, JSON evidence and browser screenshots when available;
analytics for recent saved-project runs;
local data backup and restore.
A saved target can have up to 20 Browser checks and 20 API checks. Browser checks use GET/HEAD requests on the configured host. API checks use GET requests and do not follow redirects. These configurable checks are smoke assertions; they are not automatically full end-to-end tests for another store.
The dashboard does not execute shell commands entered in the browser. Saved target profiles, run history, reports and evidence stay in the local `reports/` directory, which is excluded from Git.
For detailed setup and usage instructions, see the project documentation in `docs/`.
Website scanner and safety
The scanner is intended for public websites that I own or am authorised to test. It checks a limited set of signals, such as the page response, HTTPS, title, visible H1, metadata, image attributes, selected store-related markers, browser errors and a small number of same-host links.
The scanner is deliberately limited:
it blocks local/private destinations and unsafe redirects;
it uses a fresh browser without saved logins or cookies;
it does not sign in, submit forms, change a cart, place orders or test payments;
it uses bounded read-only requests and a small sample of links;
it reports potential issues that need manual review.
A short scan cannot prove that a whole website is defect-free. Store-related markers indicate that an element appears to be present; they do not prove that the feature works.
Running live tests
Run these commands from the project root after setup:
```powershell
# Small API smoke suite
.\\.venv\\Scripts\\python.exe -m pytest -m "api and smoke" -v

# Small browser smoke suite
.\\.venv\\Scripts\\python.exe -m pytest -m "ui and smoke" -v

# API and UI checks, excluding stateful and authenticated tests
.\\.venv\\Scripts\\python.exe -m pytest -m "(api or ui) and not stateful and not auth" -v
```
The stateful cart test is disabled by default because it changes data on a shared demo service. Run it only if you understand the effect and explicitly opt in:
```powershell
$env:SHOPGUARD\_ALLOW\_STATEFUL='I\_UNDERSTAND\_SHARED\_DATA'
.\\.venv\\Scripts\\python.exe -m pytest -m 'api and stateful' -v
```
Avoid modifying shared accounts, registering private data or sending large volumes of requests. CI does not run stateful checks.
Postman
Import these files into Postman:
`postman/ShopGuard.postman\_collection.json`
`postman/Toolshop.postman\_environment.json`
Select the Toolshop environment and run the collection in its original order. The collection contains assertions and uses the public demo account published by the Toolshop maintainers.
Newman is optional. If Node.js and Newman are installed:
```bash
newman run postman/ShopGuard.postman\_collection.json -e postman/Toolshop.postman\_environment.json
```
Do not replace public demo values with private credentials in committed files. Keep private credentials outside the repository.
CI and test results
GitHub Actions runs the offline checks on every push and pull request using Python 3.11, 3.12, 3.13 and 3.14. The workflow compiles Python sources and runs the unit-marked test suite.
Optional live API and browser smoke tests, or the broader read-only regression selection, can be started manually through `workflow\_dispatch`. Live checks are not scheduled against the shared demo store. When applicable, reports and browser evidence are uploaded as workflow artifacts.
A green offline workflow confirms that the offline checks passed in CI. It does not mean that the external demo store is always available or defect-free.
See the GitHub Actions workflow for the CI configuration.
Project structure
```text
shopguard/                 API client, configuration and response assertions
pages/                     Page Object helpers
tests/api/                 Live API tests
tests/ui/                  Live browser tests
tests/unit/                Offline tests
tests/targets/             Generic read-only target checks
dashboard/                 Local dashboard and website scanner
postman/                   Postman collection and environment
docs/                      Test plan, test cases and guides
scripts/                   Windows setup and run scripts
.github/workflows/         GitHub Actions CI workflow
```
Limitations
The built-in API and UI suites are designed around the Practice Software Testing / Toolshop demo environment.
Generic saved-target checks are configurable smoke checks, not store-specific regression coverage.
Dashboard API checks support GET requests only; API authentication and write operations are not configurable there.
Scanner results are limited to the pages and resources it can safely inspect.
Test results depend on the state and availability of the external demo service.
For more detail, see `docs/TEST\_PLAN.md`, `docs/TEST\_CASES.md`, and `docs/START\_HERE\_RU.md`.
Credits and license
Application under test: Practice Software Testing / Toolshop, maintained by `testsmith-io`. The tests in this repository are independent and do not redistribute the application. See the Toolshop project for its own licensing terms.
ShopGuard source code is licensed under the MIT License. See `LICENSE`.
