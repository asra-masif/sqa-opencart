import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

# ------------------------------ settings ---------------------------------
BASE = os.getenv("BASE_URL", "https://demo.opencart.com").rstrip("/")
PW_MIN_LEN = int(os.getenv("PW_MIN_LEN", "4"))       # OpenCart minimum password length
NFR_MAX_SEC = float(os.getenv("NFR_MAX_SEC", "5"))    # NFR-01 pass limit in seconds
PASSWORD = "Passw0rd!"
A, B, C = "Asra M.Asif", "Aliza Malik", "Abeha Tariq"   # Member 1 / 2 / 3
REGRESSION_IDS = ["TC-01", "TC-02", "TC-03", "TC-04", "TC-16"]
try:
    expect.set_options(timeout=15000)                 
except Exception:
    pass

TESTS, STATE, NOTE = [], {}, []
BROWSER = None


class Blocked(Exception):
    """Raised when a test cannot run because something it depends on failed."""


def case(id, fr, owner, technique, inputs, steps, expected, smoke=False):
    """Decorator: registers a test together with its documentation."""
    def deco(fn):
        TESTS.append(dict(id=id, fr=fr, owner=owner, technique=technique, inputs=inputs,
                          steps=steps, expected=expected, smoke=smoke, fn=fn))
        return fn
    return deco


def note(text):
    NOTE.append(text)


# ------------------------------ helpers ----------------------------------
def url(route, **params):
    extra = "".join(f"&{k}={v}" for k, v in params.items())
    return f"{BASE}/index.php?route={route}&language=en-gb{extra}"


def unique_email():
    return f"sqa{int(time.time() * 1000)}@example.com"


def register(page, first="Test", last="User", email=None, password=PASSWORD):    # Module A
    email = email or unique_email()
    page.goto(url("account/register"))
    page.fill("#input-firstname", first)
    page.fill("#input-lastname", last)
    page.fill("#input-email", email)
    page.fill("#input-password", password)
    page.locator("input[name=agree]").check()
    page.get_by_role("button", name="Continue").click()
    return email


def login(page, email, password):                                                 # Module A
    page.goto(url("account/login"))
    page.fill("#input-email", email)
    page.fill("#input-password", password)
    page.get_by_role("button", name="Login").click()


def search(page, term):                                                           # Module B
    page.goto(url("product/search", search=term))


def open_product(page, product_id):                                               # Module B
    page.goto(url("product/product", product_id=product_id))


def add_to_cart(page, product_id=40, qty=1):                                      # Module C
    open_product(page, product_id)
    page.fill("#input-quantity", str(qty))
    page.click("#button-cart")


def fill_if_empty(page, selector, value):
    loc = page.locator(selector)
    if loc.count() and loc.first.is_visible() and not loc.first.input_value():
        loc.first.fill(value)


def place_order(page):                                                            # Module C
    """Checkout as guest or logged-in user. If your OpenCart version uses different
    element IDs, fix them in THIS function only (used by TC-12 and TC-16)."""
    page.goto(url("checkout/checkout"))
    guest = page.locator("#input-guest")                       
    if guest.count() and guest.is_visible():
        guest.check()
    fields = {"#input-firstname": "Test", "#input-lastname": "User", "#input-email": unique_email(),
              "#input-shipping-firstname": "Test", "#input-shipping-lastname": "User",
              "#input-payment-firstname": "Test", "#input-payment-lastname": "User",
              "#input-shipping-address-1": "1 Test Street", "#input-shipping-city": "Karachi",
              "#input-shipping-postcode": "75000", "#input-payment-address-1": "1 Test Street",
              "#input-payment-city": "Karachi", "#input-payment-postcode": "75000"}
    for sel, val in fields.items():
        fill_if_empty(page, sel, val)
    for kind in ("shipping", "payment"):                       
        zone = page.locator(f"#input-{kind}-zone")
        if zone.count() and zone.first.is_visible():
            zone.locator("option").nth(1).wait_for(state="attached")
            zone.first.select_option(index=1)
    for cb in page.locator("input[type=checkbox][name=agree]").all():
        if cb.is_visible():
            cb.check()
    for btn in ("#button-register", "#button-shipping-address", "#button-payment-address"):
        b = page.locator(btn)
        if b.count() and b.first.is_visible():
            b.first.click()
            page.wait_for_timeout(1500)
    for trigger, radio, confirm in (("#button-shipping-methods", "shipping_method", "#button-shipping-method"),
                                    ("#button-payment-methods", "payment_method", "#button-payment-method")):
        t = page.locator(trigger)
        if t.count() and t.first.is_visible():
            t.first.click()
            page.locator(f"input[type=radio][name={radio}]").first.check()
            page.click(confirm)
            page.wait_for_timeout(1500)
    page.click("#button-confirm")


