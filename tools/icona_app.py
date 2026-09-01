"""Disegna l'icona di "Tool Fantacalcio.app": un campo da calcio stilizzato.

Solo libreria standard: zlib e struct bastano a scrivere un PNG, quindi lo script
gira ovunque senza installare nulla. Il disegno e' fatto a 2048 px e poi ridotto da
`sips`, cosi' i bordi risultano morbidi senza scrivere un antialiasing a mano.

    python3 tools/icona_app.py <file.png>
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

N = 2048
RADIUS = N * 0.22          # angoli arrotondati, proporzione delle icone macOS
MARGIN = N * 0.12          # margine del campo dentro il riquadro
LINE = N * 0.016           # spessore delle righe del campo
SFONDO = (10, 46, 34)      # verde scuro in alto
SFONDO2 = (22, 122, 80)    # verde piu' chiaro in basso
RIGA = (245, 250, 247)


def dentro_riquadro(x: float, y: float) -> bool:
    """Riquadro con angoli arrotondati: fuori dagli angoli vale la distanza dal centro
    dell'arco, altrove basta stare nella scatola."""
    cx = min(max(x, RADIUS), N - RADIUS)
    cy = min(max(y, RADIUS), N - RADIUS)
    return (x - cx) ** 2 + (y - cy) ** 2 <= RADIUS ** 2


def su_riga(x: float, y: float) -> bool:
    """Le righe del campo: perimetro, linea di meta' campo, cerchio, due aree."""
    l, r = MARGIN, N - MARGIN
    t, b = MARGIN, N - MARGIN
    h = LINE / 2

    def cornice(x0: float, y0: float, x1: float, y1: float) -> bool:
        if not (x0 - h <= x <= x1 + h and y0 - h <= y <= y1 + h):
            return False
        return not (x0 + h < x < x1 - h and y0 + h < y < y1 - h)

    if cornice(l, t, r, b):                                   # perimetro
        return True
    if abs(y - N / 2) <= h and l <= x <= r:                   # meta' campo
        return True
    d = ((x - N / 2) ** 2 + (y - N / 2) ** 2) ** 0.5          # cerchio di centrocampo
    if abs(d - N * 0.13) <= h:
        return True
    area = N * 0.20
    if cornice(N / 2 - area, t, N / 2 + area, t + N * 0.10):  # area in alto
        return True
    if cornice(N / 2 - area, b - N * 0.10, N / 2 + area, b):  # area in basso
        return True
    return False


def png(path: Path) -> None:
    righe = []
    for y in range(N):
        quota = y / (N - 1)
        base = tuple(int(a + (b - a) * quota) for a, b in zip(SFONDO, SFONDO2))
        riga = bytearray([0])                                  # filtro 0, nessuno
        for x in range(N):
            if not dentro_riquadro(x + 0.5, y + 0.5):
                riga += bytes((0, 0, 0, 0))                    # fuori: trasparente
            elif su_riga(x + 0.5, y + 0.5):
                riga += bytes(RIGA) + b"\xff"
            else:
                riga += bytes(base) + b"\xff"
        righe.append(bytes(riga))

    def blocco(tipo: bytes, dati: bytes) -> bytes:
        return (struct.pack(">I", len(dati)) + tipo + dati
                + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + blocco(b"IHDR", struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0))
        + blocco(b"IDAT", zlib.compress(b"".join(righe), 9))
        + blocco(b"IEND", b"")
    )


if __name__ == "__main__":
    png(Path(sys.argv[1]))
