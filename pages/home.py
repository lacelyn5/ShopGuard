"""Toolshop storefront locators isolated from test intentions.

The target is maintained by a third party. Changes to data-test selectors
should be handled here rather than weakening assertions in individual tests.
"""
from playwright.sync_api import expect


class HomePage:
    def __init__(self, page, base_url):
        self.page = page
        self.base_url = base_url

    def open(self):
        self.page.goto(self.base_url, wait_until="domcontentloaded")
        expect(self.page).to_have_title(__import__("re").compile(r"Toolshop|Practice Software Testing", __import__("re").I))

    def product_cards(self):
        return self.page.locator("[data-test='product-name']")

    def search(self, phrase: str):
        search_field = self.page.locator("[data-test='search-query']")
        expect(search_field).to_be_visible()
        search_field.fill(phrase)
        self.page.locator("[data-test='search-submit']").click()

    def open_first_product(self):
        item = self.product_cards().first
        expect(item).to_be_visible()
        item.click()
