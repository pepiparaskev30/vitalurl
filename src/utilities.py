import os
import re
import json
import pandas as pd
import requests
from urllib.parse import urlparse, urljoin, parse_qs


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUSPENDED_KEYWORDS = [
    "account suspended", "this account has been suspended", "site suspended",
    "suspected phishing", "deceptive site", "this site has been blocked",
    "domain has expired", "domain for sale", "this domain is parked",
]

DNS_ERRORS = [
    "NameResolutionError", "Name or service not known",
    "nodename nor servname", "getaddrinfo failed", "No address associated",
]

URL_COLUMNS = ["URL ή ΙΡ ΚΑΤΑΓΓΕΛΛΟΜΕΝΟΥ ΙΣΤΟΤΟΠΟY", "URL ή ΙΡ ΑΝΑΚΑΤΕΥΘΥΝΣΗΣ"]

META_REFRESH = re.compile(
    r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*content=["\']?\s*\d*\s*;?\s*url\s*=\s*([^"\'>\s]+)',
    re.I,
)
JS_REDIRECT = re.compile(
    r'(?:window\.|document\.|top\.|self\.)?location(?:\.href)?\s*=\s*["\']([^"\']+)["\']'
    r'|location\.(?:replace|assign)\(\s*["\']([^"\']+)["\']',
    re.I,
)

STATUS_ORDER = [
    "ACTIVE", "SUSPENDED", "FORBIDDEN", "RATE LIMITED", "SERVER ERROR",
    "HTTP ERROR", "NOT FOUND", "GONE", "BLOCKED", "SSL ERROR",
    "TIMEOUT", "TOO MANY REDIRECTS", "CONNECTION", "DNS", "INVALID",
]


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def read_json_dictionary(path, filename):
    try:
        with open(os.path.join(path, filename), encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading {filename}: {e}")
        return None


def xlsx_to_csv(dirname, ext=(".xlsx",)):
    frames = []
    for file in os.listdir(dirname):
        if file.endswith(ext) and not file.startswith("~$"):
            frames.append(pd.read_excel(os.path.join(dirname, file)))
    if not frames:
        raise FileNotFoundError(f"No {ext} files in {dirname}")
    return pd.concat(frames, ignore_index=True)


def initialize_new_df(columns):
    return pd.DataFrame(columns=columns)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def refang(url):
    url = str(url).strip()
    url = re.sub(r"(?i)hxxp(s?)\[://\]", r"http\1://", url)     # hxxps[://]
    url = re.sub(r"(?i)hxxp(s?)\[?:\]?//", r"http\1://", url)   # hxxps://, hxxps[:]//
    url = re.sub(r"(?i)^(https?)\[:\]//", r"\1://", url)        # https[:]//
    return (url.replace("[.]", ".")
               .replace("(.)", ".")
               .replace("{.}", ".")
               .replace("[dot]", "."))


def defang(url):
    return (url.replace("https://", "hxxps[://]")
               .replace("http://", "hxxp[://]")
               .replace(".", "[.]"))


def is_safelink(url):
    return "safelinks.protection.outlook.com" in refang(url).lower()


def unwrap_safelink(url):
    """Returns the real URL from an Outlook Safe Links wrapper (also handles nesting)."""
    for _ in range(5):
        parsed = urlparse(url)
        if not parsed.netloc.lower().endswith("safelinks.protection.outlook.com"):
            break
        inner = parse_qs(parsed.query).get("url")
        if not inner:
            break
        url = refang(inner[0])
    return url


def unwrap_if_safelink(url):
    if pd.isna(url) or not is_safelink(url):
        return url                      # δεν είναι safelink → bypass
    return unwrap_safelink(refang(url))


def extract_client_redirect(body, base_url):
    """Meta refresh / JavaScript redirects that requests does not follow."""
    m = META_REFRESH.search(body) or JS_REDIRECT.search(body)
    if not m:
        return None
    target = next(g for g in m.groups() if g)
    if target.startswith(("#", "javascript:")):
        return None
    return urljoin(base_url, target)


# ---------------------------------------------------------------------------
# Status checks
# ---------------------------------------------------------------------------

def rank(status):
    for i, key in enumerate(STATUS_ORDER):
        if status.startswith(key):
            return i
    return len(STATUS_ORDER)


def classify_response(r, original_url):
    code = r.status_code
    chain = [h.url for h in r.history] + [r.url] if r.history else []

    if code < 400:
        try:
            body_raw = r.raw.read(100_000, decode_content=True).decode(errors="ignore")
        except Exception:
            body_raw = ""
        if any(k in body_raw.lower() for k in SUSPENDED_KEYWORDS):
            return "SUSPENDED / TAKEN DOWN", chain

        client = extract_client_redirect(body_raw, r.url)
        if client and client != r.url:
            chain = (chain or [r.url]) + [client]

        if chain:
            final_host = urlparse(chain[-1]).netloc
            if final_host != urlparse(original_url).netloc:
                return f"ACTIVE (REDIRECT → {final_host})", chain
        return "ACTIVE", chain

    if code == 403: return "FORBIDDEN (403)", chain
    if code == 404: return "NOT FOUND (404)", chain
    if code == 410: return "GONE (410)", chain
    if code == 429: return "RATE LIMITED (429)", chain
    if code == 451: return "BLOCKED - LEGAL (451)", chain
    if code >= 500: return f"SERVER ERROR ({code})", chain
    return f"HTTP ERROR ({code})", chain


def check_single(url, user_agents, timeout=10):
    """Returns (status, redirect_chain). ACTIVE from any user agent wins."""
    if pd.isna(url) or not str(url).strip():
        return None, []
    url = unwrap_safelink(refang(url))
    best = None

    for ua in user_agents.values():
        chain = []
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=timeout,
                             allow_redirects=True, verify=False, stream=True)
            status, chain = classify_response(r, url)
            r.close()
        except requests.exceptions.Timeout:
            status = "TIMEOUT"
        except requests.exceptions.TooManyRedirects:
            status = "TOO MANY REDIRECTS"
        except requests.exceptions.SSLError:
            status = "SSL ERROR"
        except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
                requests.exceptions.InvalidSchema):
            return "INVALID URL", []
        except requests.exceptions.ConnectionError as e:
            msg = str(e)
            if any(d in msg for d in DNS_ERRORS):
                return "DNS NOT RESOLVED", []
            status = "CONNECTION REFUSED" if "refused" in msg.lower() else "CONNECTION ERROR"
        except requests.RequestException:
            status = "UNKNOWN ERROR"

        if status.startswith("ACTIVE"):
            return status, chain
        if best is None or rank(status) < rank(best[0]):
            best = (status, chain)

    return best


def check_row(row, user_agents, timeout=10):
    """Returns (status, redirect_chain_as_text) for a row with URL_COLUMNS."""
    results = [check_single(row.get(col), user_agents, timeout) for col in URL_COLUMNS]
    results = [r for r in results if r[0] is not None]
    if not results:
        return None, None
    status, chain = min(results, key=lambda x: rank(x[0]))
    redirect = " → ".join(chain) if len(chain) > 1 else None
    return status, redirect


def to_greek(status, status_gr):
    if status is None or not status_gr:
        return status
    for en, gr in status_gr.items():
        if status.startswith(en):
            return gr + status[len(en):]
    return status