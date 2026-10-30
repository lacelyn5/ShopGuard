"""Non-mutating login-page checks."""
import re
import pytest
from playwright.sync_api import expect
from pages.login import LoginPage


@pytest.mark.ui
@pytest.mark.smoke
def test_login_page_fields_visible(shop_page, settings):
    login = LoginPage(shop_page, settings.shop_url)
    login.open()
    expect(shop_page.locator("[data-test='email']")).to_be_visible()
    expect(shop_page.locator("[data-test='password']")).to_be_visible()
    expect(shop_page.locator("[data-test='login-submit']")).to_be_visible()


@pytest.mark.ui
@pytest.mark.regression
def test_login_with_invalid_credentials_is_rejected(shop_page, settings):
    login = LoginPage(shop_page, settings.shop_url)
    login.open()
    login.login("invalid.user.not.registered@example.test", "wrong-password-1234")

    # A route check alone is too weak: the app could silently ignore the submit.
    # Require a visible, user-facing rejection message as well as remaining signed out.
    expect(shop_page).to_have_url(re.compile(r"/auth/login"), timeout=15000)
    expect(shop_page.locator("[data-test='login-submit']")).to_be_visible()
    rejection_message = re.compile(
        r"invalid|incorrect|wrong|credentials|not correct|not successful|"
        r"authentication failed|authentication error|failed to authenticate|"
        r"sign in failed|login failed|unable to sign in|unauthorized",
        re.IGNORECASE,
    )
    expect(shop_page.locator("body")).to_contain_text(rejection_message, timeout=15000)
