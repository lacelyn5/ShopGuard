"""Low-impact, read-only URL smoke scanner for public websites.

This scanner intentionally avoids login, cart mutations, checkout and arbitrary
browser JavaScript. It checks a small amount of public HTML and a few same-host
links. In the temporary browser it allows only public GET/HEAD plus bounded,
read-only QUERY requests (RFC 10008) and their narrowly validated CORS preflight.
Network destinations are restricted to public HTTP(S) hosts to reduce SSRF risk
when the local dashboard accepts a URL from its UI.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

USER_AGENT = "ShopGuard-ReadOnly-URL-Scanner/1.0"
MAX_URL_LENGTH = 2048
MAX_HTML_BYTES = 1_000_000
MAX_REDIRECTS = 4
MAX_LINKS_TO_CHECK = 3
MAX_BROWSER_REQUESTS = 40
MAX_QUERY_BODY_BYTES = 16 * 1024
BROWSER_NAV_TIMEOUT_MS = 12_000
BROWSER_SETTLE_MS = 900
DYNAMIC_PRODUCT_WAIT_MS = 5_000
REQUEST_TIMEOUT = (2.5, 4.0)
REDIRECT_CODES = {301, 302, 303, 307, 308}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".test", ".invalid", ".example", ".onion")


class ScanInputError(ValueError):
    """Raised when a target URL is malformed or not a public web destination."""


class ScanRequestError(RuntimeError):
    """Raised when a public target cannot be fetched safely."""


class ScanBrowserError(RuntimeError):
    """Raised when the temporary Playwright browser cannot be started."""


def validate_public_url(value: str, *, resolve_dns: bool = True) -> str:
    """Validate and normalize a public HTTP(S) URL. Live requests should resolve DNS."""
    if not isinstance(value, str) or not value.strip():
        raise ScanInputError("Enter a website URL, for example https://example.com.")
    raw = value.strip()
    if len(raw) > MAX_URL_LENGTH:
        raise ScanInputError("The URL is too long (maximum 2048 characters).")
    if any(ord(char) < 32 for char in raw):
        raise ScanInputError("The URL contains invalid control characters.")
    if "://" not in raw:
        raw = "https://" + raw

    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ScanInputError("The URL format or port is invalid.") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ScanInputError("Only public HTTP and HTTPS websites can be scanned.")
    if not parsed.hostname:
        raise ScanInputError("Enter a valid website hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ScanInputError("URLs containing usernames or passwords are not allowed.")

    hostname = parsed.hostname.rstrip(".").lower()
    if not hostname or hostname == "localhost" or hostname.endswith(BLOCKED_SUFFIXES):
        raise ScanInputError("Local and private website addresses are blocked.")
    if port is not None and port != (443 if scheme == "https" else 80):
        raise ScanInputError("Only standard web ports 80 and 443 are allowed.")

    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ScanInputError("The hostname is invalid.") from exc

    try:
        literal_ip = ipaddress.ip_address(ascii_hostname.strip("[]"))
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if not literal_ip.is_global:
            raise ScanInputError("Local and private IP addresses are blocked.")
    else:
        if "." not in ascii_hostname or ".." in ascii_hostname:
            raise ScanInputError("Enter a public internet hostname.")
        if resolve_dns:
            try:
                answers = socket.getaddrinfo(ascii_hostname, port or (443 if scheme == "https" else 80), type=socket.SOCK_STREAM)
            except OSError as exc:
                raise ScanInputError("ShopGuard could not find this website address. Check the URL and try again.") from exc
            addresses = {answer[4][0].split("%", 1)[0] for answer in answers}
            if not addresses:
                raise ScanInputError("The hostname did not resolve to an IP address.")
            for address in addresses:
                try:
                    ip = ipaddress.ip_address(address)
                except ValueError as exc:
                    raise ScanInputError("The hostname resolved to an invalid IP address.") from exc
                if not ip.is_global:
                    raise ScanInputError("This address points to a local or reserved IP and cannot be checked.")

    netloc = f"[{ascii_hostname}]" if ":" in ascii_hostname else ascii_hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


class _PageInspector(HTMLParser):
    """Collect page structure and conservative e-commerce presence signals."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.meta_description = False
        self.image_count = 0
        self.images_missing_alt = 0
        self.images_empty_alt = 0
        self.forms = 0
        self.internal_link_candidates: list[str] = []
        self.search_control = False
        self.shop_signals: set[str] = set()
        self.shop_evidence: dict[str, int] = {}
        self._in_title = False
        self._h1_depth = 0
        self._text_capture: list[str] | None = None

    def _record_shop_signal(self, signal: str) -> None:
        self.shop_signals.add(signal)
        self.shop_evidence[signal] = self.shop_evidence.get(signal, 0) + 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_map = {key.lower(): (value or "") for key, value in attrs}
        if tag == "title":
            self._in_title = True
        if tag == "h1":
            self._h1_depth += 1
            self._text_capture = []
        if tag == "meta" and attrs_map.get("name", "").lower() == "description":
            self.meta_description = bool(attrs_map.get("content", "").strip())
        if tag == "img":
            self.image_count += 1
            # A missing alt attribute differs from alt="", which is valid for
            # decorative images and should not automatically be called a defect.
            if "alt" not in attrs_map:
                self.images_missing_alt += 1
            elif not attrs_map.get("alt", "").strip():
                self.images_empty_alt += 1
        if tag == "form":
            self.forms += 1
        if tag == "a" and attrs_map.get("href"):
            self.internal_link_candidates.append(attrs_map["href"].strip())

        search_attrs = " ".join((attrs_map.get("type", ""), attrs_map.get("name", ""), attrs_map.get("placeholder", ""), attrs_map.get("aria-label", ""), attrs_map.get("role", ""))).lower()
        if tag == "input" and "search" in search_attrs:
            self.search_control = True
        elif tag in {"button", "a"} and "search" in search_attrs:
            self.search_control = True

        # Attribute-based signals include stable test hooks such as the
        # Toolshop's [data-test="product-name"], which the main UI smoke suite
        # already uses. Class/id-only matching missed these markers before.
        test_markers = " ".join((
            attrs_map.get("data-test", ""), attrs_map.get("data-testid", ""),
            attrs_map.get("data-cy", ""), attrs_map.get("data-qa", ""),
        )).lower()
        descriptive_attrs = " ".join((
            tag, attrs_map.get("href", ""), attrs_map.get("class", ""),
            attrs_map.get("id", ""), attrs_map.get("aria-label", ""),
            attrs_map.get("title", ""), attrs_map.get("itemprop", ""),
            attrs_map.get("itemtype", ""), attrs_map.get("property", ""),
            test_markers,
        )).lower()

        product_marker = bool(
            re.search(
                r"\bproduct[-_ ]?(?:name|card|item|tile|title|grid|list|detail)\b|\bproducts\b|\bcatalog(?:ue)?(?:[-_ ]?(?:item|card|grid|list))?\b",
                descriptive_attrs,
            )
            or re.search(r"/products?(?:/|$)", attrs_map.get("href", ""), re.IGNORECASE)
        )
        product_schema = "schema.org/product" in attrs_map.get("itemtype", "").lower()
        if product_marker or product_schema:
            self._record_shop_signal("product/catalog elements")

        price_marker = (
            "price" in attrs_map.get("itemprop", "").lower()
            or "price" in attrs_map.get("property", "").lower()
            or "price" in attrs_map.get("class", "").lower()
            or "price" in attrs_map.get("id", "").lower()
            or "price" in test_markers
            or "data-price" in attrs_map
        )
        if price_marker:
            self._record_shop_signal("price indicators")

        control_attrs = " ".join((
            attrs_map.get("href", ""), attrs_map.get("class", ""),
            attrs_map.get("id", ""), attrs_map.get("aria-label", ""),
            attrs_map.get("title", ""), test_markers,
        )).lower()
        is_control = tag in {"a", "button", "input"} or attrs_map.get("role", "").lower() in {"button", "link"}
        if is_control and re.search(r"(?:cart|basket|shopping[-_ ]?bag)", control_attrs):
            self._record_shop_signal("cart/basket controls")
        if re.search(r"add[-_ ]?to[-_ ]?(?:cart|basket|bag)", control_attrs):
            self._record_shop_signal("add-to-cart controls")
        if re.search(r"(?:checkout|payment)", descriptive_attrs):
            self._record_shop_signal("checkout/payment navigation")
        if "schema.org/product" in attrs_map.get("itemtype", "").lower():
            self._record_shop_signal("e-commerce structured data")
        if tag == "meta" and re.search(r"product:price|og:type", attrs_map.get("property", "").lower()):
            if "product:price" in attrs_map.get("property", "").lower():
                self._record_shop_signal("price indicators")
            elif attrs_map.get("content", "").lower() == "product":
                self._record_shop_signal("e-commerce structured data")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
            if self._text_capture is not None:
                text = " ".join("".join(self._text_capture).split())
                if text:
                    self.h1_parts.append(text)
                self._text_capture = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._h1_depth and self._text_capture is not None:
            self._text_capture.append(data)
        lowered = data.lower()
        if re.search(r"(?:[$€£]\s?\d|\bzł\s?\d|\b(?:price|sale|discount)\s?\d)", lowered):
            self._record_shop_signal("price indicators")
        if re.search(r"add to (?:cart|basket|bag)|shopping cart", lowered):
            self._record_shop_signal("cart/basket controls")
            self._record_shop_signal("add-to-cart controls")
        if re.search(r"\b(?:checkout|payment)\b", lowered):
            self._record_shop_signal("checkout/payment navigation")

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())


