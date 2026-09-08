# URL Vitality

Batch liveness and phishing-status checker for URLs held in spreadsheets. Reads a `.xlsx` dataset, normalises and probes each URL, and writes back an enriched dataset suitable for CTI ingestion.

---

## Overview

```
Data (.xlsx)  ──▶  url_checker  ──▶  updated data
```

`url_checker` is the single entry point. Everything else is internal.

---

## Architecture

### High-level

| Stage | Type | Description |
|---|---|---|
| `Data (.xlsx)` | Input | Spreadsheet containing the URLs to be assessed |
| `url_checker` | Process | Orchestrates normalisation, probing and enrichment |
| `updated data` | Output | Same records, augmented with liveness and phishing verdicts |

### Internal functionality

```
Data (.xlsx)
      │
      ▼
┌───────────────────────── url_checker ─────────────────────────┐
│                                                               │
│  url_normalization ──▶ curl_phising_link ──▶ post_checker_api │
│                                                    (planned)  │
└───────────────────────────────────────────────────────────────┘
      │
      ▼
updated data for CTI (.xlsx)
```

| Module | Status | Responsibility |
|---|---|---|
| `url_normalization` | Implemented | Canonicalises raw URL strings before probing |
| `curl_phising_link` | Implemented | Issues the HTTP request and captures the response signals |
| `post_checker_api` | Planned | Post-processing / enrichment against an external API |

`post_checker_api` is drawn with a dashed border in the architecture diagram: interface defined, not yet wired into the pipeline.

---

## Pipeline stages

### 1. `url_normalization`

Brings heterogeneous input into a single canonical form so that probing and deduplication are deterministic.

- Strips surrounding whitespace, quotes and zero-width characters
- Adds a scheme where missing (default `http://`)
- Lower-cases scheme and host; leaves path and query case-sensitive
- Decodes IDN / punycode hosts for display, retains ASCII form for the request
- Removes default ports (`:80`, `:443`) and trailing dots on the host
- Normalises percent-encoding and collapses duplicate slashes in the path
- Flags malformed entries rather than dropping them, so no input row is lost

### 2. `curl_phising_link`

Performs the live probe and records the observable evidence.

- Issues the request with a configurable timeout and User-Agent
- Follows redirects up to a bounded depth and records the full redirect chain
- Captures final URL, HTTP status code, response headers, TLS certificate details and response time
- Classifies liveness: `LIVE`, `DEAD`, `TIMEOUT`, `TLS_ERROR`, `DNS_ERROR`
- Detects parked, sinkholed and takedown-notice responses
- Never executes page content — retrieval only

### 3. `post_checker_api` *(planned)*

Enrichment layer for third-party verdicts.

- Submits the final URL and/or hash to an external reputation service
- Merges the returned verdict, category and confidence into the record
- Optional by design: the pipeline runs to completion without it

---

## Input format

A `.xlsx` workbook. The URL column is identified by header name (configurable, default `url`). All other columns are carried through unchanged.

| url | *(any other columns)* |
|---|---|
| `hxxp://example[.]com/login` | … |
| `https://example.org/pay` | … |

Defanged notation is normalised on read.

## Output format

The input columns, plus:

| Column | Description |
|---|---|
| `normalized_url` | Canonical form used for the probe |
| `status` | `LIVE` / `DEAD` / `TIMEOUT` / `TLS_ERROR` / `DNS_ERROR` |
| `http_code` | Final HTTP status code |
| `final_url` | URL after redirects |
| `redirect_chain` | Ordered list of intermediate URLs |
| `response_time_ms` | Round-trip time |
| `tls_issuer` | Certificate issuer, where TLS was negotiated |
| `checked_at` | UTC timestamp of the probe |
| `verdict` | Populated by `post_checker_api` once enabled |

---

## Installation

```bash
git clone <repository-url>
cd url-vitality
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python url_checker.py --input data.xlsx --output updated_data.xlsx
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--input` | — | Path to the source `.xlsx` |
| `--output` | — | Path for the enriched `.xlsx` |
| `--url-column` | `url` | Header name of the URL column |
| `--timeout` | `10` | Per-request timeout, seconds |
| `--max-redirects` | `5` | Redirect follow limit |
| `--concurrency` | `10` | Parallel probes |
| `--user-agent` | *(tool default)* | Override the request User-Agent |
| `--no-verify-tls` | off | Probe despite invalid certificates, recording the error |
| `--enable-post-checker` | off | Enable `post_checker_api` once available |

---

## Operational notes

- Probing generates traffic to potentially hostile infrastructure. Run it from an environment where that is acceptable and attributable as intended.
- Concurrency is bounded so the tool is not mistaken for a scan.
- No page content is rendered or stored; only response metadata is retained.
- Every input row appears in the output, including rows that failed normalisation.

---

## Roadmap

- [ ] Wire `post_checker_api` into the pipeline
- [ ] Screenshot / DOM capture as an optional module
- [ ] STIX 2.1 export alongside `.xlsx`
- [ ] Resume support for interrupted runs
- [ ] Per-domain rate limiting

---

## Project structure

```
url-vitality/
├── url_checker.py           # Orchestrator / CLI entry point
├── modules/
│   ├── url_normalization.py
│   ├── curl_phising_link.py
│   └── post_checker_api.py  # planned
├── docs/
│   └── architecture.png
├── requirements.txt
└── README.md
```
