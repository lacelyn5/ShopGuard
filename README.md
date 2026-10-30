# ShopGuard

**A Python-based QA automation framework for API and browser testing.**

[![CI](https://github.com/lacelyn5/ShopGuard/actions/workflows/tests.yml/badge.svg)](https://github.com/lacelyn5/ShopGuard/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-testing-0A9EDC?logo=pytest&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-browser%20testing-2EAD33?logo=playwright&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

ShopGuard is an independent portfolio project built to demonstrate practical software testing workflows. It combines automated API checks, browser-based UI tests, a local dashboard, and a small read-only website checker in one Python project.

The built-in test suites target the public [Practice Software Testing / Toolshop demo store](https://practicesoftwaretesting.com). ShopGuard is a testing tool; it does not contain the store's source code and is not a commercial security scanner.

## What it includes

| Area | What it does |
|---|---|
| **API testing** | Sends requests and checks response codes, data, and selected authorization behaviour. |
| **Browser testing** | Uses Playwright to check storefront pages and selected UI elements. |
| **Local dashboard** | Starts test groups, manages saved targets, and displays run history. |
| **Website checks** | Runs a limited, read-only set of checks against an authorized public website. |
| **Test evidence** | Stores logs, JUnit reports, JSON evidence, and screenshots when available. |
| **Postman** | Includes a collection of 14 ordered HTTP requests with assertions. |
| **CI** | Runs offline checks with Python 3.11, 3.12, 3.13, and 3.14 through GitHub Actions. |

## Quick start and daily workflow

**Requirements:** Python 3.11 or newer. An internet connection is needed to install dependencies, download Chromium, and run live tests.

1. Clone or download this repository.
2. From the project folder, run:

   ```bat
   scripts\setup_windows.bat
   ```

3. Start the dashboard:

   ```bat
   scripts\run_dashboard_windows.bat
   ```

4. Open **http://127.0.0.1:8765** in your browser.

Start with **Test groups → Local checks**. The built-in API and Browser smoke groups can then be used to check the demo store integration.

## Running tests

Run commands from the project folder after setup.

**Offline checks** — do not depend on the external demo store:

```powershell
.\.venv\Scripts\python.exe -m pytest -m unit -v
```

**API smoke tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest -m "api and smoke" -v
```

**Browser smoke tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest -m "ui and smoke" -v
```

Live tests depend on the availability and current state of the public demo service. A failed live check should be investigated and is not automatically proof of a defect in the application.

## Dashboard and website checker

The dashboard runs locally at **http://127.0.0.1:8765**. It includes predefined test groups, saved website targets, run history, logs, reports, evidence, and local backup/restore.

The configurable website checks are deliberately limited:

- Browser checks use GET/HEAD requests on the configured host.
- API checks use GET requests and do not follow redirects.
- The checker blocks local/private destinations and unsafe redirects.
- It does not log in, submit forms, change data, place orders, or test payments.

Use the checker only on public websites that you own or are authorized to test. Its results are signals for manual review, not a guarantee that a website is secure or defect-free.

## Project structure

```text
shopguard/                 API client, configuration, and response assertions
pages/                     Page Object helpers
tests/api/                 API tests
tests/ui/                  Browser tests
tests/unit/                Offline tests
tests/targets/             Generic read-only target checks
dashboard/                 Local dashboard and website checker
postman/                   Postman collection and environment
docs/                      Test plan, test cases, and user guides
scripts/                   Windows setup and run scripts
.github/workflows/         GitHub Actions workflow
```

## Documentation

- [Test plan](docs/TEST_PLAN.md)
- [Test cases](docs/TEST_CASES.md)
- [Getting started guide (Russian)](docs/START_HERE_RU.md)
- [Postman collection](postman/ShopGuard.postman_collection.json)

## Notes and limitations

- The built-in API and UI suites are designed for the Practice Software Testing / Toolshop demo environment.
- Generic saved-target checks are configurable smoke checks, not full end-to-end regression suites for arbitrary websites.
- Dashboard API checks support GET requests only; dashboard-based API authentication and write operations are not configurable.
- Live results depend on the external demo service. The GitHub Actions workflow runs the offline suite automatically; live checks are optional manual workflows.

## Credits and license

**Demo application:** [Practice Software Testing / Toolshop](https://practicesoftwaretesting.com), maintained by `testsmith-io`.

**ShopGuard:** Created by Maksim Kernazhytski. Source code is licensed under the [MIT License](LICENSE).
