#!/usr/bin/env bash
# Accende tutto con un comando: ./avvia.sh
#
# Fa da solo quello che il README chiede di fare a mano in due terminali: crea
# l'ambiente Python se manca, installa le dipendenze la prima volta, avvia l'API e
# l'interfaccia, apre il browser. Ctrl-C spegne entrambi.
set -euo pipefail

cd "$(dirname "$0")"
PORTA_API=8000
PORTA_WEB=5173
PROFILO="config/profiles/lega-paolo.json"

rosso()  { printf '\033[31m%s\033[0m\n' "$*"; }
verde()  { printf '\033[32m%s\033[0m\n' "$*"; }
grigio() { printf '\033[90m%s\033[0m\n' "$*"; }

# --- prerequisiti ------------------------------------------------------------
command -v python3 >/dev/null || { rosso "manca python3"; exit 1; }
command -v node    >/dev/null || { rosso "manca node (serve la 22 o superiore)"; exit 1; }

versione_node=$(node -v | sed 's/v\([0-9]*\).*/\1/')
if [ "$versione_node" -lt 22 ]; then
  rosso "node $(node -v): serve la 22 o superiore"
  exit 1
fi

# --- porte gia' occupate -----------------------------------------------------
for porta in "$PORTA_API" "$PORTA_WEB"; do
  if lsof -ti tcp:"$porta" >/dev/null 2>&1; then
    rosso "la porta $porta e' gia' occupata"
    grigio "  chi la usa:  lsof -ti tcp:$porta"
    grigio "  per liberarla:  kill \$(lsof -ti tcp:$porta)"
    exit 1
  fi
done

# --- ambiente Python ---------------------------------------------------------
if [ ! -d .venv ]; then
  grigio "creo l'ambiente Python..."
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import pandas, numpy, rapidfuzz, openpyxl, bs4" 2>/dev/null; then
  grigio "installo le dipendenze Python (solo la prima volta)..."
  .venv/bin/pip install -q -r requirements.txt
fi

# --- dipendenze web ----------------------------------------------------------
if [ ! -d web/node_modules ]; then
  grigio "installo le dipendenze web (solo la prima volta)..."
  (cd web && npm install --silent)
fi

# --- dataset -----------------------------------------------------------------
DATASET="data/processed/lega-paolo-2026-27/2026-27/auction_data.json"
if [ ! -f "$DATASET" ]; then
  grigio "genero il dataset (manca $DATASET)..."
  .venv/bin/python -m advisor.pipeline --profile "$PROFILO" \
    --raw-dir data/raw --output-dir data/processed
fi

# --- avvio -------------------------------------------------------------------
mkdir -p .log
spegni() {
  echo
  grigio "spengo..."
  [ -n "${PID_API:-}" ] && kill "$PID_API" 2>/dev/null || true
  [ -n "${PID_WEB:-}" ] && kill "$PID_WEB" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap spegni EXIT INT TERM

.venv/bin/python -m advisor.server --host 127.0.0.1 --port "$PORTA_API" > .log/api.log 2>&1 &
PID_API=$!

(cd web && npm run dev -- --port "$PORTA_WEB" > ../.log/web.log 2>&1) &
PID_WEB=$!

# Attende che l'interfaccia risponda davvero prima di aprire il browser.
grigio "avvio in corso..."
for _ in $(seq 1 60); do
  if curl -sf "http://localhost:$PORTA_WEB" >/dev/null 2>&1; then break; fi
  if ! kill -0 "$PID_API" 2>/dev/null; then
    rosso "l'API si e' fermata. Ultime righe di .log/api.log:"; tail -15 .log/api.log; exit 1
  fi
  sleep 0.5
done

if ! curl -sf "http://localhost:$PORTA_WEB" >/dev/null 2>&1; then
  rosso "l'interfaccia non risponde. Ultime righe di .log/web.log:"; tail -15 .log/web.log; exit 1
fi

verde "pronto:  http://localhost:$PORTA_WEB"
grigio "  API su 127.0.0.1:$PORTA_API   log in .log/   Ctrl-C per spegnere"
command -v open >/dev/null && open "http://localhost:$PORTA_WEB" 2>/dev/null || true

wait
