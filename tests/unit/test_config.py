import pytest
from shopguard.config import clean_base_url, Settings


@pytest.mark.unit
@pytest.mark.parametrize("candidate", [
    "https://practicesoftwaretesting.com",
    "https://api.practicesoftwaretesting.com/",
    "https://with-bugs.practicesoftwaretesting.com",
    "http://localhost:8090",
    "http://127.0.0.1:8000",
])
def test_allowed_hosts(candidate):
    assert clean_base_url(candidate).endswith("practicesoftwaretesting.com") or "localhost" in candidate or "127.0.0.1" in candidate


@pytest.mark.unit
@pytest.mark.parametrize("candidate", [
    "https://example.com", "ftp://practicesoftwaretesting.com", "https://attacker@practicesoftwaretesting.com",
    "http://api.practicesoftwaretesting.com", "https://practicesoftwaretesting.com/private",
    "https://practicesoftwaretesting.com?redirect=http://example.com", "", "//localhost:80",
])
def test_reject_bad_hosts_and_paths(candidate):
    with pytest.raises(ValueError):
        clean_base_url(candidate)


@pytest.mark.unit
def test_trim_trailing_slash():
    assert clean_base_url("https://practicesoftwaretesting.com/") == "https://practicesoftwaretesting.com"
