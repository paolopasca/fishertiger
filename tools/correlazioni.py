"""Cerca segnali che aggiungano informazione OLTRE il prezzo di mercato.

Un segnale che correla coi punti realizzati non serve a niente se il mercato lo sa gia':
il prezzo lo incorpora e comprare quel giocatore costa quanto vale. Serve la parte di
segnale ORTOGONALE al prezzo. Per ogni candidato si stima

    rango(risultato) ~ rango(prezzo preseason) + rango(segnale) + effetti fissi stagione

e si guarda il coefficiente del segnale: se e' diverso da zero, quel segnale dice
qualcosa che il mercato non sta prezzando.

Due bersagli, perche' rispondono a domande diverse:
  presenze  quante volte prendera' voto  (l'83-94% della varianza dei punti)
  punti     il risultato finale

Uso: .venv/bin/python tools/correlazioni.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

SEASONS = ["2015_16", "2016_17", "2017_18", "2018_19", "2019_20", "2020_21",
           "2021_22", "2022_23", "2023_24", "2024_25", "2025_26"]
DEMAND = {"P": 30, "D": 80, "C": 80, "A": 60}
MATCHDAYS = 38


def read(season: str) -> pd.DataFrame:
    listone = pd.read_excel(f"data/raw/listone_{season}.xlsx", sheet_name="Tutti", header=1)
    stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
    frame = listone[["Id", "R", "Nome", "Squadra", "Qt.I", "Qt.A"]].merge(
        stats[["Id", "Pv", "Mv", "Fm", "Gf", "Ass", "Amm", "Esp"]], on="Id", how="inner")
    frame["punti"] = frame.Fm * frame.Pv
    frame["stagione"] = season
    return frame


def build() -> pd.DataFrame:
    frames = {s: read(s) for s in SEASONS}
    rows = []
    for i in range(3, len(SEASONS)):
        season = SEASONS[i]
        now = frames[season]
        prev1, prev2, prev3 = (frames[SEASONS[i - k]].set_index("Id") for k in (1, 2, 3))
        d = now.set_index("Id")
        out = pd.DataFrame(index=d.index)
        out["stagione"] = season
        out["R"] = d.R
        out["prezzo"] = d["Qt.I"]
        out["punti"] = d.punti
        out["presenze"] = d.Pv
        out["fm"] = d.Fm

        out["pv_prec"] = prev1.Pv.reindex(d.index)
        out["pv_prec2"] = prev2.Pv.reindex(d.index)
        out["fm_prec"] = prev1.Fm.reindex(d.index)
        out["mv_prec"] = prev1.Mv.reindex(d.index)
        out["punti_prec"] = (prev1.Fm * prev1.Pv).reindex(d.index)
        out["gol90_prec"] = (prev1.Gf / prev1.Pv.replace(0, np.nan)).reindex(d.index)
        out["ass90_prec"] = (prev1.Ass / prev1.Pv.replace(0, np.nan)).reindex(d.index)
        out["amm90_prec"] = (prev1.Amm / prev1.Pv.replace(0, np.nan)).reindex(d.index)

        # Segnali costruiti
        out["revisione_mercato"] = d["Qt.I"] - prev1["Qt.A"].reindex(d.index)
        out["trend_presenze"] = out.pv_prec - out.pv_prec2
        out["costanza_presenze"] = -pd.concat(
            [prev1.Pv, prev2.Pv, prev3.Pv], axis=1).reindex(d.index).std(axis=1)
        out["esperienza"] = pd.concat(
            [prev1.Pv.notna(), prev2.Pv.notna(), prev3.Pv.notna()], axis=1
        ).reindex(d.index).sum(axis=1)
        out["cambio_squadra"] = (d.Squadra != prev1.Squadra.reindex(d.index)).astype(float)
        # Sorpresa dell'anno prima rispetto a due anni prima: chi esplode, regredisce?
        out["sorpresa_prec"] = out.fm_prec - prev2.Fm.reindex(d.index)
        out["scarto_prezzo_punti"] = (
            d["Qt.I"].rank(pct=True) - out.punti_prec.rank(pct=True))
        rows.append(out.reset_index())
    return pd.concat(rows, ignore_index=True)


def partial_effect(frame: pd.DataFrame, signal: str, target: str) -> tuple[float, float, int]:
    """Coefficiente del segnale in rango, al netto del prezzo e della stagione."""
    d = frame[["stagione", "prezzo", signal, target]].dropna()
    if len(d) < 200:
        return float("nan"), float("nan"), len(d)
    pieces = []
    for _, group in d.groupby("stagione"):
        if len(group) < 30:
            continue
        g = pd.DataFrame({
            "y": group[target].rank(pct=True),
            "p": group["prezzo"].rank(pct=True),
            "x": group[signal].rank(pct=True),
        })
        pieces.append(g)
    if not pieces:
        return float("nan"), float("nan"), 0
    g = pd.concat(pieces, ignore_index=True)
    X = np.column_stack([np.ones(len(g)), g.p.to_numpy(), g.x.to_numpy()])
    y = g.y.to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    residual = y - X @ beta
    dof = len(g) - X.shape[1]
    sigma2 = residual @ residual / dof
    cov = sigma2 * np.linalg.inv(X.T @ X)
    return float(beta[2]), float(beta[2] / np.sqrt(cov[2, 2])), len(g)


def main() -> None:
    frame = build()
    # Solo i giocatori che una lega da 10 sorteggerebbe: sul resto non si decide nulla.
    drafted = pd.concat([
        g.nlargest(DEMAND[role], "prezzo")
        for (_, role), g in frame.groupby(["stagione", "R"])
        for role in [role]
    ], ignore_index=True)

    signals = ["pv_prec", "fm_prec", "mv_prec", "punti_prec", "gol90_prec", "ass90_prec",
               "amm90_prec", "revisione_mercato", "trend_presenze", "costanza_presenze",
               "esperienza", "cambio_squadra", "sorpresa_prec", "scarto_prezzo_punti"]

    for target in ("presenze", "punti"):
        print(f"\n{'=' * 78}")
        print(f"SEGNALI CHE AGGIUNGONO INFORMAZIONE OLTRE IL PREZZO  ->  bersaglio: {target}")
        print(f"{'=' * 78}")
        print(f"{'segnale':22s} {'coeff':>8s} {'t':>7s} {'n':>7s}   interpretazione")
        results = []
        for signal in signals:
            beta, t, n = partial_effect(drafted, signal, target)
            results.append((signal, beta, t, n))
        for signal, beta, t, n in sorted(results, key=lambda r: -abs(r[2] if r[2] == r[2] else 0)):
            if beta != beta:
                continue
            verdict = ("NIENTE" if abs(t) < 2
                       else ("aggiunge, segno +" if beta > 0 else "aggiunge, segno -"))
            print(f"{signal:22s} {beta:8.3f} {t:7.2f} {n:7d}   {verdict}")

    print(f"\n{'=' * 78}")
    print("LO STESSO, SOLO SUGLI ATTACCANTI (dove il mercato e' piu' forte)")
    print(f"{'=' * 78}")
    att = drafted[drafted.R == "A"]
    for signal in ["pv_prec", "revisione_mercato", "trend_presenze", "costanza_presenze",
                   "gol90_prec", "cambio_squadra"]:
        beta, t, n = partial_effect(att, signal, "punti")
        if beta == beta:
            print(f"  {signal:22s} coeff {beta:7.3f}  t {t:6.2f}  n {n}")


if __name__ == "__main__":
    main()


def multivariata(frame: pd.DataFrame, signals: list[str], target: str):
    """Tutti i segnali insieme, non uno alla volta.

    Girare una regressione per segnale sovrastima: due segnali che portano la stessa
    informazione risultano entrambi significativi da soli, ma insieme uno dei due si
    spegne. Qui si stima un modello unico e si legge quale sopravvive.
    """
    d = frame[["stagione", "prezzo", target] + signals].dropna()
    pieces = []
    for _, group in d.groupby("stagione"):
        if len(group) < 30:
            continue
        piece = {"y": group[target].rank(pct=True), "prezzo": group["prezzo"].rank(pct=True)}
        for s in signals:
            piece[s] = group[s].rank(pct=True)
        pieces.append(pd.DataFrame(piece))
    g = pd.concat(pieces, ignore_index=True)
    cols = ["prezzo"] + signals
    X = np.column_stack([np.ones(len(g))] + [g[c].to_numpy() for c in cols])
    y = g.y.to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = len(g) - X.shape[1]
    cov = (resid @ resid / dof) * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
    # Quanto spiega il solo prezzo, per misurare cosa aggiungono gli altri.
    Xp = np.column_stack([np.ones(len(g)), g["prezzo"].to_numpy()])
    bp, *_ = np.linalg.lstsq(Xp, y, rcond=None)
    rp = y - Xp @ bp
    r2_prezzo = 1 - (rp @ rp) / ((y - y.mean()) @ (y - y.mean()))
    return cols, beta[1:], se[1:], r2, r2_prezzo, len(g)


if __name__ != "__main__":
    pass
