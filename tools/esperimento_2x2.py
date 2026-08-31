"""Disegno 2x2: separa il contributo della VALUTAZIONE da quello dell'ALLOCATORE.

Finora i due erano confusi. Il confronto "noi contro loro" passava per un draft greedy
con ripartizione di budget per ruolo, che e' una regola arbitraria: misurava
l'ordinamento attraverso una lente distorta.

Qui si incrociano:

    valutazione:  mercato (rango del prezzo)      contro   modello presenze (regressione)
    allocatore:   greedy con split di ruolo       contro   knapsack multi-scelta esatto

Le righe misurano quanto vale la regressione, le colonne quanto vale l'ottimizzazione.
Prezzi, budget, vincoli e estrazioni di valutazione sono identici in tutte e quattro le
celle, quindi le differenze sono attribuibili.

CONTROLLO DI CORRETTEZZA ATTESO: a parita' di valutazione il knapsack deve dare un
valore obiettivo somma(v_i) maggiore o uguale al greedy. E' una garanzia matematica, non
un risultato empirico: se non vale, c'e' un bug.

Uso: .venv/bin/python tools/esperimento_2x2.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import warnings

import knapsack as K
from selezione import build, prepare, DEMAND
from confronto_draft import (market_price, fit_predict, draft, season_points,
                             SLOTS, PARTICIPANTS, CREDITS, SPLIT_MERCATO, MODEL_PRESENZE)

warnings.filterwarnings("ignore")


def main() -> None:
    frame = build()
    realised = {}
    for season in frame.stagione.unique():
        stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx",
                              sheet_name="Tutti", header=1)
        realised[season] = stats.set_index("Id")[["Mv", "Fm"]]

    pool_all = pd.concat([
        g.nlargest(DEMAND[role], "prezzo")
        for (_, role), g in frame.groupby(["stagione", "R"]) for role in [role]
    ], ignore_index=True)
    data = prepare(pool_all, "presenze")

    rows, checks = [], []
    for season in sorted(frame.stagione.unique()):
        pool = pool_all[pool_all.stagione == season].copy().reset_index(drop=True)
        pool["costo"] = market_price(pool)
        pool["mv_realizzata"] = pool.Id.map(realised[season].Mv).fillna(0.0)
        pool["fm_realizzata"] = pool.Id.map(realised[season].Fm).fillna(0.0)
        costs = pool.costo.to_numpy()

        valuations = {
            "mercato": pool.costo.rank(pct=True).to_numpy(),
            "modello presenze": fit_predict(data, MODEL_PRESENZE, season).to_numpy(),
        }
        seed = abs(hash(season)) % (2 ** 32)

        for valuation_name, values in valuations.items():
            ranking = pd.Series(values, index=pool.index)

            greedy = draft(pool, ranking, SPLIT_MERCATO)
            picks = K.solve(pool, values, costs, SLOTS, CREDITS)
            optimal = pool.iloc[picks]

            # Controllo di correttezza: il knapsack non puo' fare peggio sul suo obiettivo.
            greedy_objective = float(values[greedy.index.to_numpy()].sum()) if len(greedy) else float("-inf")
            optimal_objective = float(values[picks].sum())
            checks.append({"stagione": season, "valutazione": valuation_name,
                           "greedy": greedy_objective, "knapsack": optimal_objective,
                           "ok": optimal_objective >= greedy_objective - 1e-9})

            for allocator_name, roster in (("greedy con split", greedy), ("knapsack", optimal)):
                if roster.empty or len(roster) != sum(SLOTS.values()):
                    continue
                rows.append({
                    "stagione": season, "valutazione": valuation_name,
                    "allocatore": allocator_name,
                    "punti": season_points(roster, seed),
                    "spesa": float(roster.costo.sum()),
                    "presenze_medie": float(roster.presenze.mean()),
                })

    check_table = pd.DataFrame(checks)
    print("CONTROLLO DI CORRETTEZZA: knapsack >= greedy sull'obiettivo somma(v_i)")
    print(f"  rispettato in {check_table.ok.sum()} casi su {len(check_table)}")
    if not check_table.ok.all():
        print(check_table[~check_table.ok].to_string(index=False))
    guadagno = (check_table.knapsack - check_table.greedy) / check_table.greedy.abs()
    print(f"  guadagno medio sull'obiettivo: {guadagno.mean() * 100:+.1f}%\n")

    table = pd.DataFrame(rows)
    pivot = table.pivot_table(index="valutazione", columns="allocatore", values="punti")
    print("PUNTI STAGIONE REALIZZATI, media sulle 8 stagioni\n")
    print(pivot.round(1).to_string())

    print("\nEFFETTI SEPARATI (differenze appaiate per stagione)")
    wide = table.pivot_table(index="stagione", columns=["valutazione", "allocatore"],
                             values="punti")
    def paired(a, b, label):
        d = (wide[a] - wide[b]).dropna()
        se = d.std(ddof=1) / np.sqrt(len(d))
        t = d.mean() / se if se > 0 else 0
        print(f"  {label:52s} {d.mean():+8.1f} +- {se:5.1f}  t = {t:5.2f}  "
              f"{'REALE' if abs(t) > 2 else 'non distinguibile'}")

    paired(("modello presenze", "greedy con split"), ("mercato", "greedy con split"),
           "valutazione: modello - mercato, a greedy fisso")
    paired(("modello presenze", "knapsack"), ("mercato", "knapsack"),
           "valutazione: modello - mercato, a knapsack fisso")
    paired(("mercato", "knapsack"), ("mercato", "greedy con split"),
           "allocatore: knapsack - greedy, a mercato fisso")
    paired(("modello presenze", "knapsack"), ("modello presenze", "greedy con split"),
           "allocatore: knapsack - greedy, a modello fisso")
    paired(("modello presenze", "knapsack"), ("mercato", "greedy con split"),
           "totale: modello+knapsack contro mercato+greedy")

    print("\nDIAGNOSTICA DELLE ROSE")
    print(table.groupby(["valutazione", "allocatore"])[
        ["spesa", "presenze_medie"]].mean().round(1).to_string())
    table.to_csv("data/processed/esperimento_2x2.csv", index=False)


if __name__ == "__main__":
    main()
