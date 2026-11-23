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


# ============================ NON-FUNCTIONAL ================================
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