def _request_follow_safe(url: str, method: str = "GET") -> tuple[requests.Response, str, int]:
    current = validate_public_url(url)
    redirects = 0
    while True:
        # Revalidate every redirect target; never allow requests to follow a redirect blindly.
        current = validate_public_url(current)
        try:
            response = requests.request(
                method,
                current,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"},
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise ScanRequestError(f"Could not load {current}: {exc.__class__.__name__}.") from exc

        if response.status_code not in REDIRECT_CODES or not response.headers.get("Location"):
            return response, current, redirects
        location = response.headers.get("Location", "")
        response.close()
        if redirects >= MAX_REDIRECTS:
            raise ScanRequestError("The website exceeded the redirect limit.")
        current = urljoin(current, location)
        # Validate immediately so an unsafe redirect is reported without a request.
        current = validate_public_url(current)
        redirects += 1


def _read_limited(response: requests.Response) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    try:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            remaining = MAX_HTML_BYTES - total
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                truncated = True
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= MAX_HTML_BYTES:
                truncated = True
                break
    finally:
        response.close()
    return b"".join(chunks), truncated


def _same_host(left: str, right: str) -> bool:
    a, b = urlsplit(left), urlsplit(right)
    return (a.hostname or "").lower() == (b.hostname or "").lower() and (a.port or (443 if a.scheme == "https" else 80)) == (b.port or (443 if b.scheme == "https" else 80))


def _link_status(url: str) -> tuple[int | None, str | None]:
    try:
        response, final_url, _ = _request_follow_safe(url, "HEAD")
        status = response.status_code
        response.close()
        if status in {405, 501}:
            response, final_url, _ = _request_follow_safe(url, "GET")
            status = response.status_code
            response.close()
        return status, None
    except (ScanInputError, ScanRequestError) as exc:
        return None, str(exc)



def _classify_failed_browser_request(
    url: str,
    target_url: str,
    failure: str,
    scanner_blocked: bool = False,
) -> tuple[str, str | None]:
    """Classify one failed browser request without over-reporting scan blocks.

    Returns (classification, evidence). A None evidence value means the request
    was intentionally skipped or canceled and should not be counted as a site
    resource failure.
    """
    if scanner_blocked:
        return "scanner_blocked", None
    label = _resource_label(url, target_url)
    reason = " ".join(str(failure or "request failed").split())[:160]
    lowered = reason.lower()
    if "err_blocked_by_client" in lowered or "blockedbyclient" in lowered:
        return "client_blocked", f"{label} ({reason})"
    if "err_aborted" in lowered or "err_canceled" in lowered or "err_cancelled" in lowered:
        return "cancelled", None
    return "network_failure", f"{label} ({reason})"

def _browser_resource_allowed(
    url: str,
    method: str,
    is_main_document: bool,
    target_url: str,
    request_headers: dict[str, str] | None = None,
    request_body: bytes | str | None = None,
) -> bool:
    """Allow bounded, public, read-only browser requests in the temporary context.

    Besides GET/HEAD, the scanner supports the standardized safe/idempotent
    HTTP QUERY method (RFC 10008). Some modern SPAs use QUERY with a small JSON
    body to load catalog data. Cross-origin QUERY requires a matching CORS
    preflight (OPTIONS), which is permitted only for that exact page origin.
    State-changing methods such as POST/PUT/PATCH/DELETE remain blocked.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False

    scheme = parsed.scheme.lower()
    normalized_method = str(method or "").upper()
    headers = {str(key).lower(): str(value) for key, value in (request_headers or {}).items()}
    if scheme in {"data", "blob", "about"}:
        return not is_main_document
    if scheme not in {"http", "https"}:
        return False

    try:
        checked_url = validate_public_url(url)
    except ScanInputError:
        return False

    # JavaScript redirects and popups must not send the main page to another host.
    if is_main_document and not _same_host(target_url, checked_url):
        return False

    if normalized_method in {"GET", "HEAD"}:
        return True

    target = urlsplit(target_url)
    expected_origin = f"{target.scheme.lower()}://{target.netloc.lower()}"
    request_origin = headers.get("origin", "").rstrip("/").lower()
    same_page_origin = bool(request_origin) and request_origin == expected_origin

    if normalized_method == "OPTIONS":
        # Only allow the browser's CORS preflight for the safe QUERY request.
        # General OPTIONS requests are not needed by this scanner.
        return (
            not is_main_document
            and same_page_origin
            and headers.get("access-control-request-method", "").upper() == "QUERY"
        )

    if normalized_method == "QUERY":
        if is_main_document:
            return False
        # For cross-origin queries require the browser Origin to match the page
        # being scanned. This prevents arbitrary page scripts from using the
        # scanner to send QUERY requests with a forged/missing origin.
        if not _same_host(target_url, checked_url) and not same_page_origin:
            return False
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"application/json", "application/x-www-form-urlencoded"}:
            return False
        if isinstance(request_body, str):
            body_size = len(request_body.encode("utf-8"))
        elif isinstance(request_body, (bytes, bytearray)):
            body_size = len(request_body)
        else:
            body_size = 0
        return 0 < body_size <= MAX_QUERY_BODY_BYTES

    return False


def _resource_label(url: str, target_url: str) -> str:
    """Return a short URL label without query strings or fragments."""
    parsed = urlsplit(url)
    target_host = (urlsplit(target_url).hostname or "").lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    if host and host != target_host:
        return f"{host}{path}"[:110]
    return path[:110]


def _wait_for_dynamic_product_markers(page, timeout_ms: int = DYNAMIC_PRODUCT_WAIT_MS) -> bool:
    """Wait briefly for SPA-rendered product cards before classifying store signals.

    The Toolshop UI smoke suite waits up to 20 seconds for its product-name
    marker. A short URL scan used to inspect the page after only 900 ms, which
    could miss products populated asynchronously. This bounded wait looks for
    visible product/catalog elements only; it never clicks or submits anything.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    product_ready_script = r"""() => {
      const visible = (el) => {
        const style = window.getComputedStyle(el);
        const box = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) !== 0 && box.width > 0 && box.height > 0;
      };
      const selectors = [
        '[data-test="product-name" i]', '[data-testid="product-name" i]',
        '[data-test*="product-card" i]', '[data-testid*="product-card" i]',
        '[data-test*="product-item" i]', '[data-testid*="product-item" i]',
        '[data-cy*="product-card" i]', '[data-qa*="product-card" i]',
        '[itemtype*="schema.org/Product" i]',
        '[class*="product-card" i]', '[class*="product-item" i]',
        '[class*="product-grid" i]', '[class*="product-list" i]',
        'a[href*="/product/" i]', 'a[href*="/products/" i]'
      ].join(',');
      return [...document.querySelectorAll(selectors)].some(visible);
    }"""
    try:
        page.wait_for_function(product_ready_script, timeout=timeout_ms, polling=200)
        return True
    except PlaywrightTimeoutError:
        # A non-commerce page (or a page with unsupported/custom markers) is
        # still a valid scan target; continue with the available observations.
        return False


def _scan_in_browser(url: str) -> dict:
    """Inspect the rendered page in a fresh, short-lived Chromium context.

    The browser has no saved cookies or credentials. Every HTTP(S) request is
    checked before it is allowed. GET/HEAD and bounded safe QUERY are allowed,
    along with a validated QUERY CORS preflight; state-changing methods remain
    blocked. Service workers and downloads are disabled and request count is
    limited. No buttons are clicked and no forms are submitted.
    """
    start = time.monotonic()
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ScanBrowserError(
            "The browser tools are missing. Run scripts\\setup_windows.bat and try again."
        ) from exc

    target_host = (urlsplit(url).hostname or "").lower()
    request_count = 0
    blocked_requests = 0
    scanner_blocked_urls: set[str] = set()
    javascript_errors: list[str] = []
    console_errors: list[str] = []
    browser_blocked_resources: list[str] = []
    failed_requests: list[str] = []
    failed_image_requests: list[str] = []
    http_errors: list[str] = []
    navigation_status: int | None = None
    navigation_timed_out = False
    dom: dict = {}
    collect_page_events = [True]

    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                raise ScanBrowserError(
                    "The browser is not installed yet. Run scripts\\setup_windows.bat, then try again."
                ) from exc

            try:
                context = browser.new_context(
                    accept_downloads=False,
                    service_workers="block",
                    ignore_https_errors=False,
                    viewport={"width": 1365, "height": 768},
                    locale="en-US",
                )
                page = context.new_page()
                page.set_default_navigation_timeout(BROWSER_NAV_TIMEOUT_MS)
                page.set_default_timeout(2500)
                page.on("popup", lambda popup: popup.close())

                def guard_request(route) -> None:
                    nonlocal request_count, blocked_requests
                    request = route.request
                    request_count += 1
                    is_main_document = False
                    try:
                        is_main_document = (
                            request.is_navigation_request()
                            and request.resource_type == "document"
                            and request.frame.parent_frame is None
                        )
                    except Exception:
                        # Fail closed if Playwright cannot identify the frame.
                        is_main_document = request.is_navigation_request() and request.resource_type == "document"

                    try:
                        request_body = request.post_data_buffer
                    except Exception:
                        request_body = None
                    if request_count > MAX_BROWSER_REQUESTS or not _browser_resource_allowed(
                        request.url, request.method, is_main_document, url,
                        request_headers=request.headers, request_body=request_body,
                    ):
                        blocked_requests += 1
                        scanner_blocked_urls.add(request.url)
                        try:
                            route.abort("blockedbyclient")
                        except PlaywrightError:
                            pass
                        return
                    try:
                        route.continue_()
                    except PlaywrightError:
                        blocked_requests += 1
                        try:
                            route.abort("failed")
                        except PlaywrightError:
                            pass

                context.route("**/*", guard_request)

                def on_page_error(error) -> None:
                    if not collect_page_events[0]:
                        return
                    message = " ".join(str(error).split())[:180]
                    if message and message not in javascript_errors and len(javascript_errors) < 4:
                        javascript_errors.append(message)

                def on_console(message) -> None:
                    if not collect_page_events[0] or message.type != "error":
                        return
                    text = " ".join(message.text.split())[:220]
                    if not text:
                        return
                    lowered = text.lower()
                    # Chromium often logs blocked network resources as console
                    # errors. They are not JavaScript exceptions and should not
                    # be presented as proof that the site's code is broken.
                    if "err_blocked_by_client" in lowered or "blockedbyclient" in lowered:
                        if text not in browser_blocked_resources and len(browser_blocked_resources) < 5:
                            browser_blocked_resources.append(text)
                    elif lowered.startswith("failed to load resource:") or "net::err_" in lowered:
                        # URL/reason-level diagnostics are collected via
                        # requestfailed; avoid duplicating a generic console line.
                        return
                    elif text not in console_errors and len(console_errors) < 5:
                        console_errors.append(text)

                def on_failed_request(request) -> None:
                    if not collect_page_events[0]:
                        return
                    try:
                        classification, detail = _classify_failed_browser_request(
                            request.url,
                            url,
                            str(getattr(request, "failure", None) or "request failed"),
                            scanner_blocked=request.url in scanner_blocked_urls,
                        )
                        resource_type = str(getattr(request, "resource_type", "") or "").lower()
                        if classification == "client_blocked" and detail:
                            if detail not in browser_blocked_resources and len(browser_blocked_resources) < 5:
                                browser_blocked_resources.append(detail)
                            return
                        if classification != "network_failure" or not detail:
                            # Scanner policy blocks and canceled navigation/teardown
                            # requests are not evidence of a target-site failure.
                            return
                        if resource_type == "image" and detail not in failed_image_requests and len(failed_image_requests) < 10:
                            failed_image_requests.append(detail)
                        if _same_host(url, request.url):
                            if detail not in failed_requests and len(failed_requests) < 5:
                                failed_requests.append(detail)
                    except Exception:
                        pass

                def on_response(response) -> None:
                    if not collect_page_events[0]:
                        return
                    try:
                        if response.status >= 400:
                            resource_type = str(getattr(response.request, "resource_type", "") or "").lower()
                            label = f"HTTP {response.status} {_resource_label(response.url, url)}"
                            if resource_type == "image" and label not in failed_image_requests and len(failed_image_requests) < 10:
                                failed_image_requests.append(label)
                            if _same_host(url, response.url):
                                if label not in http_errors and len(http_errors) < 5:
                                    http_errors.append(label)
                    except Exception:
                        pass

                page.on("pageerror", on_page_error)
                page.on("console", on_console)
                page.on("requestfailed", on_failed_request)
                page.on("response", on_response)

                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_NAV_TIMEOUT_MS)
                    if response is not None:
                        navigation_status = response.status
                except PlaywrightTimeoutError:
                    navigation_timed_out = True
                except PlaywrightError as exc:
                    raise ScanBrowserError(
                        "The browser could not open this page. The basic website check is still available."
                    ) from exc

                # Give client-side scripts a short chance to add page content.
                # Then explicitly wait for the same stable product markers used
                # by the Toolshop UI tests. The helper existed in earlier builds
                # but was not called, so its 5-second wait never affected scans.
                try:
                    page.wait_for_timeout(BROWSER_SETTLE_MS)
                    _wait_for_dynamic_product_markers(page)
                    dom = page.evaluate(
                        r"""() => {
                          const visible = (el) => {
                            const style = window.getComputedStyle(el);
                            const box = el.getBoundingClientRect();
                            return style.display !== 'none' && style.visibility !== 'hidden' &&
                              Number(style.opacity) !== 0 && box.width > 0 && box.height > 0;
                          };
                          const visibleH1 = [...document.querySelectorAll('h1')].filter(visible);
                          const imgs = [...document.images];
                          const searchSelector = [
                            'input[type="search"]',
                            'input[name*="search" i]',
                            'input[placeholder*="search" i]',
                            'input[aria-label*="search" i]',
                            'button[aria-label*="search" i]',
                            '[role="search"]'
                          ].join(',');
                          const searchCount = [...document.querySelectorAll(searchSelector)].filter(visible).length;
                          const bodyText = document.body ? (document.body.innerText || '') : '';
                          const signals = new Set();
                          const evidence = {};
                          const addSignal = (name, count) => {
                            if (count > 0) {
                              signals.add(name);
                              evidence[name] = Math.min(Number(count) || 1, 999);
                            }
                          };
                          const visibleMatches = (selector) => [...document.querySelectorAll(selector)].filter(visible);
                          // Stable semantic/test attributes are more reliable than
                          // framework-generated class names. In particular, the
                          // Toolshop app exposes [data-test="product-name"].
                          const productSelector = [
                            '[data-test="product-name" i]', '[data-testid="product-name" i]',
                            '[data-test*="product-card" i]', '[data-testid*="product-card" i]',
                            '[data-test*="product-item" i]', '[data-testid*="product-item" i]',
                            '[data-cy*="product-card" i]', '[data-qa*="product-card" i]',
                            '[itemtype*="schema.org/Product" i]', 
                            '[class*="product-card" i]', '[class*="product-item" i]',
                            '[class*="product-grid" i]', '[class*="product-list" i]',
                            'a[href*="/product/" i]', 'a[href*="/products/" i]',
                            'a[href*="/catalog" i]'
                          ].join(',');
                          const productMarkers = visibleMatches(productSelector);
                          addSignal('product/catalog elements', productMarkers.length);

                          const priceSelector = [
                            '[data-test*="price" i]', '[data-testid*="price" i]',
                            '[data-cy*="price" i]', '[data-qa*="price" i]',
                            '[itemprop="price" i]', '[data-price]',
                            '[class*="price" i]', '[id*="price" i]',
                            'meta[property*="product:price" i]'
                          ].join(',');
                          const priceMarkers = [...document.querySelectorAll(priceSelector)].filter(el => el.tagName === 'META' || visible(el));
                          const hasVisiblePriceText = /(?:[$€£]\s?\d|\bzł\s?\d|\bUSD\s?\d|\bprice\s?\d)/i.test(bodyText);
                          addSignal('price indicators', Math.max(priceMarkers.length, hasVisiblePriceText ? 1 : 0));

                          const controls = [...document.querySelectorAll('a,button,input,[role="button"],[role="link"],[data-test],[data-testid],[data-cy],[data-qa]')].filter(visible);
                          const controlDescription = (el) => [
                            el.innerText || el.textContent || '', el.getAttribute('aria-label') || '',
                            el.getAttribute('title') || '', el.getAttribute('href') || '',
                            el.getAttribute('class') || '', el.id || '',
                            el.getAttribute('data-test') || '', el.getAttribute('data-testid') || '',
                            el.getAttribute('data-cy') || '', el.getAttribute('data-qa') || ''
                          ].join(' ').toLowerCase();
                          const descriptions = controls.map(controlDescription);
                          const cartCount = descriptions.filter(value => /cart|basket|shopping[-_ ]?bag/.test(value)).length;
                          const addToCartCount = descriptions.filter(value => /add[-_ ]?to[-_ ]?(cart|basket|bag)/.test(value)).length;
                          const checkoutCount = descriptions.filter(value => /checkout|payment/.test(value)).length;
                          addSignal('cart/basket controls', cartCount);
                          addSignal('add-to-cart controls', addToCartCount);
                          addSignal('checkout/payment navigation', checkoutCount);

                          const structuredProduct = [...document.querySelectorAll('script[type="application/ld+json"]')]
                            .some(script => /"@type"\s*:\s*"[^"]*(Product|Offer|AggregateOffer)\b/i.test(script.textContent || ''));
                          const productMeta = document.querySelector('meta[property="og:type" i][content="product" i]');
                          addSignal('e-commerce structured data', structuredProduct || productMeta ? 1 : 0);
                          const meta = document.querySelector('meta[name="description" i]');
                          return {
                            title: (document.title || '').trim(),
                            h1Count: visibleH1.length,
                            metaDescription: !!(meta && (meta.content || '').trim()),
                            imageCount: imgs.length,
                            imagesMissingAlt: imgs.filter(img => !img.hasAttribute('alt')).length,
                            imagesEmptyAlt: imgs.filter(img => img.hasAttribute('alt') && !img.getAttribute('alt').trim()).length,
                            imageLoadUnverifiedCount: imgs.filter(img => (img.currentSrc || img.getAttribute('src')) && (!img.complete || img.naturalWidth === 0)).length,
                            searchCount,
                            formCount: document.forms.length,
                            shopSignals: [...signals],
                            shopEvidence: evidence,
                            links: [...document.querySelectorAll('a[href]')].map(a => a.href).filter(Boolean).slice(0, 80)
                          };
                        }"""
                    )
                except PlaywrightError:
                    dom = {}
                finally:
                    # Ignore requests that are cancelled when the short scan closes the page.
                    collect_page_events[0] = False

                context.close()
            finally:
                browser.close()
    except ScanBrowserError:
        raise
    except Exception as exc:
        raise ScanBrowserError(
            "The browser check could not finish. The basic website check is still available."
        ) from exc

    if not dom:
        raise ScanBrowserError(
            "The browser opened the site but could not read its page content. Check the site manually."
        )

    return {
        "available": True,
        "navigation_status": navigation_status,
        "navigation_timed_out": navigation_timed_out,
        "title": str(dom.get("title") or "")[:200],
        "h1_count": int(dom.get("h1Count") or 0),
        "meta_description": bool(dom.get("metaDescription")),
        "image_count": int(dom.get("imageCount") or 0),
        "images_missing_alt": int(dom.get("imagesMissingAlt") or 0),
        "images_empty_alt": int(dom.get("imagesEmptyAlt") or 0),
        # Only count confirmed HTTP/network image request failures as broken.
        # A DOM image with naturalWidth=0 at a single snapshot can still be
        # loading, lazy-loaded, or blocked by the browser/client policy.
        "broken_image_count": len(failed_image_requests),
        "images_unverified_count": max(0, int(dom.get("imageLoadUnverifiedCount") or 0) - len(failed_image_requests)),
        "failed_image_requests": failed_image_requests,
        "search_count": int(dom.get("searchCount") or 0),
        "form_count": int(dom.get("formCount") or 0),
        "shop_signals": [str(item) for item in dom.get("shopSignals", [])[:10]],
        "shop_evidence": {str(key): int(value) for key, value in (dom.get("shopEvidence") or {}).items() if str(key)[:80]},
        "links": [str(item) for item in dom.get("links", [])[:80]],
        "javascript_errors": javascript_errors,
        "console_errors": console_errors,
        "browser_blocked_resources": browser_blocked_resources,
        "failed_requests": failed_requests,
        "http_errors": http_errors,
        "request_count": request_count,
        "blocked_requests": blocked_requests,
        "allowed_requests": max(0, request_count - blocked_requests),
        "duration_ms": round((time.monotonic() - start) * 1000),
        "target_host": target_host,
    }


