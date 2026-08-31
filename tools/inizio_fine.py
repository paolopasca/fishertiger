"""Quanto si muove il valore di un giocatore dall'inizio alla fine della stagione.

Domanda di Paolo: per ogni stagione, quanto vale un giocatore a campionato non
iniziato e quanto vale alla fine, e cosa varia poco.

Tre grandezze per stagione:
  Qt.I  quotazione iniziale, cioe' il prezzo preseason;
  Qt.A  quotazione a fine stagione, il prezzo aggiornato dal rendimento;
  punti realizzati = fantamedia per presenze.

Uso: .venv/bin/python tools/inizio_fine.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

SEASONS = ["2015_16", "2016_17", "2017_18", "2018_19", "2019_20", "2020_21",
           "2021_22", "2022_23", "2023_24", "2024_25", "2025_26"]
DEMAND = {"P": 30, "D": 80, "C": 80, "A": 60}


def spearman(a, b) -> float:
    a, b = pd.Series(np.asarray(a, float)), pd.Series(np.asarray(b, float))
    ok = a.notna() & b.notna()
    return float(a[ok].rank().corr(b[ok].rank())) if ok.sum() > 2 else float("nan")


def load(season: str) -> pd.DataFrame:
    listone = pd.read_excel(f"data/raw/listone_{season}.xlsx", sheet_name="Tutti", header=1)
    stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
    frame = listone[["Id", "R", "Nome", "Qt.I", "Qt.A"]].merge(
        stats[["Id", "Pv", "Mv", "Fm"]], on="Id", how="inner"
    )
    frame["punti"] = frame.Fm * frame.Pv
    return frame


def main() -> None:
    rows = []
    for season in SEASONS:
        frame = load(season)
        played = frame[frame.Pv > 0]
        # Solo i giocatori che una lega da 10 squadre sorteggerebbe davvero.
        drafted = pd.concat([
            frame[frame.R == role].nlargest(count, "Qt.I") for role, count in DEMAND.items()
        ])
        drafted = drafted[drafted.Pv > 0]
        rows.append({
            "stagione": season[2:7],
            "n": len(played),
            "inizio-fine": spearman(played["Qt.I"], played["Qt.A"]),
            "inizio-punti": spearman(played["Qt.I"], played.punti),
            "fine-punti": spearman(played["Qt.A"], played.punti),
            "inizio-fine (top250)": spearman(drafted["Qt.I"], drafted["Qt.A"]),
            "inizio-punti (top250)": spearman(drafted["Qt.I"], drafted.punti),
            "quota rivalutati": float((played["Qt.A"] > played["Qt.I"]).mean()),
            "var. media Qt": float((played["Qt.A"] - played["Qt.I"]).mean()),
            "var. assoluta media": float((played["Qt.A"] - played["Qt.I"]).abs().mean()),
            "Qt.I media": float(played["Qt.I"].mean()),
        })
    table = pd.DataFrame(rows).set_index("stagione")

    print("QUANTO IL MERCATO RIVEDE I PREZZI DURANTE LA STAGIONE\n")
    print(table[["n", "inizio-fine", "inizio-punti", "fine-punti"]].round(3).to_string())
    print("\n  medie:", " ".join(
        f"{c}={table[c].mean():.3f}" for c in ["inizio-fine", "inizio-punti", "fine-punti"]))
    print("\n  Lo scarto fra 'inizio-punti' e 'fine-punti' e' quanto il mercato impara")
    print("  guardando la stagione: e' la parte che a inizio asta NON puoi sapere.")

    print("\n\nSOLO I 250 CHE UNA LEGA DA 10 SORTEGGEREBBE\n")
    print(table[["inizio-fine (top250)", "inizio-punti (top250)"]].round(3).to_string())
    print("\n  medie:", " ".join(
        f"{c}={table[c].mean():.3f}" for c in ["inizio-fine (top250)", "inizio-punti (top250)"]))

    print("\n\nDI QUANTO SI MUOVONO LE QUOTAZIONI\n")
    print(table[["Qt.I media", "var. media Qt", "var. assoluta media", "quota rivalutati"]]
          .round(3).to_string())
    movimento = (table["var. assoluta media"] / table["Qt.I media"]).mean()
    print(f"\n  movimento assoluto medio = {movimento * 100:.1f}% della quotazione iniziale")

    # Cosa varia poco: persistenza anno su anno delle grandezze fondamentali.
    print("\n\nCOSA VARIA POCO DA UNA STAGIONE ALL'ALTRA")
    print("  (correlazione fra la stagione t e la t+1, giocatori con Pv>=15 in entrambe)\n")
    persist = {k: [] for k in ["Qt.I", "Pv", "Mv", "Fm", "punti"]}
    for first, second in zip(SEASONS, SEASONS[1:]):
        a, b = load(first), load(second)
        merged = a.merge(b, on="Id", suffixes=("_0", "_1"))
        merged = merged[(merged.Pv_0 >= 15) & (merged.Pv_1 >= 15)]
        for key in persist:
            persist[key].append(spearman(merged[f"{key}_0"], merged[f"{key}_1"]))
    for key, values in persist.items():
        bar = "#" * int(round(np.nanmean(values) * 40))
        print(f"    {key:7s} {np.nanmean(values):.3f}  {bar}")
    print("\n  Piu' alto = piu' stabile, quindi piu' prevedibile dall'anno prima.")

    table.to_csv("data/processed/inizio_fine.csv")
    print("\nsalvato in data/processed/inizio_fine.csv")


if __name__ == "__main__":
    main()
