import io
import os
import re
import json
import uuid
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool

from pipeline import load_config, process_df, save_excel, category
from stats import build_stats, stats_to_json, save_stats_excel
from deepcheck import deep_check, active_mode, deep_check_one
from utilities import defang, refang, unwrap_safelink, check_single, to_greek

SRC_DIR = os.path.dirname(os.path.abspath(__file__))       # .../pepscan/src
BASE_DIR = os.path.dirname(SRC_DIR)                         # .../pepscan

SRC_PATH = os.getenv("SRC_PATH", SRC_DIR)
OUTPUT_PATH = os.getenv("OUTPUT_PATH", os.path.join(BASE_DIR, "output"))
STATIC_PATH = os.path.join(BASE_DIR, "static")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
WORKERS = int(os.getenv("WORKERS", "20"))

os.makedirs(OUTPUT_PATH, exist_ok=True)
config = load_config(SRC_PATH)

app = FastAPI(title="CheckMyURL API")
app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REDIRECT_COL = "URL ή ΙΡ ΑΝΑΚΑΤΕΥΘΥΝΣΗΣ"
STATUS_COL = "ΤΡΕΧΟΥΣΑ ΚΑΤΑΣΤΑΣΗ (ACTIVE/OFFLINE/BROWSER BLOCKED)"
# Ετυμηγορία urlscan → τελική κατάσταση της γραμμής
DEEP_VERDICT = {
    "ACTIVE": ("ACTIVE (urlscan)", "ΕΝΕΡΓΟ (επιβεβαίωση urlscan)", "active"),
    "BROWSER BLOCKED": ("BROWSER BLOCKED (urlscan)",
                        "ΜΠΛΟΚΑΡΙΣΜΕΝΟ ΑΠΟ BROWSER / CDN (urlscan)", "error"),
    "OFFLINE": (None, None, None),
}
URL_COL = "URL ή ΙΡ ΚΑΤΑΓΓΕΛΛΟΜΕΝΟΥ ΙΣΤΟΤΟΠΟY"
ALLOWED_EXT = (".xlsx", ".xlsm")


def to_records(df):
    """JSON-safe rows for the UI (NaN → null, dates → dd/mm/yyyy)."""
    view = df.copy()
    for col in view.columns:
        if pd.api.types.is_datetime64_any_dtype(view[col]):
            view[col] = view[col].dt.strftime("%d/%m/%Y")
        else:
            view[col] = view[col].apply(
                lambda v: v.strftime("%d/%m/%Y") if isinstance(v, (pd.Timestamp, datetime)) else v
            )
    return json.loads(view.to_json(orient="records", force_ascii=False))


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_PATH, "index.html"))


