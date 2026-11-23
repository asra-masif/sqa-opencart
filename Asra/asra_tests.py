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
REGRESSION_IDS = ["TC-01", "TC-02", "TC-03", "TC-04"]
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
