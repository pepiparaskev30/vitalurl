import asyncio
import ssl
from urllib.parse import urlparse
import httpx


TIMEOUT = httpx.Timeout(6.0, connect=3.0)
CONCURRENCY = 50
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def classify(status: int) -> str:
    if status in (200, 201, 203, 206):
        return "ACTIVE"
    if status in (301, 302, 303, 307, 308):
        return "REDIRECT"
    if status == 403:
        return "FORBIDDEN"
    if status == 404:
        return "NOT FOUND (404)"
    if status == 410:
        return "GONE"
    if 500 <= status < 600:
        return "SERVER ERROR"
    return f"HTTP {status}"


async def check_one(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> dict:
    out = {
        "url": url,
        "status": None,
        "state": None,
        "final_url": None,
        "redirect_chain": [],
        "server": None,
        "error": None,
    }

    if not isinstance(url, str) or not url.strip():
        out["state"] = "EMPTY"
        return out

    u = url.strip()
    if not urlparse(u).scheme:
        u = "http://" + u
        out["url"] = u

    async with sem:
        for method in ("HEAD", "GET"):
            try:
                r = await client.request(method, u)
                out["status"] = r.status_code
                out["state"] = classify(r.status_code)
                out["final_url"] = str(r.url)
                out["redirect_chain"] = [str(h.url) for h in r.history]
                out["server"] = r.headers.get("server")
                out["error"] = None
                # some hosts reject HEAD - retry once with GET
                if method == "HEAD" and r.status_code in (400, 405, 501):
                    continue
                return out
            except httpx.ConnectTimeout:
                out["state"], out["error"] = "TIMEOUT", "connect timeout"
            except httpx.ReadTimeout:
                out["state"], out["error"] = "TIMEOUT", "read timeout"
            except ssl.SSLError as e:
                out["state"], out["error"] = "SSL ERROR", str(e)[:200]
            except httpx.ConnectError as e:
                msg = str(e).lower()
                out["state"] = "DNS/NXDOMAIN" if "name" in msg or "resolve" in msg else "OFFLINE"
                out["error"] = str(e)[:200]
            except Exception as e:
                out["state"], out["error"] = "ERROR", f"{type(e).__name__}: {e}"[:200]

    return out


async def check_urls(urls, concurrency: int = CONCURRENCY, follow_redirects: bool = True):
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=10)
    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=follow_redirects,
        max_redirects=5,
        verify=False,               # phishing hosts routinely have bad certs
        limits=limits,
        headers={"User-Agent": UA},
    ) as client:
        return await asyncio.gather(*(check_one(client, u, sem) for u in urls))


def check_urls_sync(urls, **kw):
    return asyncio.run(check_urls(urls, **kw))