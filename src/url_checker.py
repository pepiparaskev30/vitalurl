#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import re


global _REFANG
global URL_COLS

_REFANG = [
    (re.compile(r"h(?:xx|tt)p(s?)\s*\[?\s*:\s*\]?\s*/\s*/\s*\]?", re.I), r"http\1://"),
    (re.compile(r"\[\.\]|\(\.\)|\[dot\]", re.I), "."),
    (re.compile(r"\[@\]|\(at\)|\[at\]", re.I), "@"),
]

URL_COLS = ["URL ή ΙΡ ΚΑΤΑΓΓΕΛΛΟΜΕΝΟΥ ΙΣΤΟΤΟΠΟY", "URL ή ΙΡ ΑΝΑΚΑΤΕΥΘΥΝΣΗΣ"]

def refang(v):
    if not isinstance(v, str):
        return v
    for pat, rep in _REFANG:
        v = pat.sub(rep, v)
    return v.strip()


def convert_phishing_links(df:pd.DataFrame):
    for c in URL_COLS:
        if c in df.columns:
            df[c] = df[c].map(refang)