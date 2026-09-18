"""
urlscan.io enrichment: resolves redirect chains (HTTP *and* client-side JS)
from urlscan's own infrastructure rather than your egress IP.

    pip install httpx
    export URLSCAN_API_KEY=...

Visibility:
    "private"  - only your team. Default here. Use for live casework.
    "unlisted" - not in public search, reachable by direct link.
    "public"   - indexed and searchable. The operator can see it.
"""

import asyncio
import os

import httpx

API = "https://urlscan.io/api/v1"
KEY = os.getenv("URLSCAN_API_KEY", "")

SUBMIT_CONCURRENCY = 2      # urlscan asks for low concurrency + backoff
POLL_INTERVAL = 5.0
POLL_MAX = 24               # ~2 min ceiling per scan


async def _submit(client, url, visibility, tags):
    r = await client.post(
        f"{API}/scan/",
        headers={"API-Key": KEY, "Content-Type": "application/json"},
        json={"url": url, "visibility": visibility, "tags": tags},
    )
    if r.status_code == 429:
        raise RuntimeError("rate limited (429)")
    if r.status_code == 400:
        raise RuntimeError(f"rejected: {r.json().get('description', r.text)[:200]}")
    r.raise_for_status()
    return r.json()["uuid"]


async def _poll(client, uuid):
    # result is 404 until the scan finishes
    for _ in range(POLL_MAX):
        r = await client.get(f"{API}/result/{uuid}/", headers={"API-Key": KEY})
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            await asyncio.sleep(POLL_INTERVAL * 3)
            continue
        await asyncio.sleep(POLL_INTERVAL)
    raise TimeoutError(f"scan {uuid} not ready")


def _parse(res: dict) -> dict:
    page = res.get("page", {}) or {}
    task = res.get("task", {}) or {}
    data = res.get("data", {}) or {}
    verdicts = (res.get("verdicts", {}) or {}).get("overall", {}) or {}

    hops = []
    for h in data.get("redirects", []) or []:
        u = h.get("url")
        if u:
            hops.append(f"{u} [{h.get('type', '?')}]")

    submitted = task.get("url")
    final = page.get("url")

    return {
        "urlscan_uuid": task.get("uuid"),
        "urlscan_report": task.get("reportURL"),
        "submitted_url": submitted,
        "final_url": final,
        "redirected": bool(final and submitted and final.rstrip("/") != submitted.rstrip("/")),
        "redirect_hops": len(hops),
        "redirect_chain": " -> ".join(hops) if hops else None,
        "final_domain": page.get("domain"),
        "final_ip": page.get("ip"),
        "final_asn": page.get("asn"),
        "final_asn_name": page.get("asnname"),
        "country": page.get("country"),
        "server": page.get("server"),
        "page_title": page.get("title"),
        "tls_issuer": page.get("tlsIssuer"),
        "malicious": verdicts.get("malicious"),
        "score": verdicts.get("score"),
        "brands": ", ".join(b.get("name", "") for b in (verdicts.get("brands") or [])) or None,
        "screenshot": res.get("screenshot"),
        "error": None,
    }


async def scan_one(client, url, sem, visibility, tags):
    blank = {k: None for k in _parse({})}
    blank["submitted_url"] = url
    if not KEY:
        blank["error"] = "URLSCAN_API_KEY not set"
        return blank
    async with sem:
        try:
            uuid = await _submit(client, url, visibility, tags)
            await asyncio.sleep(POLL_INTERVAL)
            return _parse(await _poll(client, uuid))
        except Exception as e:
            blank["error"] = f"{type(e).__name__}: {e}"[:200]
            return blank


async def scan_urls(urls, visibility="private", tags=None,
                    concurrency=SUBMIT_CONCURRENCY):
    tags = tags or []
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        return await asyncio.gather(
            *(scan_one(client, u, sem, visibility, tags) for u in urls)
        )


async def quota():
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API}/quotas/", headers={"API-Key": KEY})
        r.raise_for_status()
        return r.json()