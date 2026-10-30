import pytest
from shopguard.contracts import (
    product_list, product_record, named_collection, token_response, assert_ascending,
)


@pytest.fixture
def sample_product():
    return {"id": "01HHJC7RERZ0M3VDGS6X9HM33A", "name": "Hammer", "price": 12.99}


@pytest.mark.unit
def test_product_contract_accepts_sample(sample_product):
    assert product_record(sample_product)["name"] == "Hammer"


@pytest.mark.unit
@pytest.mark.parametrize("patch", [{"id": None}, {"name": ""}, {"price": -1}, {"price": "12"}, {"price": True}])
def test_product_contract_rejects_bad_data(sample_product, patch):
    with pytest.raises(AssertionError):
        product_record({**sample_product, **patch})


@pytest.mark.unit
def test_paginated_response(sample_product):
    assert len(product_list({"data": [sample_product], "current_page": 1, "total": 1})) == 1


@pytest.mark.unit
@pytest.mark.parametrize("payload", [[], {"data": [], "current_page": 0, "total": 0}, {"data": {}, "current_page": 1, "total": 1}])
def test_paginated_response_rejects_invalid(payload):
    with pytest.raises(AssertionError):
        product_list(payload)


@pytest.mark.unit
def test_named_collection():
    assert len(named_collection([{"name": "Brand"}])) == 1


@pytest.mark.unit
def test_named_collection_rejects_bad_name():
    with pytest.raises(AssertionError):
        named_collection([{"name": ""}])


@pytest.mark.unit
def test_token_response():
    assert token_response({"access_token": "sufficiently-long-demo-token"})


@pytest.mark.unit
def test_token_response_rejects_missing_token():
    with pytest.raises(AssertionError):
        token_response({"access_token": None})


@pytest.mark.unit
def test_sort_contract():
    assert_ascending([1, 1.5, 6])


@pytest.mark.unit
def test_sort_contract_detects_wrong_order():
    with pytest.raises(AssertionError):
        assert_ascending([4, 2, 3])