@app.post("/api/check")
async def check(
    file: UploadFile = File(...),
    check: bool = Query(True, description="Send requests to each URL"),
    redirects: bool = Query(True, description="Record redirect chains"),
    max_rows: int = Query(1000, ge=1, le=10000),
    deep: bool = Query(False, description="Deep check (headless browser or urlscan.io)"),
):
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, "Δεκτά μόνο αρχεία .xlsx ή .xlsm")

    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Το αρχείο ξεπερνά τα {MAX_UPLOAD_MB} MB")

    try:
        old_df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Δεν ήταν δυνατή η ανάγνωση του αρχείου: {e}")
    if old_df.empty:
        raise HTTPException(400, "Το αρχείο δεν περιέχει γραμμές")

    new_df, categories, groups = await run_in_threadpool(
        process_df, old_df, config["ua_agents"], config["dictionary_columns"],
        config["status_gr"], WORKERS, check, redirects, max_rows,
        config["brand_categories"],
    )

    # Βαθύς έλεγχος με browser ή urlscan, μόνο για ενεργά και αβέβαια
    deep_results, deep_mode = {}, None
    if deep:
        file_id_pre = uuid.uuid4().hex
        urls = {i: refang(str(u)) for i, u in enumerate(new_df[URL_COL]) if pd.notna(u)}
        deep_results, deep_mode = await run_in_threadpool(
            deep_check, urls, categories, OUTPUT_PATH, f"{file_id_pre}_shot__"
        )
        # αν βρέθηκε αλυσίδα που δεν είχε πιάσει το requests, γράφεται στη στήλη
        chains = list(new_df[REDIRECT_COL])
        statuses = list(new_df[STATUS_COL])
        for i, res in deep_results.items():
            chain = res.get("chain") or []
            if len(chain) > 1 and not str(chains[i] or "").strip():
                chains[i] = " → ".join(defang(c) for c in chain)

            # το scan έγινε από άλλο δίκτυο: αν είδε τη σελίδα, η γραμμή δεν είναι αβέβαιη
            en, gr, cat = DEEP_VERDICT.get(res.get("verdict") or "", (None, None, None))
            if en:
                statuses[i] = to_greek(en, config["status_gr"]) if config["status_gr"] else en
                if statuses[i] == en and gr:
                    statuses[i] = gr
                categories[i] = cat
        new_df[REDIRECT_COL] = chains
        new_df[STATUS_COL] = statuses

    today = f"{datetime.now():%d-%m-%Y}"
    download_name = f"προς_ΕΑΚ_{today}.xlsx"
    stats_name = f"Στατιστικά_{today}.xlsx"
    file_id = file_id_pre if deep and deep_results else uuid.uuid4().hex
    await run_in_threadpool(
        save_excel, new_df, categories, os.path.join(OUTPUT_PATH, f"{file_id}__{download_name}")
    )

    group_order = [g for g, _ in config["brand_categories"]]
    stats = build_stats(new_df, categories, groups, group_order)
    checked_at = f"{datetime.now():%d/%m/%Y %H:%M}"
    await run_in_threadpool(
        save_stats_excel, stats, os.path.join(OUTPUT_PATH, f"{file_id}_stats__{stats_name}"),
        f"{len(new_df)} URL · έλεγχος {checked_at}",
    )

    stats_json = stats_to_json(stats)

    return {
        "file_id": file_id,
        "filename": download_name,
        "columns": list(new_df.columns),
        "rows": to_records(new_df),
        "categories": categories,
        "groups": groups,
        "deep": {str(k): v for k, v in deep_results.items()},
        "deep_mode": deep_mode,
        "stats": stats_json,
        "stats_filename": stats_name,
    }


def _find(prefix):
    for name in os.listdir(OUTPUT_PATH):
        if name.startswith(prefix):
            return name
    return None


def _send(prefix, media_type=XLSX_MIME):
    name = _find(prefix)
    if not name:
        raise HTTPException(404, "Το αρχείο δεν βρέθηκε")
    return FileResponse(os.path.join(OUTPUT_PATH, name),
                        filename=name.split("__", 1)[1], media_type=media_type)


def _valid(file_id):
    if not re.fullmatch(r"[0-9a-f]{32}", file_id):
        raise HTTPException(400, "Μη έγκυρο αναγνωριστικό")


@app.get("/api/download/{file_id}")
def download(file_id: str):
    _valid(file_id)
    return _send(f"{file_id}__")


@app.get("/api/download/{file_id}/stats")
def download_stats(file_id: str):
    _valid(file_id)
    return _send(f"{file_id}_stats__")


@app.get("/api/deep-modes")
def deep_modes():
    """Ποιος τρόπος βαθέος ελέγχου είναι διαθέσιμος σε αυτό το μηχάνημα."""
    return {"mode": active_mode()}


@app.get("/api/shot/{file_id}/{index}")
def screenshot(file_id: str, index: int):
    _valid(file_id)
    name = _find(f"{file_id}_shot__{index}.png")
    if not name:
        raise HTTPException(404, "Δεν βρέθηκε screenshot")
    return FileResponse(os.path.join(OUTPUT_PATH, name), media_type="image/png")


@app.post("/api")
async def support_service(
    url: str = Query(..., description="URL σε defanged ή κανονική μορφή"),
    deep: bool = Query(False, description="Επιπλέον έλεγχος με browser ή urlscan"),
):
    """Έλεγχος ενός URL: κατάσταση, αλυσίδα ανακατεύθυνσης και τελικός προορισμός."""
    clean = unwrap_safelink(refang(url))
    if not clean.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "Μη έγκυρο URL")

    status, chain = await run_in_threadpool(check_single, clean, config["ua_agents"])
    chain = chain or [clean]

    if deep:
        results, mode = await run_in_threadpool(deep_check_one, clean)
        if results and len(results.get("chain") or []) > len(chain):
            chain = results["chain"]

    return {
        "url": clean,
        "status": to_greek(status, config["status_gr"]) if config["status_gr"] else status,
        "active": bool(status and status.startswith("ACTIVE")),
        "redirected": len(chain) > 1,
        "final_url": chain[-1],
        "chain": chain,
    }