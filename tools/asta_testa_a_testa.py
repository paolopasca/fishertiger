"""Tre metodi nella stessa asta, in competizione per gli stessi giocatori.

Differenza rispetto a tools/backtest.py: li' ogni metodo giocava un'asta separata contro
nove avversari a mercato. Qui i tre metodi sono nella STESSA lega e si contendono i
giocatori, che e' la situazione reale. Se il nostro modello e quello della repo vogliono
lo stesso attaccante, uno solo lo prende.

Composizione della lega (10 squadre):
    7  offrono il prezzo di mercato con rumore moltiplicativo (avversari realistici)
    1  usa il modello di regressione sulle presenze
    1  usa il metodo della repo (FVM per ruolo x moltiplicatore di qualita' limitato)
    1  offre il prezzo di mercato puro, come controllo calibrato

Avvertenza sulla potenza, da tenere presente leggendo i risultati. I semi riducono solo
la varianza DENTRO la stagione (629 punti); quella FRA stagioni (266) resta, perche' le
stagioni sono otto. Il pavimento sull'effetto minimo rilevabile e' 188 punti e non si
sposta aumentando le ripetizioni.

Uso: .venv/bin/python tools/asta_testa_a_testa.py [ripetizioni]
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import warnings

from selezione import build, prepare, DEMAND
from confronto_draft import (market_price, fit_predict, season_points,
                             SLOTS, PARTICIPANTS, CREDITS, MIN_PRICE, MODEL_PRESENZE)

warnings.filterwarnings("ignore")

RESERVE = 1
ORDER = ["P", "D", "C", "A"]          # la lega chiama per ruolo, in quest'ordine
SPLIT_REPO = {"P": 0.07, "D": 0.18, "C": 0.25, "A": 0.50}


def repo_ranking(pool: pd.DataFrame) -> np.ndarray:
    """Il metodo della repo: prezzo ancorato al FVM per ruolo, corretto da un
    moltiplicatore di qualita' limitato a [0.75, 1.25]."""
    values = np.zeros(len(pool))
    for role in SLOTS:
        mask = (pool.R == role).to_numpy()
        group = pool[mask]
        demand = SLOTS[role] * PARTICIPANTS
        ranked = group.punti_attesi.fillna(0).sort_values(ascending=False)
        cutoff = ranked.iloc[min(demand, len(ranked)) - 1] if len(ranked) else 0.0
        quality = group.punti_attesi.fillna(0.0)
        edge = (quality - cutoff) / np.maximum(1.0, np.maximum(quality, cutoff))
        values[mask] = group.costo.to_numpy() * np.clip(1 + edge * 0.4, 0.75, 1.25)
    return values


def run(pool: pd.DataFrame, willingness: dict[int, np.ndarray], rng) -> dict[int, list[int]]:
    """Asta per ruolo. Chi vince paga il secondo prezzo piu' uno."""
    credits = [CREDITS] * PARTICIPANTS
    need = [dict(SLOTS) for _ in range(PARTICIPANTS)]
    rosters: dict[int, list[int]] = {t: [] for t in range(PARTICIPANTS)}
    for role in ORDER:
        candidates = pool[pool.R == role].sort_values("costo", ascending=False)
        for position, row in candidates.iterrows():
            buyers = [t for t in range(PARTICIPANTS) if need[t][role] > 0]
            if not buyers:
                break
            bids = []
            for team in buyers:
                open_slots = sum(need[team].values())
                legal_max = credits[team] - RESERVE * (open_slots - 1)
                if legal_max < MIN_PRICE:
                    continue
                base = willingness[team][position]
                noise = float(rng.uniform(0.8, 1.25)) if team >= 3 else 1.0
                want = min(legal_max, max(MIN_PRICE, round(base * noise)))
                bids.append((want, float(rng.random()), team))
            if not bids:
                continue
            bids.sort(reverse=True)
            best = bids[0]
            runner = bids[1][0] if len(bids) > 1 else 0
            price = max(MIN_PRICE, min(best[0], runner + 1))
            winner = best[2]
            credits[winner] -= price
            need[winner][role] -= 1
            rosters[winner].append(position)
    return rosters


def main() -> None:
    repetitions = int(sys.argv[1]) if len(sys.argv) > 1 else 20
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

    NAMES = {0: "modello presenze", 1: "metodo repo", 2: "mercato puro"}
    rows = []
    for season in sorted(frame.stagione.unique()):
        pool = pool_all[pool_all.stagione == season].copy().reset_index(drop=True)
        pool["costo"] = market_price(pool)
        pool["mv_realizzata"] = pool.Id.map(realised[season].Mv).fillna(0.0)
        pool["fm_realizzata"] = pool.Id.map(realised[season].Fm).fillna(0.0)
        # Il valore atteso preseason che il metodo della repo usa come qualita'.
        pool["punti_attesi"] = pool.punti_prec.fillna(pool.punti_prec.median())

        model = fit_predict(data, MODEL_PRESENZE, season).to_numpy()
        # La predizione e' un rango: si converte in disponibilita' a pagare mantenendo
        # la stessa scala di spesa complessiva del mercato, cosi' i metodi partono pari.
        model_price = pd.Series(model).rank(pct=True).to_numpy()
        model_price = model_price * pool.costo.sum() / model_price.sum()

        willingness = {0: model_price, 1: repo_ranking(pool), 2: pool.costo.to_numpy()}
        for team in range(3, PARTICIPANTS):
            willingness[team] = pool.costo.to_numpy()

        for repetition in range(repetitions):
            rng = np.random.default_rng(abs(hash((season, repetition))) % (2 ** 32))
            rosters = run(pool, willingness, rng)
            for team, name in NAMES.items():
                picks = rosters[team]
                if len(picks) != sum(SLOTS.values()):
                    continue
                roster = pool.iloc[picks]
                rows.append({"stagione": season, "ripetizione": repetition,
                             "metodo": name, "punti": season_points(roster, rng.integers(1 << 30)),
                             "spesa": float(roster.costo.sum()),
                             "presenze_medie": float(roster.presenze.mean())})

    table = pd.DataFrame(rows)
    if table.empty:
        print("nessuna asta completata")
        return
    print(f"ASTA TESTA A TESTA, {repetitions} ripetizioni per stagione\n")
    print(table.groupby("metodo")[["punti", "spesa", "presenze_medie"]].mean().round(1).to_string())
    print("\nper stagione:")
    print(table.pivot_table(index="stagione", columns="metodo", values="punti").round(0).to_string())

    print("\nCONFRONTI APPAIATI (stessa asta, stessa stagione, stessa ripetizione)")
    wide = table.pivot_table(index=["stagione", "ripetizione"], columns="metodo", values="punti")
    for a, b in [("modello presenze", "metodo repo"),
                 ("modello presenze", "mercato puro"),
                 ("metodo repo", "mercato puro")]:
        if a not in wide or b not in wide:
            continue
        # Aggregando prima per stagione: la varianza fra stagioni e' quella che conta,
        # le ripetizioni dentro la stagione non sono osservazioni indipendenti.
        per_season = (wide[a] - wide[b]).groupby("stagione").mean()
        se = per_season.std(ddof=1) / np.sqrt(len(per_season))
        t = per_season.mean() / se if se > 0 else 0
        print(f"  {a:20s} - {b:18s} {per_season.mean():+8.1f} +- {se:5.1f}  "
              f"t = {t:5.2f}  {'REALE' if abs(t) > 2 else 'non distinguibile'}")
    table.to_csv("data/processed/asta_testa_a_testa.csv", index=False)


if __name__ == "__main__":
    main()
