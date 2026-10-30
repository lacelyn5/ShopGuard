"""Read-only comparison of normal and intentionally buggy Toolshop endpoints.

Observations are leads for manual investigation, NOT confirmed bug reports.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ENVIRONMENTS = {
    "baseline": "https://api.practicesoftwaretesting.com",
    "buggy": "https://api-with-bugs.practicesoftwaretesting.com",
}


def snapshot(client: requests.Session, base: str) -> dict:
    checks = {}
    for route in ("/products?page=1", "/categories", "/brands"):
        try:
            response = client.get(base + route, timeout=(5, 15))
            record = {"http_status": response.status_code}
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict):
                    record["count"] = len(payload.get("data", []))
                    record["total"] = payload.get("total")
                elif isinstance(payload, list):
                    record["count"] = len(payload)
            checks[route] = record
        except (requests.RequestException, ValueError) as exc:
            checks[route] = {"error": str(exc)}
    return checks


def main() -> int:
    with requests.Session() as client:
        client.headers["User-Agent"] = "ShopGuard-QA/1.0 (read-only environment comparison)"
        data = {name: snapshot(client, url) for name,url in ENVIRONMENTS.items()}
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "environments": data,
              "note": "Differences are investigation leads, not independently verified defects."}
    Path("reports").mkdir(exist_ok=True)
    path=Path("reports/environment-comparison.json")
    path.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("Saved:",path)
    return 0 if all("error" not in value for snapshot in data.values() for value in snapshot.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