def _add_browser_checks(checks: list[dict[str, str]], browser_data: dict) -> None:
    """Add browser findings without treating scanner/browser blocks as site bugs."""
    status = browser_data.get("navigation_status")
    timed_out = bool(browser_data.get("navigation_timed_out"))
    if timed_out:
        checks.append({
            "name": "Browser page load",
            "status": "warning",
            "detail": "The page did not finish its initial load within the time limit. Some results may be missing.",
        })
    elif status is None:
        checks.append({
            "name": "Browser page load",
            "status": "info",
            "detail": "The browser did not provide a clear navigation response, so browser-page availability could not be confirmed.",
        })
    elif 200 <= status < 400:
        checks.append({
            "name": "Browser page load",
            "status": "pass",
            "detail": f"The page opened in the test browser (HTTP {status}).",
        })
    elif status in {401, 403, 429}:
        checks.append({
            "name": "Browser page load",
            "status": "warning",
            "detail": f"The browser received HTTP {status}. Authentication, rate limiting or bot protection may affect this result; confirm in a normal browser.",
        })
    else:
        checks.append({
            "name": "Browser page load",
            "status": "warning",
            "detail": f"The browser received HTTP {status}. Confirm whether this response is expected for the selected page.",
        })

    errors = browser_data.get("javascript_errors") or []
    if errors:
        details = " | ".join(str(item)[:160] for item in errors[:3])
        checks.append({
            "name": "JavaScript errors",
            "status": "warning",
            "detail": f"The browser reported uncaught JavaScript exception(s): {details}",
        })
    else:
        checks.append({
            "name": "JavaScript errors",
            "status": "pass",
            "detail": "No uncaught JavaScript exceptions were seen during the short check.",
        })

    console_errors = browser_data.get("console_errors") or []
    if console_errors:
        details = " | ".join(str(item)[:140] for item in console_errors[:3])
        checks.append({
            "name": "Browser console",
            "status": "warning",
            "detail": f"The browser console reported error message(s): {details}. Console output can include handled or non-critical errors; verify before reporting a defect.",
        })

    http_errors = list(browser_data.get("http_errors") or [])
    failed_requests = list(browser_data.get("failed_requests") or [])
    blocked_resources = list(browser_data.get("browser_blocked_resources") or [])
    request_issues = http_errors + failed_requests
    if request_issues:
        checks.append({
            "name": "Browser resources",
            "status": "warning",
            "detail": "Resource request(s) returned HTTP errors or failed at the network layer: " + "; ".join(str(item)[:150] for item in request_issues[:4]) + ". Inspect the individual response/reason; a transient network error does not by itself prove an application defect.",
        })
    elif blocked_resources:
        checks.append({
            "name": "Browser resources",
            "status": "info",
            "detail": "The browser reported resource(s) blocked by client-side rules: " + "; ".join(str(item)[:120] for item in blocked_resources[:3]) + ". This may come from browser policy or scanning protections and is not classified as a site defect.",
        })
    else:
        checks.append({
            "name": "Browser resources",
            "status": "pass",
            "detail": "No failed same-host resource requests were observed during the short check.",
        })

    blocked = int(browser_data.get("blocked_requests") or 0)
    if blocked:
        checks.append({
            "name": "Safety limits",
            "status": "info",
            "detail": f"ShopGuard intentionally skipped {blocked} request(s) because of its public-site safety rules or request limit. These skipped requests are excluded from site-failure counts.",
        })


