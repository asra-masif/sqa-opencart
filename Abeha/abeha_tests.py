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
REGRESSION_IDS = []
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
