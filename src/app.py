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

from pipeline import load_config, process_df, save_excel
from stats import build_stats, stats_to_json, save_stats_excel

SRC_DIR = os.path.dirname(os.path.abspath(__file__))       # .../checkmyurl/src
BASE_DIR = os.path.dirname(SRC_DIR)                         # .../checkmyurl

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

    today = f"{datetime.now():%d-%m-%Y}"
    download_name = f"προς_ΕΑΚ_{today}.xlsx"
    stats_name = f"Στατιστικά_{today}.xlsx"
    file_id = uuid.uuid4().hex
    await run_in_threadpool(
        save_excel, new_df, categories, os.path.join(OUTPUT_PATH, f"{file_id}__{download_name}")
    )

    group_order = [g for g, _ in config["brand_categories"]]
    stats = build_stats(new_df, categories, groups, group_order)
    await run_in_threadpool(
        save_stats_excel, stats, os.path.join(OUTPUT_PATH, f"{file_id}_stats__{stats_name}"),
        f"{len(new_df)} URL · έλεγχος {datetime.now():%d/%m/%Y %H:%M}",
    )

    return {
        "file_id": file_id,
        "filename": download_name,
        "columns": list(new_df.columns),
        "rows": to_records(new_df),
        "categories": categories,
        "groups": groups,
        "stats": stats_to_json(stats),
        "stats_filename": stats_name,
    }


def _send(prefix):
    for name in os.listdir(OUTPUT_PATH):
        if name.startswith(prefix):
            return FileResponse(
                os.path.join(OUTPUT_PATH, name),
                filename=name.split("__", 1)[1],
                media_type=XLSX_MIME,
            )
    raise HTTPException(404, "Το αρχείο δεν βρέθηκε")


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