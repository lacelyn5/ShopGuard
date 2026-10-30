"""Small, intentional response contracts validated without overfitting changing data."""
from collections.abc import Mapping


def product_list(body: object) -> list[dict]:
    assert isinstance(body, dict), "expected paginated JSON object"
    assert isinstance(body.get("current_page"), int) and body["current_page"] >= 1
    assert isinstance(body.get("total"), int) and body["total"] >= 0
    data = body.get("data")
    assert isinstance(data, list), "expected JSON data array"
    for product in data:
        product_record(product)
    return data


def product_record(value: object) -> Mapping:
    assert isinstance(value, dict), "product must be an object"
    for field in ("id", "name"):
        assert isinstance(value.get(field), str) and value[field].strip(), f"invalid {field}"
    assert isinstance(value.get("price"), (int, float)) and not isinstance(value.get("price"), bool)
    assert value["price"] >= 0
    return value


def named_collection(value: object) -> list:
    assert isinstance(value, list), "expected a JSON list"
    for entry in value:
        assert isinstance(entry, dict), "entry must be object"
        assert isinstance(entry.get("name"), str) and entry["name"].strip()
    return value


def token_response(value: object) -> str:
    assert isinstance(value, dict)
    token = value.get("access_token")
    assert isinstance(token, str) and len(token) > 12
    return token


def assert_ascending(values: list[float]):
    assert values == sorted(values), f"expected ascending order; observed {values}"
