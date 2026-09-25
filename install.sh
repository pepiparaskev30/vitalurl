#!/usr/bin/env bash
# CheckMyURL — εγκατάσταση και εκκίνηση χωρίς Docker (Linux / macOS)
#
#   ./checkmyurl.sh                 εγκατάσταση (την πρώτη φορά) και εκκίνηση
#   ./checkmyurl.sh --install-only  μόνο εγκατάσταση
#   HOST=0.0.0.0 PORT=9000 ./checkmyurl.sh
#
# Εγκαθιστά αυτόματα, αν λείπουν: Python 3, venv, pip
# (apt / dnf / yum / zypper / pacman / apk / brew, αλλιώς get-pip.py)
set -euo pipefail

cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
VENV=".venv"
GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mΠροειδοποίηση:\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31mΣφάλμα:\033[0m %s\n' "$*" >&2; exit 1; }

# 0. Package manager / sudo
SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
fi

PKG=""
for m in apt-get dnf yum zypper pacman apk brew; do
  if command -v "$m" >/dev/null 2>&1; then PKG="$m"; break; fi
done

APT_UPDATED=0
pkg_install() {
  [ -n "$PKG" ] || return 1
  if [ "$PKG" != "brew" ] && [ "$(id -u)" -ne 0 ] && [ -z "$SUDO" ]; then
    warn "Χρειάζονται δικαιώματα root (sudo) για εγκατάσταση πακέτων"
    return 1
  fi
  case "$PKG" in
    apt-get)
      if [ "$APT_UPDATED" -eq 0 ]; then
        $SUDO apt-get update -qq || return 1
        APT_UPDATED=1
      fi
      $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" ;;
    dnf|yum) $SUDO "$PKG" install -y "$@" ;;
    zypper)  $SUDO zypper -n install "$@" ;;
    pacman)  $SUDO pacman -S --noconfirm --needed "$@" ;;
    apk)     $SUDO apk add --no-cache "$@" ;;
    brew)    brew install "$@" ;;
  esac
}

python_pkgs() {
  case "$PKG" in
    apt-get)      echo "python3 python3-venv python3-pip" ;;
    dnf|yum)      echo "python3 python3-pip" ;;
    zypper)       echo "python3 python3-pip" ;;
    pacman)       echo "python python-pip" ;;
    apk)          echo "python3 py3-pip" ;;
    brew)         echo "python" ;;
  esac
}

# 1. Python 3.10+
find_python() {
  PY=""
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1 && \
       "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PY="$cand"; return 0
    fi
  done
  return 1
}

if ! find_python; then
  say "Εγκατάσταση Python 3"
  # shellcheck disable=SC2046
  pkg_install $(python_pkgs) || true
  find_python || fail "Χρειάζεται Python 3.10 ή νεότερη.
  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip
  macOS:         brew install python"
fi
PYVER="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
say "Python: $($PY --version)"

# 2. venv και pip συστήματος
has_venv() { "$PY" -c 'import venv, ensurepip' >/dev/null 2>&1; }
has_pip()  { "$PY" -m pip --version >/dev/null 2>&1; }

if ! has_venv || ! has_pip; then
  say "Εγκατάσταση venv / pip"
  # shellcheck disable=SC2046
  pkg_install $(python_pkgs) || warn "Αποτυχία εγκατάστασης μέσω $PKG"
  if [ "$PKG" = "apt-get" ] && ! has_venv; then
    pkg_install "python${PYVER}-venv" || true
  fi
fi

get_pip() {
  local py="$1" tmp
  tmp="$(mktemp)"
  say "Λήψη get-pip.py"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$GET_PIP_URL" -o "$tmp"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$tmp" "$GET_PIP_URL"
  else
    "$py" -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \
      "$GET_PIP_URL" "$tmp"
  fi || { rm -f "$tmp"; return 1; }
  "$py" "$tmp" || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
}

# 3. Virtual environment
if [ -d "$VENV" ] && [ ! -x "$VENV/bin/python" ]; then
  rm -rf "$VENV"
fi
if [ ! -x "$VENV/bin/python" ]; then
  say "Δημιουργία virtual environment ($VENV)"
  if ! "$PY" -m venv "$VENV" 2>/dev/null; then
    rm -rf "$VENV"
    warn "Το ensurepip δεν είναι διαθέσιμο — venv χωρίς pip, pip μέσω get-pip.py"
    "$PY" -m venv --without-pip "$VENV" || fail "Αποτυχία δημιουργίας venv.
  Ubuntu/Debian: sudo apt install python3-venv python${PYVER}-venv"
  fi
fi
VPY="$VENV/bin/python"

# 4. pip μέσα στο venv
if ! "$VPY" -m pip --version >/dev/null 2>&1; then
  say "Εγκατάσταση pip στο venv"
  "$VPY" -m ensurepip --upgrade >/dev/null 2>&1 || get_pip "$VPY" || true
  "$VPY" -m pip --version >/dev/null 2>&1 || fail "Αποτυχία εγκατάστασης pip (ελέγξτε τη σύνδεση δικτύου)"
  rm -f "$VENV/.requirements.sha256"
fi
say "pip: $("$VPY" -m pip --version | cut -d' ' -f1-2)"

# 5. Πακέτα — μόνο αν άλλαξε το requirements.txt
[ -f requirements.txt ] || fail "Λείπει το requirements.txt"
REQ_HASH="$("$VPY" -c 'import hashlib; print(hashlib.sha256(open("requirements.txt","rb").read()).hexdigest())')"
if [ "$(cat "$VENV/.requirements.sha256" 2>/dev/null || true)" != "$REQ_HASH" ]; then
  say "Εγκατάσταση πακέτων"
  "$VPY" -m pip install --upgrade pip setuptools wheel >/dev/null
  "$VPY" -m pip install -r requirements.txt
  echo "$REQ_HASH" > "$VENV/.requirements.sha256"
else
  say "Τα πακέτα είναι ήδη εγκατεστημένα"
fi

# 6. Έλεγχος αρχείων ρυθμίσεων
for f in agents.json dictionary.json; do
  [ -f "src/$f" ] || fail "Λείπει το src/$f"
done
mkdir -p output

if [ "${1:-}" = "--install-only" ]; then
  say "Η εγκατάσταση ολοκληρώθηκε. Εκκίνηση με: ./checkmyurl.sh"
  exit 0
fi

# 7. Ρυθμίσεις από .env (αν υπάρχει)
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

say "CheckMyURL: http://$HOST:$PORT  (Ctrl+C για τερματισμό)"
exec "$VPY" -m uvicorn app:app --app-dir src --host "$HOST" --port "$PORT"