"""Public demo authentication (no account creation or credential changes)."""
import pytest
from shopguard.client import checked_json
from shopguard.contracts import token_response


@pytest.mark.api
@pytest.mark.smoke
def test_current_user_requires_auth(client):
    response = client.get("/users/me")
    assert response.status_code == 401, f"expected 401 without bearer token; got {response.status_code}"


@pytest.mark.api
@pytest.mark.auth
@pytest.mark.regression
def test_demo_customer_login_and_read_profile(client, settings):
    token = token_response(checked_json(client.post_json("/users/login", {
        "email": settings.email, "password": settings.password,
    })))
    client.session.headers["Authorization"] = f"Bearer {token}"
    response = checked_json(client.get("/users/me"))
    assert isinstance(response, dict)
    assert response.get("email", "").lower() == settings.email.lower()


@pytest.mark.api
@pytest.mark.regression
def test_admin_only_report_denies_anonymous(client):
    response = client.get("/reports/top10-purchased-products")
    assert response.status_code == 401, f"expected 401 for anonymous admin report, got {response.status_code}"
