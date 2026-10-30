"""Offline unit tests for the public-URL scanner and its safety guardrails."""
import socket
from unittest.mock import Mock

import pytest

from dashboard.url_scanner import (
    ScanInputError,
    _PageInspector,
    ScanBrowserError,
    _add_browser_checks,
    _browser_resource_allowed,
    _classify_failed_browser_request,
    _wait_for_dynamic_product_markers,
    _enrich_checks,
    scan_public_url,
    validate_public_url,
)


def _public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


@pytest.mark.unit
def test_dynamic_product_wait_uses_stable_toolshop_markers():
    """The scan waits briefly for product cards injected after DOMContentLoaded."""
    page = Mock()
    assert _wait_for_dynamic_product_markers(page) is True
    script = page.wait_for_function.call_args.args[0]
    kwargs = page.wait_for_function.call_args.kwargs
    assert '[data-test="product-name" i]' in script
    assert '[data-testid="product-name" i]' in script
    assert kwargs['timeout'] == 5000
    assert kwargs['polling'] == 200


@pytest.mark.unit
def test_dynamic_product_wait_treats_timeout_as_no_observed_marker():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    page = Mock()
    page.wait_for_function.side_effect = PlaywrightTimeoutError('timeout')
    assert _wait_for_dynamic_product_markers(page) is False



@pytest.mark.unit
def test_scan_in_browser_actually_invokes_dynamic_product_wait(monkeypatch):
    """The dynamic-marker wait must be part of the real scan, not dead code."""
    from types import SimpleNamespace
    import playwright.sync_api as playwright_api

    dom_snapshot = {
        "title": "Toolshop",
        "h1Count": 1,
        "metaDescription": True,
        "imageCount": 1,
        "imagesMissingAlt": 0,
        "imagesEmptyAlt": 0,
        "imageLoadUnverifiedCount": 0,
        "searchCount": 1,
        "formCount": 0,
        "shopSignals": ["product/catalog elements", "price indicators"],
        "shopEvidence": {"product/catalog elements": 4, "price indicators": 4},
        "links": [],
    }

    class FakePage:
        def set_default_navigation_timeout(self, *_args): pass
        def set_default_timeout(self, *_args): pass
        def on(self, *_args): pass
        def goto(self, *_args, **_kwargs): return SimpleNamespace(status=200)
        def wait_for_timeout(self, *_args): pass
        def evaluate(self, *_args): return dom_snapshot

    class FakeContext:
        def __init__(self): self.page = FakePage()
        def new_page(self): return self.page
        def route(self, *_args): pass
        def close(self): pass

    class FakeBrowser:
        def __init__(self): self.context = FakeContext()
        def new_context(self, **_kwargs): return self.context
        def close(self): pass

    class FakeManager:
        def __enter__(self):
            self.chromium = SimpleNamespace(launch=lambda **_kwargs: FakeBrowser())
            return self
        def __exit__(self, *_args): pass

    wait_spy = Mock(return_value=True)
    monkeypatch.setattr("dashboard.url_scanner._wait_for_dynamic_product_markers", wait_spy)
    monkeypatch.setattr(playwright_api, "sync_playwright", lambda: FakeManager())

    from dashboard.url_scanner import _scan_in_browser
    result = _scan_in_browser("https://example.com/")

    wait_spy.assert_called_once()
    assert "product/catalog elements" in result["shop_signals"]
    assert result["shop_evidence"]["product/catalog elements"] == 4


