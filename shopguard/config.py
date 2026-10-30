"""Target selection, allowlist and reusable configuration for a shared public SUT."""
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

ALLOWED_HOSTS = {
    "practicesoftwaretesting.com", "with-bugs.practicesoftwaretesting.com",
    "api.practicesoftwaretesting.com", "api-with-bugs.practicesoftwaretesting.com",
    "v1.practicesoftwaretesting.com", "api-v1.practicesoftwaretesting.com",
    "v2.practicesoftwaretesting.com", "api-v2.practicesoftwaretesting.com",
    "v3.practicesoftwaretesting.com", "api-v3.practicesoftwaretesting.com",
    "v4.practicesoftwaretesting.com", "api-v4.practicesoftwaretesting.com",
    "localhost", "127.0.0.1",
}


def clean_base_url(value: str) -> str:
    """Avoid accidentally sending demo requests to an arbitrary third-party host."""
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Base URL must not contain credentials, path, query or fragment")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"Host is not on the explicit Toolshop allowlist: {parsed.hostname}")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Public Toolshop endpoints must use HTTPS")
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    shop_url: str
    api_url: str
    email: str
    password: str


def get_settings() -> Settings:
    return Settings(
        shop_url=clean_base_url(os.getenv("SHOP_URL", "https://practicesoftwaretesting.com")),
        api_url=clean_base_url(os.getenv("API_URL", "https://api.practicesoftwaretesting.com")),
        email=os.getenv("DEMO_EMAIL", "customer@practicesoftwaretesting.com"),
        password=os.getenv("DEMO_PASSWORD", "welcome01"),
    )