def _enrich_checks(checks: list[dict[str, str]]) -> None:
    """Attach actionable guidance and confidence to every scan check.

    The classification describes the strength and meaning of a scanner signal;
    it deliberately does not claim to prove a defect solely from a heuristic.
    """
    guidance = {
        "HTTP response": ("Availability", "Check whether the response is expected for an anonymous visitor. Retry once before filing a defect.", "A non-success response can indicate downtime, access rules or bot protection."),
        "HTTPS": ("Transport security", "Use HTTPS for public pages and redirect HTTP traffic to HTTPS.", "Unencrypted transport exposes page traffic to interception."),
        "HTML page": ("Scan applicability", "Use the relevant API or file check for JSON, PDF or other non-HTML resources; use this scanner for public HTML pages.", "Page structure checks apply to HTML. A non-HTML response is not a defect by itself."),
        "HTML parsing": ("Content", "Inspect the saved response in a browser or HTML validator.", "Malformed or truncated markup can make automated observations incomplete."),
        "Page title": ("SEO / usability", "Add a concise, page-specific title if this page is intended for public browsing.", "A missing title can harm accessibility and search-result clarity."),
        "Main heading (H1)": ("Structure / accessibility", "Confirm whether the page should expose a visible main heading; avoid treating app-like pages as defects without context.", "A missing main heading can make page structure harder to understand."),
        "Meta description": ("SEO recommendation", "Consider adding a concise description if search snippets matter for this page.", "This is generally an SEO recommendation, not a functional defect."),
        "Image accessibility": ("Accessibility", "Check each affected image: informative images need meaningful alt text; an empty alt attribute is valid for decorative images.", "Missing alt attributes can prevent assistive technology from conveying image content."),
        "Image loading": ("Content / network", "Reload the page and verify the specific image URL; slow or lazy-loaded images may need a second check.", "Broken images can hide product or instructional content."),
        "Internal links": ("Navigation", "Open the reported URL in a normal browser and verify the expected route and access policy.", "Broken same-host links can prevent users reaching a page; 4xx responses can also be intentional."),
        "Search control": ("Functional coverage", "Search was not exercised. If search is important, add a dedicated test for opening the search UI and submitting a query.", "Presence detection does not prove search works; a hidden or icon-triggered search may not be detected."),
        "Store features": ("Functional coverage", "Review the detected HTML/DOM markers, then verify important product, cart and checkout behavior with dedicated read-only or authorised functional tests.", "Presence of product, price or cart markers does not prove the associated workflow works; no controls are activated by this scan."),
        "Forms": ("Functional coverage", "Forms were not submitted. Test validation and submission only in an authorised test environment.", "The scan only counts forms and does not validate their behavior."),
        "Redirects": ("Navigation", "Review the final URL if the redirect is unexpected.", "Redirects can be normal and are recorded for context."),
        "Scan coverage": ("Coverage limitation", "Repeat with a more focused manual test if important content may occur after the HTML limit.", "Truncated HTML can hide elements from static inspection."),
        "Browser page load": ("Browser availability", "Retry in a normal browser and check the target site's response and bot-protection policy.", "A timeout or access denial may reflect network policy rather than a site defect."),
        "JavaScript errors": ("Runtime behavior", "Reproduce the exception in a normal browser and inspect its stack trace before reporting a defect.", "An uncaught exception may break client-side behavior, but short scans cannot determine user impact."),
        "Browser console": ("Runtime diagnostics", "Inspect the full console message and reproduce it; a console error alone does not establish a user-visible defect.", "Some console errors are handled, non-critical or caused by third-party resources."),
        "Browser resources": ("Network diagnostics", "Inspect each HTTP status or network failure; retry transient failures and distinguish target responses from client-side blocking.", "Failed assets or API calls can affect the page, but a short scan cannot prove their impact."),
        "Safety limits": ("Coverage limitation", "No action needed for expected safety blocks. Use the separate authorised test suite if a skipped request is essential.", "Requests blocked by ShopGuard are intentionally not treated as site defects."),
        "Browser check": ("Scanner limitation", "Install/update Playwright Chromium and retry; HTML-only findings remain limited.", "Without browser inspection, JavaScript-rendered content and resource behavior are not assessed."),
    }
    not_tested_names = {"Search control", "Store features", "Forms"}
    limitation_names = {"Scan coverage", "Safety limits", "Browser check"}
    context_names = {"Browser page load", "Browser resources"}
    recommendation_names = {"Meta description", "Page title", "Main heading (H1)"}

    for check in checks:
        name = str(check.get("name", ""))
        status = str(check.get("status", "info"))
        category, next_step, impact = guidance.get(
            name,
            ("General", "Review the observation and reproduce it before filing a defect.", "The scanner provides a signal, not a complete functional test."),
        )
        if status == "pass":
            finding_type, severity, confidence = "check_passed", "none", "high"
        elif name == "Image accessibility" and status == "info" and "empty alt value" in str(check.get("detail", "")).lower():
            finding_type, severity, confidence = "recommendation", "low", "medium"
        elif name in recommendation_names and status in {"warning", "info"}:
            finding_type, severity, confidence = "recommendation", "low", "high"
        elif name in limitation_names:
            finding_type, severity, confidence = "scan_limit", "none", "high"
        elif name == "Internal links" and status == "warning" and "server error" in str(check.get("detail", "")).lower():
            finding_type, severity, confidence = "potential_issue", "medium", "medium"
        elif name == "Browser resources" and status == "warning" and re.search(r"\b(?:404|410|5\d{2})\b", str(check.get("detail", ""))):
            finding_type, severity, confidence = "potential_issue", "medium", "medium"
        elif name in context_names or (name == "HTTP response" and status == "warning") or (name == "Internal links" and status == "warning"):
            finding_type, severity, confidence = "environment_signal", "low" if status != "fail" else "medium", "medium"
        elif name in not_tested_names or (status == "info" and name not in {"Redirects", "Safety limits"}):
            finding_type, severity, confidence = "not_tested", "none", "none"
        elif name == "Image loading" and status == "warning":
            finding_type, severity, confidence = "potential_issue", "low", "medium"
        elif status == "fail":
            finding_type, severity, confidence = "potential_issue", "high", "high"
        elif status == "warning":
            finding_type, severity, confidence = "potential_issue", "medium", "medium"
        else:
            finding_type, severity, confidence = "information", "none", "high"

        check.update({
            "category": category,
            "finding_type": finding_type,
            "severity": severity,
            "confidence": confidence,
            "impact": impact,
            "next_step": next_step,
        })