@pytest.mark.unit
def test_browser_scan_counts_confirmed_failed_image_response(monkeypatch):
    """Only a confirmed failed image response becomes a broken-image warning."""
    from types import SimpleNamespace
    import playwright.sync_api as playwright_api

    dom_snapshot = {
        "title": "Toolshop", "h1Count": 1, "metaDescription": True,
        "imageCount": 1, "imagesMissingAlt": 0, "imagesEmptyAlt": 0,
        "imageLoadUnverifiedCount": 1, "searchCount": 0, "formCount": 0,
        "shopSignals": ["product/catalog elements"],
        "shopEvidence": {"product/catalog elements": 1}, "links": [],
    }

    class FakePage:
        def __init__(self): self.handlers = {}
        def set_default_navigation_timeout(self, *_args): pass
        def set_default_timeout(self, *_args): pass
        def on(self, event, callback): self.handlers[event] = callback
        def goto(self, *_args, **_kwargs):
            failed_image = SimpleNamespace(resource_type="image")
            self.handlers["response"](SimpleNamespace(
                status=404, url="https://cdn.example.com/catalog/product.jpg", request=failed_image
            ))
            return SimpleNamespace(status=200)
        def wait_for_timeout(self, *_args): pass
        def evaluate(self, *_args): return dom_snapshot

    class FakeContext:
        def __init__(self): self.page = FakePage()
        def new_page(self): return self.page
        def route(self, *_args): pass
        def close(self): pass

    class FakeBrowser:
        def __init__(self): self.context = FakeContext()
        def new_context(self, **_kwargs): return self.context
        def close(self): pass

    class FakeManager:
        def __enter__(self):
            self.chromium = SimpleNamespace(launch=lambda **_kwargs: FakeBrowser())
            return self
        def __exit__(self, *_args): pass

    monkeypatch.setattr("dashboard.url_scanner._wait_for_dynamic_product_markers", lambda *_args: True)
    monkeypatch.setattr(playwright_api, "sync_playwright", lambda: FakeManager())

    from dashboard.url_scanner import _scan_in_browser
    result = _scan_in_browser("https://example.com/")
    assert result["broken_image_count"] == 1
    assert result["images_unverified_count"] == 0
    assert result["failed_image_requests"] == ["HTTP 404 cdn.example.com/catalog/product.jpg"]


@pytest.mark.unit
def test_browser_route_allows_query_preflight_but_blocks_state_changes(monkeypatch):
    """The real Playwright route handler must allow safe catalog QUERY and CORS preflight."""
    from types import SimpleNamespace
    import playwright.sync_api as playwright_api

    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    continued = []
    aborted = []

    class FakeRequest:
        def __init__(self, url, method, *, headers=None, body=None, navigation=False, resource_type="fetch"):
            self.url = url
            self.method = method
            self.headers = headers or {}
            self.post_data_buffer = body
            self.resource_type = resource_type
            self.frame = SimpleNamespace(parent_frame=None)
            self._navigation = navigation
        def is_navigation_request(self):
            return self._navigation

    class FakeRoute:
        def __init__(self, request): self.request = request
        def continue_(self): continued.append(self.request.method)
        def abort(self, reason="failed"): aborted.append((self.request.method, reason))

    class FakePage:
        def __init__(self): self.route_handler = None
        def set_default_navigation_timeout(self, *_args): pass
        def set_default_timeout(self, *_args): pass
        def on(self, *_args): pass
        def wait_for_timeout(self, *_args): pass
        def goto(self, *_args, **_kwargs):
            requests = [
                FakeRequest("https://example.com/", "GET", navigation=True, resource_type="document"),
                FakeRequest("https://api.example.com/products", "OPTIONS", headers={
                    "origin": "https://example.com",
                    "access-control-request-method": "QUERY",
                }),
                FakeRequest("https://api.example.com/products", "QUERY", headers={
                    "origin": "https://example.com", "content-type": "application/json",
                }, body=b'{"page":"1"}'),
                FakeRequest("https://example.com/cart", "POST", headers={"content-type": "application/json"}, body=b'{"item":1}'),
            ]
            for request in requests:
                self.route_handler(FakeRoute(request))
            return SimpleNamespace(status=200)
        def evaluate(self, *_args):
            return {
                "title": "Toolshop", "h1Count": 1, "metaDescription": True,
                "imageCount": 0, "imagesMissingAlt": 0, "imagesEmptyAlt": 0,
                "brokenImageCount": 0, "searchCount": 1, "formCount": 0,
                "shopSignals": ["product/catalog elements"],
                "shopEvidence": {"product/catalog elements": 3}, "links": [],
            }

    class FakeContext:
        def __init__(self): self.page = FakePage()
        def new_page(self): return self.page
        def route(self, _pattern, handler): self.page.route_handler = handler
        def close(self): pass

    class FakeBrowser:
        def __init__(self): self.context = FakeContext()
        def new_context(self, **_kwargs): return self.context
        def close(self): pass

    class FakeManager:
        def __enter__(self):
            self.chromium = SimpleNamespace(launch=lambda **_kwargs: FakeBrowser())
            return self
        def __exit__(self, *_args): pass

    monkeypatch.setattr(playwright_api, "sync_playwright", lambda: FakeManager())
    monkeypatch.setattr("dashboard.url_scanner._wait_for_dynamic_product_markers", lambda *_args: True)

    from dashboard.url_scanner import _scan_in_browser
    result = _scan_in_browser("https://example.com/")

    assert continued == ["GET", "OPTIONS", "QUERY"]
    assert len(aborted) == 1 and aborted[0][0] == "POST"
    assert result["request_count"] == 4
    assert result["blocked_requests"] == 1


