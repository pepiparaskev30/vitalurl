"""
redirectcheck.org — ανίχνευση αλυσίδας ανακατευθύνσεων.

Χωρίς API key. Ακολουθεί HTTP redirects (301/302/303/307/308) και
<meta http-equiv="refresh">. Το αίτημα φεύγει από τους δικούς τους
servers, όχι από τη δική σας IP.

    pip install httpx
"""

import asyncio

import httpx

API = "https://www.redirectcheck.org/api/check"

# Το bulk run κόβεται στα 60 δλ συνολικά, κάθε hop στα 15 δλ.
# Μικρά chunks -> λιγότερα TIMEOUT σε αργούς hosts.
CHUNK = 20
CONCURRENCY = 3

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

BLANK = {
    "submitted_url": None, "final_url": None, "redirected": False,
    "redirect_hops": 0, "redirect_chain": None, "status_code": None,
    "server": None, "content_type": None, "loop": False,
    "warnings": None, "error": None,
}


def _parse(item: dict) -> dict:
    out = dict(BLANK)
    out["submitted_url"] = item.get("url")

    if item.get("error"):
        out["error"] = item.get("error_type") or "ERROR"
        out["error_message"] = item.get("message")
        return out

    hops = item.get("redirects") or []
    fin = item.get("final_result") or {}
    loop = item.get("loop") or {}

    chain = []
    for h in hops:
        to = h.get("to")
        if to:
            chain.append(f"{to} [{h.get('status_code') or h.get('type')}]")

    out["final_url"] = fin.get("final_url")
    out["status_code"] = fin.get("status_code")
    out["server"] = fin.get("server")
    out["content_type"] = fin.get("content_type")
    out["redirect_hops"] = len(hops)
    out["redirect_chain"] = " -> ".join(chain) if chain else None
    out["redirected"] = bool(hops)
    out["loop"] = bool(loop.get("detected"))
    out["warnings"] = ", ".join(item.get("warnings") or []) or None
    return out


async def _one_chunk(client, urls, sem, method, follow_meta, max_hops):
    async with sem:
        try:
            r = await client.post(API, json={
                "urls": urls,
                "method": method,
                "followMetaRefresh": follow_meta,
                "maxHops": max_hops,
                "userAgent": UA,
            })
            r.raise_for_status()
            results = r.json().get("results") or []
            parsed = [_parse(x) for x in results]
            # ασφάλεια: αν γυρίσουν λιγότερα, γέμισε τα υπόλοιπα
            while len(parsed) < len(urls):
                miss = dict(BLANK)
                miss["submitted_url"] = urls[len(parsed)]
                miss["error"] = "NO_RESULT"
                parsed.append(miss)
            return parsed
        except Exception as e:
            out = []
            for u in urls:
                b = dict(BLANK)
                b["submitted_url"] = u
                b["error"] = f"{type(e).__name__}: {e}"[:180]
                out.append(b)
            return out


async def check_redirects(urls, method="GET", follow_meta=True, max_hops=20):
    """Επιστρέφει λίστα αποτελεσμάτων με την ίδια σειρά με τα urls."""
    urls = list(urls)
    if not urls:
        return []

    chunks = [urls[i:i + CHUNK] for i in range(0, len(urls), CHUNK)]
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
        batches = await asyncio.gather(*(
            _one_chunk(client, c, sem, method, follow_meta, max_hops)
            for c in chunks
        ))

    return [r for batch in batches for r in batch]


def check_redirects_sync(urls, **kw):
    return asyncio.run(check_redirects(urls, **kw))