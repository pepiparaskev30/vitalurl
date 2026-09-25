"""
Βαθύς έλεγχος για επιλεγμένες γραμμές (ενεργά και αβέβαια αποτελέσματα).

Το requests δεν εκτελεί JavaScript, οπότε χάνει ανακατευθύνσεις που γίνονται από τη
σελίδα. Εδώ υπάρχουν δύο τρόποι να καλυφθεί αυτό:

  playwright  Πραγματικός headless browser στο ίδιο VM. Τίποτα δεν φεύγει σε τρίτους,
              χωρίς όρια. Απαιτεί: pip install playwright && playwright install chromium
  urlscan     urlscan.io με API key. Δεν εκτίθεται η IP του VM και δίνει screenshot
              και report, αλλά τα scans γίνονται σε τρίτη υποδομή και έχουν όρια.
  search      urlscan.io χωρίς κλειδί. ΔΕΝ υποβάλλει νέο scan: ψάχνει μόνο αν το URL
              έχει ήδη σκαναριστεί από κάποιον άλλον και φέρνει το αποτέλεσμα.
              Δωρεάν και χωρίς έκθεση, αλλά βρίσκει μόνο ό,τι υπάρχει ήδη.

Ρυθμίσεις:
    DEEP_MODE           auto (default) | playwright | urlscan | search
    DEEP_LIMIT          μέγιστες γραμμές ανά έλεγχο (default 30)
    DEEP_WORKERS        παράλληλοι βαθείς έλεγχοι (default 3)
    URLSCAN_API_KEY     κλειδί urlscan.io
    URLSCAN_VISIBILITY  unlisted (default) | private | public
                        ΠΡΟΣΟΧΗ: το public είναι ορατό σε όλους, και στους δράστες.
"""
import os
import time

import requests

DEEP_MODE = os.getenv("DEEP_MODE", "auto").lower()
DEEP_LIMIT = int(os.getenv("DEEP_LIMIT", "30"))
DEEP_WORKERS = int(os.getenv("DEEP_WORKERS", "3"))
URLSCAN_API_KEY = os.getenv("URLSCAN_API_KEY", "")
URLSCAN_VISIBILITY = os.getenv("URLSCAN_VISIBILITY", "unlisted")

# Μόνο αυτές οι κατηγορίες περνούν από βαθύ έλεγχο
DEEP_CATEGORIES = ("active", "error")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def playwright_available():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def active_mode():
    """Ποιος τρόπος θα χρησιμοποιηθεί. Πάντα υπάρχει κάποιος: τελευταία επιλογή το search."""
    if DEEP_MODE == "playwright":
        return "playwright" if playwright_available() else None
    if DEEP_MODE == "urlscan":
        return "urlscan" if URLSCAN_API_KEY else "search"
    if DEEP_MODE == "search":
        return "search"
    if playwright_available():
        return "playwright"
    return "urlscan" if URLSCAN_API_KEY else "search"


# ---------------------------------------------------------------------------
# Playwright — τοπικός headless browser
# ---------------------------------------------------------------------------

def _playwright_batch(items, out_dir, prefix, timeout=25000, settle_ms=2500):
    """items: [(index, url)] → {index: result}. Ένας browser για όλα τα URL."""
    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--ignore-certificate-errors"])
        for idx, url in items:
            chain, shot = [url], None
            context = browser.new_context(user_agent=UA, ignore_https_errors=True)
            page = context.new_page()

            def on_nav(frame, page=page, chain=chain):
                if frame is page.main_frame and frame.url not in chain and frame.url != "about:blank":
                    chain.append(frame.url)

            page.on("framenavigated", on_nav)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                page.wait_for_timeout(settle_ms)     # χρόνος για JavaScript redirect
                if page.url not in chain:
                    chain.append(page.url)
                if out_dir:
                    shot = f"{prefix}{idx}.png"
                    page.screenshot(path=os.path.join(out_dir, shot), full_page=False)
                results[idx] = {"source": "playwright", "chain": chain,
                                "final_url": chain[-1], "screenshot": shot}
            except Exception as e:
                results[idx] = {"source": "playwright", "chain": chain,
                                "final_url": chain[-1] if chain else url,
                                "error": type(e).__name__}
            finally:
                context.close()
        browser.close()
    return results