@pytest.mark.unit
def test_public_url_is_normalized(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    assert validate_public_url("EXAMPLE.COM/path?q=1#section") == "https://example.com/path?q=1"


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/win.ini",
        "ftp://example.com/file",
        "http://localhost/",
        "http://anything.local/",
        "http://127.0.0.1/",
        "http://192.168.1.1/",
        "https://user:password@example.com/",
        "https://example.com:8443/",
        "not a url",
    ],
)
def test_private_or_unsupported_urls_are_rejected(monkeypatch, url):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    with pytest.raises(ScanInputError):
        validate_public_url(url)


@pytest.mark.unit
def test_hostname_resolving_to_private_ip_is_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))],
    )
    with pytest.raises(ScanInputError, match="local or reserved"):
        validate_public_url("https://example.com/")


@pytest.mark.unit
def test_page_inspector_extracts_basic_store_signals():
    parser = _PageInspector()
    parser.feed(
        '<html><head><title>Demo Store</title>'
        '<meta name="description" content="A test shop"></head><body>'
        '<h1>Tools</h1><img src="tool.png"><img src="ok.png" alt="Tool">'
        '<input type="search" placeholder="Search products">'
        '<a href="/products">Products</a><a href="/cart">Cart</a>'
        '<button>Add to cart</button><p>Price $19</p><form></form></body></html>'
    )
    parser.close()
    assert parser.title == "Demo Store"
    assert parser.h1_parts == ["Tools"]
    assert parser.meta_description is True
    assert parser.image_count == 2
    assert parser.images_missing_alt == 1
    assert parser.search_control is True
    assert parser.forms == 1
    assert "product/catalog elements" in parser.shop_signals
    assert "cart/basket controls" in parser.shop_signals
    assert "add-to-cart controls" in parser.shop_signals
    assert "price indicators" in parser.shop_signals


@pytest.mark.unit
def test_page_inspector_detects_toolshop_data_test_markers_and_commerce_controls():
    """The scanner must recognise stable markers already used by its UI tests."""
    parser = _PageInspector()
    parser.feed(
        '<main><a data-test="product-name" href="/product/123">Combination Pliers</a>'
        '<span data-test="product-price">$12.50</span>'
        '<button data-test="add-to-cart">Add to cart</button>'
        '<a aria-label="Shopping cart" href="/checkout">Cart</a>'
        '</main>'
    )
    parser.close()

    assert "product/catalog elements" in parser.shop_signals
    assert "price indicators" in parser.shop_signals
    assert "cart/basket controls" in parser.shop_signals
    assert "add-to-cart controls" in parser.shop_signals
    assert "checkout/payment navigation" in parser.shop_signals
    assert parser.shop_evidence["product/catalog elements"] >= 1


@pytest.mark.unit
def test_product_price_marker_alone_is_not_mislabelled_as_catalog():
    parser = _PageInspector()
    parser.feed('<span data-test="product-price">$12.50</span>')
    parser.close()
    assert "price indicators" in parser.shop_signals
    assert "product/catalog elements" not in parser.shop_signals