def registered_email():
    """Creates one real account on first use and reuses it (TC-03, TC-04, TC-14)."""
    if "email" not in STATE:
        ctx = BROWSER.new_context()
        ctx.set_default_timeout(20000)
        pg = ctx.new_page()
        try:
            email = register(pg)
            expect(pg).to_have_url(re.compile("account/success"))
            STATE["email"] = email
        except Exception as e:
            raise Blocked("could not create test account: " + str(e)[:120])
        finally:
            ctx.close()
    return STATE["email"]


def failed_login_message(page, email, password):
    login(page, email, password)
    alert = page.locator(".alert-danger").first
    alert.wait_for()
    return " ".join(alert.inner_text().split())


# ======================= MODULE A: Registration & Login =====================
@case("TC-01", "FR-01", A, "BVA - max valid (32-char first name, min-length password)",
      "First name = 32 chars; password = 4 chars; new email",
      "Open register page; fill form; tick privacy policy; click Continue",
      "Account created (success page shown)", smoke=True)
def tc01(page):
    register(page, first="A" * 32, password="x" * PW_MIN_LEN)
    expect(page).to_have_url(re.compile("account/success"))
    expect(page.locator("#content h1")).to_contain_text("Account Has Been Created")


@case("TC-02", "FR-01", A, "BVA - just below minimum (password length 3)",
      "Valid details; password = 3 chars",
      "Open register page; fill form with short password; click Continue",
      "Password error shown; account not created")
def tc02(page):
    register(page, password="x" * (PW_MIN_LEN - 1))
    expect(page.locator("#error-password")).to_be_visible()
    expect(page).not_to_have_url(re.compile("account/success"))


@case("TC-03", "FR-02", A, "EP - valid partition (registered email + correct password)",
      "Registered email; correct password",
      "Open login page; enter credentials; click Login",
      "My Account page is shown")
def tc03(page):
    login(page, registered_email(), PASSWORD)
    expect(page).to_have_url(re.compile("account/account"))
    expect(page.locator("#content")).to_contain_text("My Account")


@case("TC-04", "FR-02", A, "EP - invalid partition (wrong password)",
      "Registered email; wrong password 'WrongPass1'",
      "Open login page; enter credentials; click Login",
      "Warning 'No match for E-Mail Address and/or Password'; user stays logged out")
def tc04(page):
    login(page, registered_email(), "WrongPass1")
    expect(page.locator(".alert-danger").first).to_contain_text("No match")
    expect(page).not_to_have_url(re.compile("account/account"))


# ================== MODULE B: Product search & product details ==============
@case("TC-05", "FR-03", B, "EP - valid partition (term matching a product)",
      "Search term 'iphone'", "Open search results for 'iphone'",
      "At least one product listed, including iPhone", smoke=True)
def tc05(page):
    search(page, "iphone")
    expect(page.locator(".product-thumb").first).to_be_visible()
    expect(page.locator("#content")).to_contain_text("iPhone")


@case("TC-06", "FR-03", B, "EP - invalid partition (term matching nothing)",
      "Search term 'zzzxqy'", "Open search results for 'zzzxqy'",
      "'There is no product that matches the search criteria'; no product cards")
def tc06(page):
    search(page, "zzzxqy")
    expect(page.locator("#content")).to_contain_text("no product that matches")
    expect(page.locator(".product-thumb")).to_have_count(0)


@case("TC-07", "FR-06", B, "EP - valid partition (existing product id 40)",
      "product_id = 40", "Open product page for id 40",
      "Product name 'iPhone' and Add to Cart button shown")
def tc07(page):
    open_product(page, 40)
    expect(page.locator("#content h1")).to_have_text("iPhone")
    expect(page.locator("#button-cart")).to_be_visible()


@case("TC-08", "FR-06", B, "BVA - below lowest valid id (product_id = 0)",
      "product_id = 0", "Open product page for id 0",
      "Not-found message ('The page you requested cannot be found!'); no Add to Cart button")
