"""Optional stateful API scenario. NEVER part of ordinary smoke/regression commands.

A new cart adds records to the practice server: explicit opt in required.
"""
import os
import pytest
from shopguard.client import checked_json
from shopguard.contracts import product_list


@pytest.mark.api
@pytest.mark.stateful
def test_new_cart_can_hold_one_demo_product(client):
    if os.getenv("SHOPGUARD_ALLOW_STATEFUL") != "I_UNDERSTAND_SHARED_DATA":
        pytest.skip("Set SHOPGUARD_ALLOW_STATEFUL=I_UNDERSTAND_SHARED_DATA for shared-server writes")
    products = product_list(checked_json(client.get("/products")))
    assert products
    # Intentional only within opt-in test; the normal client refuses mutation routes.
    created = client.session.post(f"{client.base_url}/carts", timeout=(5,20))
    cart_id = checked_json(created, 201)["id"]
    added = client.session.post(f"{client.base_url}/carts/{cart_id}",
                                json={"product_id": products[0]["id"], "quantity": 1}, timeout=(5,20))
    checked_json(added, 200)
    cart = checked_json(client.get(f"/carts/{cart_id}"))
    assert isinstance(cart, dict)
    assert cart.get("id") == cart_id, "the new cart should remain retrievable"
    # The published v5 CartResponse schema documents only an `id`, not line items.
    # The HTTP 200 response above confirms the add-item operation was accepted;
    # avoid asserting an undocumented `cart_items` field.
