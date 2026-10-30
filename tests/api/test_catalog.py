"""Read-only public API contract and functional tests (live network required)."""
import pytest
from shopguard.client import checked_json
from shopguard.contracts import product_list, product_record, named_collection, assert_ascending


@pytest.mark.api
@pytest.mark.smoke
def test_product_listing_response(client):
    items = product_list(checked_json(client.get("/products")))
    assert items, "practice shop should expose demo products"


@pytest.mark.api
@pytest.mark.smoke
def test_categories_endpoint(client):
    result = named_collection(checked_json(client.get("/categories")))
    assert result, "expected at least one category"


@pytest.mark.api
@pytest.mark.smoke
def test_brands_endpoint(client):
    assert named_collection(checked_json(client.get("/brands")))


@pytest.mark.api
@pytest.mark.regression
def test_products_have_unique_ids_on_first_page(client):
    data = product_list(checked_json(client.get("/products")))
    ids = [row["id"] for row in data]
    assert len(ids) == len(set(ids)), "duplicate product IDs on one page"


@pytest.mark.api
@pytest.mark.regression
def test_page_one_explicit(client):
    payload = checked_json(client.get("/products", {"page": 1}))
    product_list(payload)
    assert payload["current_page"] == 1


@pytest.mark.api
@pytest.mark.regression
def test_fetch_existing_product_by_dynamic_id(client):
    items = product_list(checked_json(client.get("/products")))
    assert items, "cannot obtain product for detail check"
    product = product_record(checked_json(client.get(f"/products/{items[0]['id']}")))
    assert product["id"] == items[0]["id"]


@pytest.mark.api
@pytest.mark.regression
def test_product_search_for_existing_name(client):
    items = product_list(checked_json(client.get("/products")))
    assert items
    phrase = items[0]["name"]
    results = product_list(checked_json(client.get("/products/search", {"q": phrase})))
    assert any(x["id"] == items[0]["id"] for x in results), "known product not found by name"


@pytest.mark.api
@pytest.mark.regression
def test_price_ascending_sort(client):
    result = product_list(checked_json(client.get("/products", {"sort":"price,asc"})))
    assert len(result) > 1
    assert_ascending([product["price"] for product in result])


@pytest.mark.api
@pytest.mark.regression
def test_price_descending_sort(client):
    result = product_list(checked_json(client.get("/products", {"sort":"price,desc"})))
    assert len(result) > 1
    prices = [product["price"] for product in result]
    assert prices == sorted(prices, reverse=True)


@pytest.mark.api
@pytest.mark.regression
def test_product_related_endpoint(client):
    first = product_list(checked_json(client.get("/products")))
    assert first
    related = checked_json(client.get(f"/products/{first[0]['id']}/related"))
    assert isinstance(related, list)
    for row in related:
        product_record(row)


@pytest.mark.api
@pytest.mark.regression
def test_categories_tree_endpoint(client):
    value = checked_json(client.get("/categories/tree"))
    assert isinstance(value, list)