def tc08(page):
    open_product(page, 0)
    expect(page.locator("#content")).to_contain_text(re.compile("not found|cannot be found", re.I))
    expect(page.locator("#button-cart")).to_have_count(0)


# ===================== MODULE C: Cart & Checkout ============================
@case("TC-09", "FR-04", C, "BVA - minimum valid quantity (1)",
      "iPhone (id 40), quantity = 1",
      "Open product; set quantity 1; click Add to Cart; open cart page",
      "Success message; cart lists iPhone with quantity 1", smoke=True)
def tc09(page):
    add_to_cart(page, 40, 1)
    expect(page.locator(".alert-success").first).to_contain_text("added")
    page.goto(url("checkout/cart"))
    expect(page.locator("#content")).to_contain_text("iPhone")
    expect(page.locator("input[name^=quantity]").first).to_have_value("1")


@case("TC-10", "FR-04", C, "EP - invalid partition (required options not selected)",
      "Apple Cinema 30 inch (id 42), no options chosen",
      "Open product; click Add to Cart without choosing required options",
      "Option error shown; product not added")
def tc10(page):
    add_to_cart(page, 42, 1)
    expect(page.locator("[id^=error-option]").first).to_be_visible()
    expect(page.locator(".alert-success")).to_have_count(0)


@case("TC-11", "FR-05", C, "EP - invalid partition (empty cart)",
      "Empty cart", "Open checkout page directly with nothing in the cart",
      "Redirected to cart page showing 'Your shopping cart is empty'")
def tc11(page):
    page.goto(url("checkout/checkout"))
    expect(page).to_have_url(re.compile("checkout/cart"))
    expect(page.locator("#content")).to_contain_text("Your shopping cart is empty")


@case("TC-12", "FR-05", C, "EP - valid partition (complete guest details)",
      "iPhone in cart; valid guest name, email, address; first shipping and payment method",
      "Add iPhone; open checkout; fill details; choose shipping and payment; confirm order",
      "Order success page 'Your order has been placed!'")
def tc12(page):
    add_to_cart(page, 40, 1)
    expect(page.locator(".alert-success").first).to_be_visible()
    place_order(page)
    expect(page).to_have_url(re.compile("checkout/success"))
    expect(page.locator("#content")).to_contain_text("order has been placed")


# ============================ NON-FUNCTIONAL ================================
@case("TC-13", "NFR-01", A, "Performance - cold page load time",
      "Login page, 5 cold loads (new browser each time)",
      "Load login page 5 times; measure time to 'load' event; compute average",
      "Average load time <= 5 seconds")
def tc13(page):
    times = []
    for _ in range(5):
        ctx = BROWSER.new_context()
        pg = ctx.new_page()
        start = time.perf_counter()
        pg.goto(url("account/login"), wait_until="load")
        times.append(time.perf_counter() - start)
        ctx.close()
    page.goto(url("account/login"))                       
    avg = sum(times) / len(times)
    note(f"avg {avg:.2f}s, max {max(times):.2f}s over 5 loads (limit {NFR_MAX_SEC}s)")
    assert avg <= NFR_MAX_SEC, f"average {avg:.2f}s is above {NFR_MAX_SEC}s"


@case("TC-14", "NFR-02", B, "Security - credential handling",
      "Login + register pages; unknown email vs known email, both with wrong password",
      "Check password fields are masked; check HTTPS; compare the two failed-login messages",
      "All password fields masked; HTTPS used; identical error message for both failed logins")
def tc14(page):
    email = registered_email()
    masked = total = 0
    for route in ("account/login", "account/register"):
        page.goto(url(route))
        masked += page.locator("#content input[type=password]").count()
        total += page.locator("#content input[id*=password]").count()
    https_ok = page.url.startswith("https://") if BASE.startswith("https") else True   
    https_text = str(https_ok) if BASE.startswith("https") else "n/a (local http site)"
    msg_unknown = failed_login_message(page, "nobody.sqa@example.com", "WrongPass1")
    msg_known = failed_login_message(page, email, "WrongPass1")
    same = msg_unknown == msg_known
    note(f"password fields masked {masked}/{total}; https={https_text}; failed-login messages identical={same}")
    assert total >= 2 and masked == total, "a password field is not masked"
    assert https_ok, "site not served over HTTPS"
    assert same, "error message reveals whether the email exists"