def _replace_or_add_check(checks: list[dict[str, str]], name: str, status: str, detail: str) -> None:
    replacement = {"name": name, "status": status, "detail": detail}
    for index, check in enumerate(checks):
        if check["name"] == name:
            checks[index] = replacement
            return
    checks.append(replacement)


def scan_public_url(value: str) -> dict:
    """Run a bounded, read-only smoke scan of a public page."""
    start = time.monotonic()
    requested_url = validate_public_url(value)
    response, final_url, redirects = _request_follow_safe(requested_url, "GET")
    status_code = response.status_code
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    encoding = response.encoding or "utf-8"
    html_bytes, truncated = _read_limited(response)
    duration_ms = round((time.monotonic() - start) * 1000)

    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    if 200 <= status_code < 300:
        add("HTTP response", "pass", f"Website returned HTTP {status_code}.")
    elif status_code in {401, 403}:
        add("HTTP response", "warning", f"Website returned HTTP {status_code}; access may be restricted to visitors or automated clients.")
    else:
        add("HTTP response", "fail", f"Website returned HTTP {status_code}.")

    if urlsplit(final_url).scheme == "https":
        add("HTTPS", "pass", "Final page uses HTTPS.")
    else:
        add("HTTPS", "warning", "Final page uses HTTP, so the connection is not encrypted.")

    if content_type not in {"text/html", "application/xhtml+xml"}:
        add("HTML page", "info", f"This URL returned {content_type or 'an unspecified content type'}, not HTML. Page-structure checks were not applicable and were skipped; this is not a defect by itself.")
        return {
            "url": requested_url,
            "final_url": final_url,
            "status_code": status_code,
            "content_type": content_type,
            "duration_ms": duration_ms,
            "redirects": redirects,
            "truncated": truncated,
            "checks": _enriched_checks(checks),
            "summary": _summary(checks),
            "coverage": {"browser_inspected": False, "html_truncated": truncated, "links_checked": 0},
            "note": "Read-only URL scan. It does not log in, submit forms, place orders or execute JavaScript.",
        }

    html = html_bytes.decode(encoding, errors="replace")
    parser = _PageInspector()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        add("HTML parsing", "warning", "Some of the page HTML could not be read.")

    # Inspect the page in Chromium too, so content added by JavaScript can be seen.
    browser_data: dict | None = None
    browser_error: str | None = None
    try:
        browser_data = _scan_in_browser(final_url)
    except ScanBrowserError as exc:
        browser_error = str(exc)
    except Exception:
        browser_error = "The browser check could not finish. The basic website check is still available."

    add("HTML page", "pass", "The website returned an HTML page.")
    title = (browser_data.get("title") if browser_data else parser.title) or ""
    h1_count = int(browser_data.get("h1_count", 0)) if browser_data else len(parser.h1_parts)
    has_description = bool(browser_data.get("meta_description")) if browser_data else parser.meta_description
    image_count = int(browser_data.get("image_count", 0)) if browser_data else parser.image_count
    missing_alt = int(browser_data.get("images_missing_alt", 0)) if browser_data else parser.images_missing_alt
    search_count = int(browser_data.get("search_count", 0)) if browser_data else int(parser.search_control)

    if title.strip():
        add("Page title", "pass", f"Title found: {title[:140]}")
    else:
        add("Page title", "warning", "No page title was found.")
    if h1_count:
        add("Main heading (H1)", "pass", f"Found {h1_count} visible main heading(s).")
    else:
        add("Main heading (H1)", "warning", "No visible H1 heading was found on the page.")
    if has_description:
        add("Meta description", "pass", "The page has a meta description.")
    else:
        add("Meta description", "info", "No meta description was found. This is an SEO recommendation, not a functional defect by itself.")
    empty_alt = int(browser_data.get("images_empty_alt", 0)) if browser_data else parser.images_empty_alt
    if image_count == 0:
        add("Image accessibility", "info", "No images were found, so image text could not be checked.")
    elif missing_alt:
        detail = f"{missing_alt} of {image_count} image(s) are missing the alt attribute."
        if empty_alt:
            detail += f" Another {empty_alt} image(s) use an empty alt attribute, which is valid for decorative images."
        add("Image accessibility", "warning", detail)
    elif empty_alt:
        add("Image accessibility", "info", f"All images have an alt attribute; {empty_alt} use an empty alt value, which is valid for decorative images. Confirm that informative images have descriptive text.")
    else:
        add("Image accessibility", "pass", f"All {image_count} image(s) have a non-empty alt attribute.")

    if browser_data and int(browser_data.get("broken_image_count", 0)):
        broken_image_count = int(browser_data["broken_image_count"])
        failed_image_details = [str(item) for item in browser_data.get("failed_image_requests", [])[:3] if str(item).strip()]
        resources_text = f" Resources: {', '.join(failed_image_details)}." if failed_image_details else ""
        add("Image loading", "warning", f"{broken_image_count} image request(s) failed with an HTTP or network error during this check.{resources_text} Retry before filing a defect.")
    elif browser_data and int(browser_data.get("images_unverified_count", 0)):
        unverified_count = int(browser_data.get("images_unverified_count", 0))
        add("Image loading", "info", f"{unverified_count} image(s) were still loading or could not be confirmed at the scan snapshot. No failed image HTTP/network response was observed, so this is not counted as a broken-image warning.")
    elif browser_data and image_count:
        add("Image loading", "pass", "No failed image HTTP/network requests were observed during the short browser check.")
    elif image_count and not browser_data:
        add("Image loading", "info", f"Found {image_count} image(s) in HTML, but image loading could not be verified because the browser check did not run.")
    else:
        add("Image loading", "info", "There were no images to check.")

    checked_links: list[tuple[str, int | None, str | None]] = []
    seen: set[str] = set()
    origin = final_url
    link_candidates = list(parser.internal_link_candidates)
    if browser_data:
        link_candidates.extend(browser_data.get("links", []))
    for href in link_candidates:
        if len(checked_links) >= MAX_LINKS_TO_CHECK:
            break
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        candidate = urljoin(final_url, href)
        parsed_candidate = urlsplit(candidate)
        if parsed_candidate.scheme not in {"http", "https"} or not _same_host(origin, candidate):
            continue
        candidate = urlunsplit((parsed_candidate.scheme, parsed_candidate.netloc, parsed_candidate.path or "/", parsed_candidate.query, ""))
        if candidate in seen:
            continue
        seen.add(candidate)
        link_status, link_error = _link_status(candidate)
        checked_links.append((candidate, link_status, link_error))

    broken = [(url, code) for url, code, error in checked_links if code in {404, 410}]
    unavailable = [(url, code, error) for url, code, error in checked_links if code is None]
    server_errors = [(url, code) for url, code, error in checked_links if code is not None and code >= 500]
    other_client_errors = [(url, code) for url, code, error in checked_links if code is not None and 400 <= code < 500 and code not in {404, 410}]
    if not checked_links:
        add("Internal links", "info", "No eligible same-host links were found in the sampled page, so link health was not assessed.")
    elif broken:
        details = ", ".join(f"{urlsplit(url).path or '/'} → HTTP {code}" for url, code in broken)
        add("Internal links", "fail", f"Broken link(s) found among {len(checked_links)} checked: {details}")
    elif server_errors:
        add("Internal links", "warning", f"{len(server_errors)} checked internal link(s) returned a server error (HTTP 5xx).")
    elif other_client_errors:
        add("Internal links", "warning", f"{len(other_client_errors)} checked internal link(s) returned a non-404 client error (HTTP 4xx); access rules or bot protection may be involved.")
    elif unavailable:
        add("Internal links", "warning", f"Could not verify {len(unavailable)} of {len(checked_links)} checked internal link(s); the cause may be network restrictions or bot protection.")
    else:
        add("Internal links", "pass", f"Checked {len(checked_links)} site link(s); none returned 404 or 410.")

    if search_count:
        add("Search control", "pass", "A visible search field or search button was found. Search results were not tested.")
    else:
        add("Search control", "info", "No visible search field was found. Search functionality was not tested.")

    commerce_evidence = dict(parser.shop_evidence)
    if browser_data:
        for signal, count in (browser_data.get("shop_evidence") or {}).items():
            commerce_evidence[signal] = max(commerce_evidence.get(signal, 0), int(count or 0))
        # Keep compatibility with older or mocked browser snapshots that only
        # return labels and do not include evidence counts.
        for signal in browser_data.get("shop_signals", []):
            commerce_evidence.setdefault(str(signal), 1)
    commerce_signals = sorted(signal for signal, count in commerce_evidence.items() if count > 0)
    if commerce_signals:
        evidence_text = ", ".join(
            f"{signal} ({commerce_evidence[signal]} signal(s))" for signal in commerce_signals
        )
        known_store_signals = {
            "product/catalog elements", "price indicators", "cart/basket controls",
            "add-to-cart controls", "checkout/payment navigation", "e-commerce structured data",
        }
        not_seen = sorted(known_store_signals.difference(commerce_signals))
        not_seen_text = "; no markers for " + ", ".join(not_seen) + " were seen on this page" if not_seen else ""
        add(
            "Store features", "info",
            "Potential e-commerce indicators detected: " + evidence_text + not_seen_text +
            ". These are HTML/DOM/metadata signals only; this page-level scan does not prove a workflow works or that unobserved features are absent from other routes. ShopGuard did not click controls or verify cart, search, checkout or payment behavior."
        )
    else:
        add(
            "Store features", "info",
            "No strong e-commerce HTML/DOM markers were detected on this page. This does not prove the site has no store features: they may be on another route, loaded later, or exposed through custom components not recognised by the scanner."
        )

    form_count = int(browser_data.get("form_count", 0)) if browser_data else parser.forms
    if form_count:
        add("Forms", "info", f"Found {form_count} form(s). Forms were not submitted.")
    if redirects:
        add("Redirects", "info", f"Followed {redirects} safe redirect(s) before reaching the final page.")
    if truncated:
        add("Scan coverage", "warning", f"Only the first {MAX_HTML_BYTES // 1000} KB of HTML was checked.")

    if browser_data:
        _add_browser_checks(checks, browser_data)
    else:
        add("Browser check", "warning", browser_error or "The page could not be checked in the browser. The basic HTML checks are still available.")

    _enrich_checks(checks)
    return {
        "url": requested_url,
        "final_url": final_url,
        "status_code": status_code,
        "content_type": content_type,
        "duration_ms": round((time.monotonic() - start) * 1000),
        "redirects": redirects,
        "truncated": truncated,
        "browser_scan": bool(browser_data),
        "browser_request_count": int(browser_data.get("request_count", 0)) if browser_data else 0,
        "coverage": {
            "browser_inspected": bool(browser_data),
            "html_truncated": truncated,
            "links_checked": len(checked_links),
            "max_links_checked": MAX_LINKS_TO_CHECK,
            "browser_requests_observed": int(browser_data.get("request_count", 0)) if browser_data else 0,
            "browser_requests_allowed": int(browser_data.get("allowed_requests", max(0, int(browser_data.get("request_count", 0)) - int(browser_data.get("blocked_requests", 0))))) if browser_data else 0,
            "browser_requests_blocked": int(browser_data.get("blocked_requests", 0)) if browser_data else 0,
            "browser_request_limit": MAX_BROWSER_REQUESTS,
        },
        "checks": checks,
        "summary": _summary(checks),
        "note": (
            "ShopGuard checked the page HTML and opened it in a temporary browser. It checks visible content, page images, search controls, links and browser errors. It does not click buttons, log in, send forms, change the cart or place orders. These are basic checks, not a full test of the store."
            if browser_data else
            "ShopGuard checked the page HTML only because the browser check could not run. It does not click buttons, log in, send forms, change the cart or place orders. Run scripts/setup_windows.bat to install Chromium, then try again."
        ),
    }



def _enriched_checks(checks: list[dict[str, str]]) -> list[dict[str, str]]:
    """Enrich checks before returning an early (non-HTML) result."""
    _enrich_checks(checks)
    return checks

def _summary(checks: list[dict[str, str]]) -> dict[str, int]:
    return {
        "passed": sum(check["status"] == "pass" for check in checks),
        "warnings": sum(check["status"] == "warning" for check in checks),
        "failed": sum(check["status"] == "fail" for check in checks),
        "info": sum(check["status"] == "info" for check in checks),
    }
