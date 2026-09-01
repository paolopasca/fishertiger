#!/usr/bin/env bash
# Crea "Tool Fantacalcio.app" sulla Scrivania: un'icona cliccabile che apre il
# Terminale e lancia ./avvia.sh.
#
#   ./crea-app.sh
#
# Perche' passa dal Terminale invece di girare in silenzio: avvia.sh stampa cosa sta
# facendo (installazioni, generazione dataset, porte occupate) e si spegne chiudendo
# la finestra o con Ctrl-C. Un'app muta nasconderebbe gli errori e non darebbe modo
# di fermarla.
#
# Perche' il bundle si costruisce in una cartella temporanea invece che direttamente
# sulla Scrivania: se la Scrivania e' sincronizzata con iCloud, il provider ci
# attacca attributi estesi mentre osacompile sta firmando, la firma fallisce e su
# Apple Silicon un binario non firmato non parte proprio. Costruito altrove e poi
# copiato, il problema non si presenta.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Desktop/Tool Fantacalcio.app"
LAVORO="$(mktemp -d)"
trap 'rm -rf "$LAVORO"' EXIT

command -v osacompile >/dev/null || { echo "manca osacompile (fa parte di macOS)"; exit 1; }
[ -x "$REPO/avvia.sh" ] || { echo "manca $REPO/avvia.sh oppure non e' eseguibile"; exit 1; }

# --- lo script: apre il Terminale sulla cartella e avvia -----------------------
# Il doppio avvio non serve gestirlo qui: avvia.sh si accorge da solo che il tool
# risponde gia' e riapre solo il browser.
# Il percorso entra come stringa AppleScript (sfuggendo \\ e ") e il quoting per la
# shell lo fa `quoted form of`: cosi' regge anche se la cartella contiene spazi.
REPO_AS=$(printf '%s' "$REPO" | sed 's/\\/\\\\/g; s/"/\\"/g')
osacompile -o "$LAVORO/app.app" <<APPLESCRIPT
on run
	set cartella to "$REPO_AS"
	tell application "Terminal"
		activate
		set nuovo to do script "cd " & quoted form of cartella & " && ./avvia.sh"
		set custom title of nuovo to "Tool Fantacalcio"
	end tell
end run
APPLESCRIPT

# --- icona --------------------------------------------------------------------
python3 "$REPO/tools/icona_app.py" "$LAVORO/icona.png"
mkdir -p "$LAVORO/icona.iconset"
for lato in 16 32 64 128 256 512 1024; do
  sips -z "$lato" "$lato" "$LAVORO/icona.png" \
       --out "$LAVORO/icona.iconset/icon_${lato}x${lato}.png" >/dev/null
done
# iconutil vuole questi nomi esatti: le @2x sono la versione grande della stessa misura.
cd "$LAVORO/icona.iconset"
mv icon_32x32.png   icon_16x16@2x.png   && cp icon_16x16@2x.png   icon_32x32.png
mv icon_64x64.png   icon_32x32@2x.png
cp icon_256x256.png icon_128x128@2x.png
cp icon_512x512.png icon_256x256@2x.png
mv icon_1024x1024.png icon_512x512@2x.png
cd "$LAVORO"
iconutil -c icns icona.iconset -o icona.icns
# Il bundle punta gia' a applet.icns: sostituendo il file si sostituisce l'icona.
cp icona.icns "$LAVORO/app.app/Contents/Resources/applet.icns"

# --- nome leggibile nel Dock e nella barra dei menu ----------------------------
plist="$LAVORO/app.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName Tool Fantacalcio" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string Tool Fantacalcio" "$plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName Tool Fantacalcio" "$plist"

# --- firma --------------------------------------------------------------------
# Ad hoc, cioe' senza certificato: basta a far partire il binario su Apple Silicon.
xattr -cr "$LAVORO/app.app"
codesign --force --deep --sign - "$LAVORO/app.app" 2>/dev/null
codesign --verify "$LAVORO/app.app" || { echo "la firma non regge, l'app non partirebbe"; exit 1; }

# --- consegna -----------------------------------------------------------------
rm -rf "$APP"
ditto "$LAVORO/app.app" "$APP"
codesign --verify "$APP" || { echo "la firma si e' rotta nella copia"; exit 1; }
touch "$APP"   # sveglia il Finder, altrimenti tiene l'icona vecchia in cache

echo "creata: $APP"
echo
echo "Al primo avvio macOS chiede il permesso di controllare il Terminale: e' normale,"
echo "l'app non fa altro che aprire una finestra ed eseguire ./avvia.sh."