@case("TC-15", "NFR-03", C, "Usability - form labelling",
      "Register and login forms",
      "Count visible text/email/password inputs and how many have a label",
      "100% of form inputs are labelled")
def tc15(page):
    js = """() => {
        const els = [...document.querySelectorAll(
            '#content input[type=text],#content input[type=email],#content input[type=password],#content input[type=tel]')]
            .filter(e => e.offsetParent !== null);
        const ok = els.filter(e => e.getAttribute('aria-label') ||
            (e.id && document.querySelector('label[for="' + e.id + '"]')));
        return [els.length, ok.length];
    }"""
    total = labelled = 0
    for route in ("account/register", "account/login"):
        page.goto(url(route))
        t, ok = page.evaluate(js)
        total += t
        labelled += ok
    pct = 100 * labelled / total if total else 0
    note(f"{labelled}/{total} inputs labelled = {pct:.0f}% (limit 100%)")
    assert total > 0 and labelled == total, f"only {labelled}/{total} inputs labelled"


# ============================== END-TO-END ==================================
@case("TC-16", "E2E", "Group", "End-to-end critical workflow",
      "New customer buys an iPhone",
      "Register (A) > logout/login (A) > search and open product (B) > add to cart, view cart, checkout (C)",
      "Order placed successfully")
def tc16(page):
    # --- Module A steps (Asra) ---
    email = register(page)
    expect(page).to_have_url(re.compile("account/success"))
    page.goto(url("account/logout"))
    login(page, email, PASSWORD)
    expect(page).to_have_url(re.compile("account/account"))
    # --- Module B steps (Aliza) ---
    search(page, "iphone")
    page.locator(".product-thumb h4 a").first.click()
    expect(page).to_have_url(re.compile("product/product"))
    expect(page.locator("#content h1")).to_contain_text("iPhone")
    # --- Module C steps (Abeha) ---
    page.click("#button-cart")
    expect(page.locator(".alert-success").first).to_contain_text("added")
    page.goto(url("checkout/cart"))
    expect(page.locator("#content")).to_contain_text("iPhone")
    place_order(page)
    expect(page).to_have_url(re.compile("checkout/success"))
    expect(page.locator("#content")).to_contain_text("order has been placed")


# =============================== RUNNER =====================================
def run_tests(browser, selected, run_name):
    global BROWSER
    BROWSER = browser
    shots = Path("screenshots") / run_name
    shots.mkdir(parents=True, exist_ok=True)
    rows = []
    for t in selected:
        NOTE.clear()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.set_default_timeout(20000)
        page = ctx.new_page()
        try:
            t["fn"](page)
            status, actual = "PASS", (NOTE[0] if NOTE else "As expected")
        except Blocked as e:
            status, actual = "BLOCKED", str(e)
        except Exception as e:
            err = " ".join(str(e).split())[:250]
            status, actual = "FAIL", (NOTE[0] + " | " if NOTE else "") + err
        try:
            page.screenshot(path=str(shots / f"{t['id']}.png"))
        except Exception:
            pass
        ctx.close()
        print(f"{t['id']:6} {t['fr']:7} {t['owner']:12} {status}")
        print(f"       actual: {actual}")
        rows.append({**{k: t[k] for k in ("id", "fr", "owner", "technique", "inputs", "steps", "expected")},
                     "actual": actual, "status": status})
    n = lambda s: sum(r["status"] == s for r in rows)
    print(f"\nPASS {n('PASS')} | FAIL {n('FAIL')} | BLOCKED {n('BLOCKED')} | TOTAL {len(rows)}")
    print(f"Screenshots saved in {shots}")
    return rows


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    headed = "--headed" in sys.argv
    run_name = args[0] if args else "all"
    ids = [a.upper() for a in args[1:]]
    if run_name == "smoke":
        selected = [t for t in TESTS if t["smoke"]]
    elif run_name in ("before", "after"):
        selected = [t for t in TESTS if t["id"] in REGRESSION_IDS]
    else:
        selected = [t for t in TESTS if not ids or t["id"] in ids]
    with sync_playwright() as p:
        opts = {}
        if os.getenv("CHROME_PATH"):                       
            opts = dict(executable_path=os.getenv("CHROME_PATH"),
                        args=["--no-sandbox", "--disable-gpu"])
        browser = p.chromium.launch(headless=not headed, slow_mo=500 if headed else 0, **opts)
        run_tests(browser, selected, run_name)
        browser.close()


if __name__ == "__main__":
    main()
