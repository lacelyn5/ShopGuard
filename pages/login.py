"""Customer sign-in page helpers; no account mutations."""
from playwright.sync_api import expect


class LoginPage:
    def __init__(self, page, base_url):
        self.page, self.base_url = page, base_url

    def open(self):
        self.page.goto(f"{self.base_url}/auth/login", wait_until="domcontentloaded")
        expect(self.page.locator("[data-test='email']")).to_be_visible()

    def login(self, email: str, password: str):
        self.page.locator("[data-test='email']").fill(email)
        self.page.locator("[data-test='password']").fill(password)
        self.page.locator("[data-test='login-submit']").click()
