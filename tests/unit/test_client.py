import pytest
from shopguard.client import ToolshopClient, checked_json


class FakeResponse:
    def __init__(self, status=200, content_type="application/json", value=None):
        self.status_code=status
        self.headers={"Content-Type":content_type}
        self.value={"ok":True} if value is None else value
        self.text='{"ok":true}'
        self.url="https://api.practicesoftwaretesting.com/products"
        self.request=type("Req", (), {"method": "GET"})()
    def json(self):
        return self.value


class FakeSession:
    def __init__(self):
        self.headers={}
        self.calls=[]
    def get(self, url, **kwargs):
        self.calls.append(("GET",url,kwargs))
        return FakeResponse()
    def post(self,url, **kwargs):
        self.calls.append(("POST",url,kwargs))
        return FakeResponse()


@pytest.mark.unit
def test_get_passes_safe_url_and_timeout():
    s=FakeSession()
    ToolshopClient("https://api.practicesoftwaretesting.com",s).get("/products", {"page":1})
    method,url,kwargs=s.calls[0]
    assert method == "GET" and url.endswith("/products")
    assert kwargs["timeout"] == (5,20)
    assert kwargs["params"] == {"page":1}


@pytest.mark.unit
@pytest.mark.parametrize("path", ["https://evil.example/", "//evil.example", "products"])
def test_invalid_relative_route(path):
    with pytest.raises(ValueError):
        ToolshopClient("https://api.practicesoftwaretesting.com",FakeSession()).get(path)


@pytest.mark.unit
def test_post_login_is_allowed():
    s=FakeSession()
    ToolshopClient("https://api.practicesoftwaretesting.com",s).post_json("/users/login", {"email":"demo","password":"demo"})
    assert s.calls[0][0] == "POST"


@pytest.mark.unit
def test_post_other_routes_is_denied():
    with pytest.raises(ValueError):
        ToolshopClient("https://api.practicesoftwaretesting.com",FakeSession()).post_json("/products", {})


@pytest.mark.unit
def test_checked_json_contract():
    assert checked_json(FakeResponse()) == {"ok":True}


@pytest.mark.unit
@pytest.mark.parametrize("response",[FakeResponse(500),FakeResponse(200,"text/html")])
def test_checked_json_detects_errors(response):
    with pytest.raises(AssertionError):
        checked_json(response)