# ---------------------------------------------------------------------------
# urlscan.io
# ---------------------------------------------------------------------------

def _urlscan_one(url, timeout=120):
    headers = {"API-Key": URLSCAN_API_KEY, "Content-Type": "application/json"}
    r = requests.post("https://urlscan.io/api/v1/scan/", headers=headers, timeout=30,
                      json={"url": url, "visibility": URLSCAN_VISIBILITY,
                            "tags": ["checkmyurl"]})
    if r.status_code == 429:
        return {"source": "urlscan", "error": "rate limit"}
    if r.status_code >= 400:
        return {"source": "urlscan", "error": f"HTTP {r.status_code}"}

    uuid = r.json()["uuid"]
    result_api = f"https://urlscan.io/api/v1/result/{uuid}/"
    deadline = time.time() + timeout
    while time.time() < deadline:                      # το scan θέλει 10-30 δευτ.
        time.sleep(5)
        g = requests.get(result_api, timeout=30)
        if g.status_code == 200:
            data = g.json()
            task, page = data.get("task", {}), data.get("page", {})
            start, final = task.get("url", url), page.get("url", url)
            chain = [start] if start == final else [start, final]
            return {"source": "urlscan", "chain": chain, "final_url": final,
                    "link": task.get("reportURL", f"https://urlscan.io/result/{uuid}/"),
                    "screenshot_url": task.get("screenshotURL")}
    return {"source": "urlscan", "error": "timeout"}


def _urlscan_batch(items):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=DEEP_WORKERS) as ex:
        out = list(ex.map(lambda it: (it[0], _urlscan_one(it[1])), items))
    return dict(out)


# ---------------------------------------------------------------------------
# urlscan.io χωρίς κλειδί — αναζήτηση σε υπάρχοντα scans
# ---------------------------------------------------------------------------

def _urlscan_search_one(url):
    """Ψάχνει αν το URL (ή το domain του) έχει ήδη σκαναριστεί. Δεν υποβάλλει τίποτα."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    if not host:
        return {"source": "search", "error": "invalid url"}
    try:
        r = requests.get("https://urlscan.io/api/v1/search/",
                         params={"q": f'page.domain:"{host}"', "size": 1}, timeout=30)
    except requests.RequestException as e:
        return {"source": "search", "error": type(e).__name__}
    if r.status_code == 429:
        return {"source": "search", "error": "rate limit"}
    if r.status_code >= 400:
        return {"source": "search", "error": f"HTTP {r.status_code}"}

    hits = r.json().get("results", [])
    if not hits:
        return {"source": "search", "error": "χωρίς scan"}
    hit = hits[0]
    final = hit.get("page", {}).get("url", url)
    start = hit.get("task", {}).get("url", url)
    chain = [start] if start == final else [start, final]
    return {"source": "search", "chain": chain, "final_url": final,
            "link": hit.get("result"), "scanned_at": hit.get("task", {}).get("time")}


def _search_batch(items):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=DEEP_WORKERS) as ex:
        return dict(ex.map(lambda it: (it[0], _urlscan_search_one(it[1])), items))


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def deep_check(urls_by_index, categories, out_dir=None, prefix=""):
    """urls_by_index: {row_index: url}. Επιστρέφει {row_index: result}.

    Ελέγχονται μόνο οι γραμμές με κατηγορία active ή error, έως DEEP_LIMIT.
    """
    mode = active_mode()
    if not mode:
        return {}, None

    items = [(i, u) for i, u in urls_by_index.items()
             if categories[i] in DEEP_CATEGORIES and u][:DEEP_LIMIT]
    if not items:
        return {}, mode

    if mode == "playwright":
        return _playwright_batch(items, out_dir, prefix), mode
    if mode == "urlscan":
        return _urlscan_batch(items), mode
    return _search_batch(items), mode