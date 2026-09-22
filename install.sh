#!/usr/bin/env bash
# CheckMyURL — εγκατάσταση και εκκίνηση χωρίς Docker (Linux / macOS)
#
#   ./checkmyurl.sh                 εγκατάσταση (την πρώτη φορά) και εκκίνηση
#   ./checkmyurl.sh --install-only  μόνο εγκατάσταση
#   HOST=0.0.0.0 PORT=9000 ./checkmyurl.sh
set -euo pipefail

cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
VENV=".venv"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31mΣφάλμα:\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Python 3.10+
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 && \
     "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || fail "Χρειάζεται Python 3.10 ή νεότερη.
  Ubuntu/Debian: sudo apt install python3 python3-venv
  macOS:         brew install python"
say "Python: $($PY --version)"

# 2. Virtual environment
if [ ! -x "$VENV/bin/python" ]; then
  say "Δημιουργία virtual environment ($VENV)"
  "$PY" -m venv "$VENV" || fail "Αποτυχία δημιουργίας venv.
  Ubuntu/Debian: sudo apt install python3-venv"
fi
VPY="$VENV/bin/python"

# 3. Πακέτα — μόνο αν άλλαξε το requirements.txt
REQ_HASH="$("$VPY" -c 'import hashlib; print(hashlib.sha256(open("requirements.txt","rb").read()).hexdigest())')"
if [ "$(cat "$VENV/.requirements.sha256" 2>/dev/null || true)" != "$REQ_HASH" ]; then
  say "Εγκατάσταση πακέτων"
  "$VPY" -m pip install --upgrade pip >/dev/null
  "$VPY" -m pip install -r requirements.txt
  echo "$REQ_HASH" > "$VENV/.requirements.sha256"
else
  say "Τα πακέτα είναι ήδη εγκατεστημένα"
fi

# 4. Έλεγχος αρχείων ρυθμίσεων
for f in agents.json dictionary.json; do
  [ -f "src/$f" ] || fail "Λείπει το src/$f"
done
mkdir -p output

if [ "${1:-}" = "--install-only" ]; then
  say "Η εγκατάσταση ολοκληρώθηκε. Εκκίνηση με: ./checkmyurl.sh"
  exit 0
fi

# 5. Ρυθμίσεις από .env (αν υπάρχει)
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

say "CheckMyURL: http://$HOST:$PORT  (Ctrl+C για τερματισμό)"
exec "$VPY" -m uvicorn app:app --app-dir src --host "$HOST" --port "$PORT"