@pytest.mark.unit
def test_page_inspector_does_not_treat_productivity_class_as_a_store():
    parser = _PageInspector()
    parser.feed('<main><section class="productivity-tips">Improve your productivity</section></main>')
    parser.close()
    assert "product/catalog elements" not in parser.shop_signals



class _FakeResponse:
    def __init__(self, status_code=200, headers=None, content=b""):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self._content = content
        self.closed = False

    def iter_content(self, chunk_size=8192):
        if self._content:
            yield self._content

    def close(self):
        self.closed = True


@pytest.mark.unit
def test_scan_reports_page_checks_without_network(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    page = (
        b'<html><head><title>Shop</title><meta name="description" content="Store"></head>'
        b'<body><h1>Products</h1><a href="/products">Products</a>'
        b'<a href="/cart">Cart</a><img src="x.png" alt="Product">'
        b'<input type="search"><button>Add to cart</button><p>Price $10</p></body></html>'
    )

    def fake_request(method, url, **kwargs):
        if method == "GET" and url.endswith("/"):
            return _FakeResponse(content=page)
        if method == "HEAD":
            return _FakeResponse(headers={"Content-Type": "text/html"})
        return _FakeResponse(content=b"ok")

    monkeypatch.setattr("dashboard.url_scanner.requests.request", fake_request)
    monkeypatch.setattr(
        "dashboard.url_scanner._scan_in_browser",
        lambda url: {
            "available": True,
            "navigation_status": 200,
            "navigation_timed_out": False,
            "title": "Shop rendered by JavaScript",
            "h1_count": 1,
            "meta_description": True,
            "image_count": 0,
            "images_missing_alt": 0,
            "broken_image_count": 0,
            "search_count": 1,
            "form_count": 1,
            "shop_signals": ["cart/basket controls"],
            "shop_evidence": {
                "product/catalog elements": 3,
                "price indicators": 3,
                "cart/basket controls": 1,
            },
            "links": ["https://example.com/products", "https://example.com/cart"],
            "javascript_errors": [],
            "failed_requests": [],
            "http_errors": [],
            "request_count": 8,
            "blocked_requests": 0,
        },
    )
    result = scan_public_url("https://example.com/")
    checks = {check["name"]: check for check in result["checks"]}
    assert result["status_code"] == 200
    assert result["summary"]["failed"] == 0
    assert checks["Page title"]["detail"] == "Title found: Shop rendered by JavaScript"
    assert checks["Main heading (H1)"]["status"] == "pass"
    assert checks["Image accessibility"]["status"] == "info"
    assert checks["Image loading"]["status"] == "info"
    assert checks["Internal links"]["status"] == "pass"
    assert checks["Store features"]["status"] == "info"
    assert "product/catalog elements" in checks["Store features"]["detail"]
    assert "price indicators" in checks["Store features"]["detail"]
    assert "cart/basket controls" in checks["Store features"]["detail"]
    assert "did not click controls" in checks["Store features"]["detail"]
    assert "no markers for" in checks["Store features"]["detail"]
    assert checks["Browser page load"]["status"] == "pass"
    assert checks["JavaScript errors"]["status"] == "pass"
    assert result["browser_scan"] is True
    assert result["final_url"] == "https://example.com/"

@pytest.mark.unit
def test_redirect_to_private_address_is_blocked(monkeypatch):
    from dashboard.url_scanner import _request_follow_safe

    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(url)
        return _FakeResponse(status_code=302, headers={"Location": "http://127.0.0.1/admin"})

    monkeypatch.setattr("dashboard.url_scanner.requests.request", fake_request)
    with pytest.raises(ScanInputError, match="blocked"):
        _request_follow_safe("https://example.com/")
    assert calls == ["https://example.com/"]


@pytest.mark.unit
def test_browser_request_filter_blocks_private_posts_and_external_page_navigation(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    target = "https://example.com/"
    assert _browser_resource_allowed("https://example.com/assets/site.css", "GET", False, target)
    assert _browser_resource_allowed("data:image/png;base64,AA", "GET", False, target)
    assert not _browser_resource_allowed("file:///C:/Windows/win.ini", "GET", False, target)
    assert not _browser_resource_allowed("https://example.com/cart", "POST", False, target)
    assert not _browser_resource_allowed("https://example.com/cart", "PUT", False, target)
    assert not _browser_resource_allowed("http://127.0.0.1/admin", "GET", False, target)
    assert not _browser_resource_allowed("https://other.example.com/", "GET", True, target)
    assert _browser_resource_allowed("https://example.com/products", "GET", True, target)


@pytest.mark.unit
def test_browser_allows_bounded_safe_query_for_same_page_origin_api(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    target = "https://example.com/"
    api = "https://api.example.com/products"
    headers = {"origin": "https://example.com", "content-type": "application/json"}
    assert _browser_resource_allowed(api, "QUERY", False, target, headers, b'{"page":"1"}')
    assert not _browser_resource_allowed(api, "QUERY", True, target, headers, b'{"page":"1"}')
    assert not _browser_resource_allowed(api, "QUERY", False, target, headers, b"")
    assert not _browser_resource_allowed(api, "QUERY", False, target, {"origin": "https://attacker.example" , "content-type": "application/json"}, b'{"page":"1"}')
    assert not _browser_resource_allowed(api, "QUERY", False, target, {"origin": "https://example.com", "content-type": "text/plain"}, b'{"page":"1"}')
    assert not _browser_resource_allowed(api, "QUERY", False, target, headers, b"x" * (16 * 1024 + 1))


@pytest.mark.unit
def test_browser_allows_only_matching_query_cors_preflight(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    target = "https://example.com/"
    api = "https://api.example.com/products"
    preflight = {"origin": "https://example.com", "access-control-request-method": "QUERY"}
    assert _browser_resource_allowed(api, "OPTIONS", False, target, preflight)
    assert not _browser_resource_allowed(api, "OPTIONS", False, target, {"origin": "https://example.com", "access-control-request-method": "POST"})
    assert not _browser_resource_allowed(api, "OPTIONS", False, target, {"origin": "https://attacker.example", "access-control-request-method": "QUERY"})
    assert not _browser_resource_allowed(api, "OPTIONS", True, target, preflight)


@pytest.mark.unit
def test_unverified_image_snapshot_is_info_not_broken_image_warning(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    page = b'<html><head><title>Images</title></head><body><h1>Gallery</h1><img src="one.jpg" alt="One"><img src="two.jpg" alt="Two"></body></html>'

    def fake_request(method, url, **kwargs):
        return _FakeResponse(content=page)

    monkeypatch.setattr("dashboard.url_scanner.requests.request", fake_request)
    monkeypatch.setattr("dashboard.url_scanner._scan_in_browser", lambda url: {
        "available": True, "navigation_status": 200, "navigation_timed_out": False,
        "title": "Images", "h1_count": 1, "meta_description": False,
        "image_count": 2, "images_missing_alt": 0, "images_empty_alt": 0,
        "broken_image_count": 0, "images_unverified_count": 2,
        "search_count": 0, "form_count": 0, "shop_signals": [], "links": [],
        "javascript_errors": [], "console_errors": [], "browser_blocked_resources": [],
        "failed_requests": [], "http_errors": [], "request_count": 4,
        "blocked_requests": 0, "allowed_requests": 4,
    })
    result = scan_public_url("https://example.com/")
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["Image loading"]["status"] == "info"
    assert "not counted as a broken-image warning" in checks["Image loading"]["detail"]


@pytest.mark.unit
def test_confirmed_image_http_failure_remains_a_warning(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    page = b'<html><head><title>Images</title></head><body><h1>Gallery</h1><img src="one.jpg" alt="One"></body></html>'

    def fake_request(method, url, **kwargs):
        return _FakeResponse(content=page)

    monkeypatch.setattr("dashboard.url_scanner.requests.request", fake_request)
    monkeypatch.setattr("dashboard.url_scanner._scan_in_browser", lambda url: {
        "available": True, "navigation_status": 200, "navigation_timed_out": False,
        "title": "Images", "h1_count": 1, "meta_description": False,
        "image_count": 1, "images_missing_alt": 0, "images_empty_alt": 0,
        "broken_image_count": 1, "images_unverified_count": 0,
        "search_count": 0, "form_count": 0, "shop_signals": [], "links": [],
        "javascript_errors": [], "console_errors": [], "browser_blocked_resources": [],
        "failed_requests": [], "http_errors": ["HTTP 404 /one.jpg"], "request_count": 4,
        "blocked_requests": 0, "allowed_requests": 4,
    })
    result = scan_public_url("https://example.com/")
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["Image loading"]["status"] == "warning"
    assert "HTTP or network error" in checks["Image loading"]["detail"]


@pytest.mark.unit
def test_browser_request_coverage_separates_attempted_allowed_and_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    page = b'<html><head><title>Coverage</title></head><body><h1>Coverage</h1></body></html>'

    def fake_request(method, url, **kwargs):
        return _FakeResponse(content=page)

    monkeypatch.setattr("dashboard.url_scanner.requests.request", fake_request)
    monkeypatch.setattr("dashboard.url_scanner._scan_in_browser", lambda url: {
        "available": True, "navigation_status": 200, "navigation_timed_out": False,
        "title": "Coverage", "h1_count": 1, "meta_description": False,
        "image_count": 0, "images_missing_alt": 0, "images_empty_alt": 0,
        "broken_image_count": 0, "images_unverified_count": 0,
        "search_count": 0, "form_count": 0, "shop_signals": [], "links": [],
        "javascript_errors": [], "console_errors": [], "browser_blocked_resources": [],
        "failed_requests": [], "http_errors": [], "request_count": 42,
        "blocked_requests": 3, "allowed_requests": 39,
    })
    result = scan_public_url("https://example.com/")
    coverage = result["coverage"]
    assert coverage["browser_requests_observed"] == 42
    assert coverage["browser_requests_allowed"] == 39
    assert coverage["browser_requests_blocked"] == 3
    assert coverage["browser_request_limit"] == 40


@pytest.mark.unit
def test_browser_failure_keeps_basic_html_results(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    html = b'<html><head><title>Example</title></head><body><h1>Welcome</h1><img src="hero.png" alt="Hero"></body></html>'

    def fake_request(method, url, **kwargs):
        return _FakeResponse(content=html)

    monkeypatch.setattr("dashboard.url_scanner.requests.request", fake_request)
    monkeypatch.setattr(
        "dashboard.url_scanner._scan_in_browser",
        lambda url: (_ for _ in ()).throw(ScanBrowserError("Chromium is not ready.")),
    )
    result = scan_public_url("https://example.com/")
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["Page title"]["status"] == "pass"
    assert checks["Main heading (H1)"]["status"] == "pass"
    assert checks["Browser check"]["status"] == "warning"
    assert checks["Image loading"]["status"] == "info"
    assert "could not be verified" in checks["Image loading"]["detail"].lower()
    assert result["browser_scan"] is False
    assert "HTML only" in result["note"]



@pytest.mark.unit
def test_no_same_host_links_are_reported_as_not_assessed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    html = b'<html><head><title>Standalone page</title></head><body><h1>Hello</h1><p>No links.</p></body></html>'

    def fake_request(method, url, **kwargs):
        return _FakeResponse(content=html)

    monkeypatch.setattr("dashboard.url_scanner.requests.request", fake_request)
    monkeypatch.setattr(
        "dashboard.url_scanner._scan_in_browser",
        lambda url: {
            "available": True, "navigation_status": 200, "navigation_timed_out": False,
            "title": "Standalone page", "h1_count": 1, "meta_description": False,
            "image_count": 0, "images_missing_alt": 0, "broken_image_count": 0,
            "search_count": 0, "form_count": 0, "shop_signals": [], "links": [],
            "javascript_errors": [], "failed_requests": [], "http_errors": [],
            "request_count": 3, "blocked_requests": 0,
        },
    )
    result = scan_public_url("https://example.com/")
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["Internal links"]["status"] == "info"
    assert "not assessed" in checks["Internal links"]["detail"].lower()


@pytest.mark.unit
def test_browser_javascript_and_resource_errors_are_reported():
    checks = []
    _add_browser_checks(
        checks,
        {
            "navigation_status": 200,
            "navigation_timed_out": False,
            "javascript_errors": ["TypeError: cannot read property"],
            "http_errors": ["404 /missing.js"],
            "failed_requests": ["/image.png"],
            "blocked_requests": 2,
        },
    )
    by_name = {check["name"]: check for check in checks}
    assert by_name["Browser page load"]["status"] == "pass"
    assert by_name["JavaScript errors"]["status"] == "warning"
    assert by_name["Browser resources"]["status"] == "warning"
    assert by_name["Safety limits"]["status"] == "info"
    assert "404 /missing.js" in by_name["Browser resources"]["detail"]


@pytest.mark.unit
def test_page_inspector_distinguishes_missing_alt_from_empty_decorative_alt():
    parser = _PageInspector()
    parser.feed('<img src="product.jpg"><img src="divider.svg" alt="">')
    parser.close()
    assert parser.image_count == 2
    assert parser.images_missing_alt == 1
    assert parser.images_empty_alt == 1


@pytest.mark.unit
def test_blocked_by_client_is_information_not_a_javascript_defect():
    checks = []
    _add_browser_checks(
        checks,
        {
            "navigation_status": 200,
            "navigation_timed_out": False,
            "javascript_errors": [],
            "console_errors": [],
            "http_errors": [],
            "failed_requests": [],
            "browser_blocked_resources": ["Failed to load resource: net::ERR_BLOCKED_BY_CLIENT"],
            "blocked_requests": 3,
        },
    )
    _enrich_checks(checks)
    by_name = {check["name"]: check for check in checks}
    assert by_name["JavaScript errors"]["status"] == "pass"
    assert by_name["Browser resources"]["status"] == "info"
    assert by_name["Browser resources"]["finding_type"] == "environment_signal"
    assert "not classified as a site defect" in by_name["Browser resources"]["detail"]
    assert by_name["Safety limits"]["finding_type"] == "scan_limit"


@pytest.mark.unit
def test_console_errors_are_separate_from_uncaught_javascript_exceptions():
    checks = []
    _add_browser_checks(
        checks,
        {
            "navigation_status": 200,
            "navigation_timed_out": False,
            "javascript_errors": [],
            "console_errors": ["Application warning: search endpoint returned empty results"],
            "http_errors": [],
            "failed_requests": [],
            "browser_blocked_resources": [],
            "blocked_requests": 0,
        },
    )
    _enrich_checks(checks)
    by_name = {check["name"]: check for check in checks}
    assert by_name["JavaScript errors"]["status"] == "pass"
    assert by_name["Browser console"]["status"] == "warning"
    assert by_name["Browser console"]["confidence"] == "medium"
    assert by_name["Browser console"]["next_step"]


@pytest.mark.unit
def test_scan_marks_non_html_as_not_applicable_not_site_failure(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)

    def fake_request(method, url, **kwargs):
        return _FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            content=b'{"ok": true}',
        )

    monkeypatch.setattr("dashboard.url_scanner.requests.request", fake_request)
    result = scan_public_url("https://example.com/api/health")
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["HTTP response"]["status"] == "pass"
    assert checks["HTML page"]["status"] == "info"
    assert checks["HTML page"]["finding_type"] == "not_tested"
    assert result["coverage"]["browser_inspected"] is False


@pytest.mark.unit
def test_scan_results_include_actionable_metadata(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    page = b'<html><head><title>Shop</title></head><body><h1>Products</h1><img src="x.png"></body></html>'

    def fake_request(method, url, **kwargs):
        return _FakeResponse(content=page)

    monkeypatch.setattr("dashboard.url_scanner.requests.request", fake_request)
    monkeypatch.setattr(
        "dashboard.url_scanner._scan_in_browser",
        lambda url: {
            "available": True, "navigation_status": 200, "navigation_timed_out": False,
            "title": "Shop", "h1_count": 1, "meta_description": False,
            "image_count": 1, "images_missing_alt": 1, "images_empty_alt": 0,
            "broken_image_count": 0, "search_count": 0, "form_count": 0,
            "shop_signals": [], "links": [], "javascript_errors": [],
            "console_errors": [], "browser_blocked_resources": [], "failed_requests": [],
            "http_errors": [], "request_count": 2, "blocked_requests": 0,
        },
    )
    result = scan_public_url("https://example.com/")
    checks = {check["name"]: check for check in result["checks"]}
    finding = checks["Image accessibility"]
    assert finding["finding_type"] == "potential_issue"
    assert finding["severity"] == "medium"
    assert finding["confidence"] == "medium"
    assert finding["impact"]
    assert finding["next_step"]
    assert result["coverage"]["browser_inspected"] is True
    assert result["coverage"]["max_links_checked"] == 3


@pytest.mark.unit
def test_http_resource_404_is_a_potential_issue_with_recommended_follow_up():
    checks = []
    _add_browser_checks(
        checks,
        {
            "navigation_status": 200,
            "navigation_timed_out": False,
            "javascript_errors": [],
            "console_errors": [],
            "http_errors": ["404 /missing.js"],
            "failed_requests": [],
            "browser_blocked_resources": [],
            "blocked_requests": 0,
        },
    )
    _enrich_checks(checks)
    resource_check = next(check for check in checks if check["name"] == "Browser resources")
    assert resource_check["status"] == "warning"
    assert resource_check["finding_type"] == "potential_issue"
    assert resource_check["severity"] == "medium"
    assert "Inspect each HTTP status" in resource_check["next_step"]


@pytest.mark.unit
def test_missing_meta_description_is_recommendation_not_a_functional_bug():
    checks = [{"name": "Meta description", "status": "info", "detail": "No meta description was found."}]
    _enrich_checks(checks)
    assert checks[0]["finding_type"] == "recommendation"
    assert checks[0]["severity"] == "low"
    assert checks[0]["confidence"] == "high"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("failure", "scanner_blocked", "expected_kind"),
    [
        ("net::ERR_BLOCKED_BY_CLIENT", False, "client_blocked"),
        ("net::ERR_ABORTED", False, "cancelled"),
        ("net::ERR_NAME_NOT_RESOLVED", False, "network_failure"),
        ("net::ERR_FAILED", True, "scanner_blocked"),
    ],
)
def test_browser_request_failures_are_classified_without_false_site_defects(failure, scanner_blocked, expected_kind):
    classification, evidence = _classify_failed_browser_request(
        "https://example.com/assets/app.js",
        "https://example.com/",
        failure,
        scanner_blocked=scanner_blocked,
    )
    assert classification == expected_kind
    assert (evidence is None) == (expected_kind in {"cancelled", "scanner_blocked"})
    if expected_kind in {"client_blocked", "network_failure"}:
        assert "/assets/app.js" in evidence


@pytest.mark.unit
def test_empty_alt_is_informational_recommendation_not_not_tested():
    checks = [{"name": "Image accessibility", "status": "info", "detail": "All images have an alt attribute; 2 use an empty alt value, which is valid for decorative images."}]
    _enrich_checks(checks)
    assert checks[0]["finding_type"] == "recommendation"
    assert checks[0]["severity"] == "low"
    assert checks[0]["confidence"] == "medium"


@pytest.mark.unit
def test_public_url_can_be_syntax_checked_without_dns_for_backup_restore(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: pytest.fail("DNS lookup was not expected"))
    assert validate_public_url("https://example.com/catalog", resolve_dns=False) == "https://example.com/catalog"
    with pytest.raises(ScanInputError, match="Local and private IP"):
        validate_public_url("http://127.0.0.1/", resolve_dns=False)
    with pytest.raises(ScanInputError, match="Local and private website addresses"):
        validate_public_url("https://router.local/", resolve_dns=False)
