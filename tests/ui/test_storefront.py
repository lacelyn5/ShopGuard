"""Small UI smoke/regression suite; live site selectors may evolve."""
import re
import pytest
from playwright.sync_api import expect
from pages.home import HomePage


@pytest.mark.ui
@pytest.mark.smoke
def test_homepage_loads_with_products(shop_page, settings):
    home = HomePage(shop_page, settings.shop_url)
    home.open()
    expect(home.product_cards().first).to_be_visible(timeout=20000)


@pytest.mark.ui
@pytest.mark.smoke
def test_product_detail_opens(shop_page, settings):
    home = HomePage(shop_page, settings.shop_url)
    home.open()
    home.open_first_product()
    expect(shop_page).to_have_url(re.compile(r"/product/"), timeout=15000)
    expect(shop_page.locator("[data-test='product-name']").first).to_be_visible()


@pytest.mark.ui
@pytest.mark.regression
def test_search_for_present_product(shop_page, settings):
    home = HomePage(shop_page, settings.shop_url)
    home.open()
    first = home.product_cards().first
    expect(first).to_be_visible(timeout=20000)
    name = first.inner_text().strip()
    assert name
    home.search(name)
    expect(home.product_cards().filter(has_text=name).first).to_be_visible(timeout=20000)


@pytest.mark.ui
@pytest.mark.regression
def test_search_for_unlikely_text_shows_no_matches(shop_page, settings):
    home = HomePage(shop_page, settings.shop_url)
    home.open()
    home.search("zzzz-no-tool-exists-2026-qa")
    expect(home.product_cards()).to_have_count(0, timeout=20000)
