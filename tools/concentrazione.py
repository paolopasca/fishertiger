"""I big vincono? Esperimento retrospettivo su stagioni vere.

Domanda: a parita' di budget, conviene concentrare i crediti su pochi fuoriclasse
o distribuirli? E quanto costa sbagliare il big?

Metodo. Per ogni stagione passata:
  1. prezzi = quotazione iniziale (preseason, non contaminata), riscalata perche' la
     somma sui 250 titolari eguagli i crediti della lega (10 x 500);
  2. si costruiscono rose legali 3-8-8-6 dentro 500 crediti a vari livelli di
     concentrazione della spesa;
  3. si valuta la rosa simulando 38 giornate con le presenze e le fantamedie
     REALIZZATE di quella stagione, scegliendo ogni giornata l'XI migliore fra i
     disponibili e applicando il modificatore difesa della lega di Paolo.

Due regimi di informazione, e la differenza fra i due e' il rischio di sbagliare:
  ORACOLO    si sceglie sapendo gia' come andra' la stagione;
  REALISTICO si sceglie con la sola informazione preseason (la quotazione).

Uso: .venv/bin/python tools/concentrazione.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

SEASONS = ["2018_19", "2019_20", "2020_21", "2021_22", "2022_23", "2023_24", "2024_25", "2025_26"]
SLOTS = {"P": 3, "D": 8, "C": 8, "A": 6}
PARTICIPANTS = 10
CREDITS = 500
FORMATIONS = ["3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-3-2", "5-4-1"]
DEFENSE_TIERS = [(6.0, 1), (6.5, 3), (7.0, 6)]
VOTE_SD = 0.8          # deviazione del voto per partita, vedi studio 1.7
MATCHDAYS = 38
ITERATIONS = 300


ALL_SEASONS = [
    "2015_16", "2016_17", "2017_18", "2018_19", "2019_20", "2020_21",
    "2021_22", "2022_23", "2023_24", "2024_25", "2025_26",
]


def previous_seasons(season: str, count: int = 3) -> list[str]:
    index = ALL_SEASONS.index(season)
    return ALL_SEASONS[max(0, index - count):index][::-1]


def load(season: str) -> pd.DataFrame:
    listone = pd.read_excel(f"data/raw/listone_{season}.xlsx", sheet_name="Tutti", header=1)
    stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
    frame = listone[["Id", "R", "Nome", "Qt.I"]].merge(
        stats[["Id", "Pv", "Mv", "Fm"]], on="Id", how="left"
    )
    frame[["Pv", "Mv", "Fm"]] = frame[["Pv", "Mv", "Fm"]].fillna(0.0)
    frame["p_gioca"] = (frame.Pv / MATCHDAYS).clip(0, 1)
    # Valore realizzato della stagione: punti totali portati a referto.
    frame["valore_vero"] = frame.Fm * frame.Pv

    return frame


def price_scale(frame: pd.DataFrame) -> pd.Series:
    """Riscala le quotazioni perche' i 250 titolari costino i crediti della lega."""
    drafted_total = 0.0
    for role, slots in SLOTS.items():
        demand = slots * PARTICIPANTS
        drafted_total += frame[frame.R == role].nlargest(demand, "Qt.I")["Qt.I"].sum()
    league_credits = CREDITS * PARTICIPANTS
    drafted_slots = sum(SLOTS.values()) * PARTICIPANTS
    factor = (league_credits - drafted_slots) / max(1.0, drafted_total - drafted_slots)
    return (1 + (frame["Qt.I"] - 1) * factor).clip(lower=1).round()


def build_roster(frame: pd.DataFrame, rank_by: str, split: dict[str, float],
                 top_share: float) -> pd.DataFrame | None:
    """Costruisce una rosa legale rispettando una ripartizione di budget per ruolo.

    `split`     quota del budget assegnata a ogni ruolo (somma 1);
    `top_share` quota del budget di ruolo concentrata sul giocatore piu' caro del ruolo.

    Senza disciplina per ruolo il greedy globale compra gli attaccanti, che costano di
    piu', e riempie la porta con giocatori da un credito che non giocano mai: la rosa
    non riesce piu' a schierare un XI legale.
    """
    picked: list[int] = []
    for role, slots in SLOTS.items():
        budget = split[role] * CREDITS
        candidates = frame[(frame.R == role) & (~frame.Id.isin(picked))]
        candidates = candidates.sort_values(rank_by, ascending=False)
        spent = 0.0
        taken = 0
        # Primo acquisto: il migliore che sta dentro la quota concentrata.
        cap = max(1.0, top_share * budget)
        for _, row in candidates.iterrows():
            if row.prezzo <= cap and row.prezzo <= budget - (slots - 1):
                picked.append(row.Id)
                spent += row.prezzo
                taken = 1
                break
        # Poi i migliori che restano dentro il budget di ruolo, sempre lasciando
        # un credito per ogni slot ancora scoperto.
        for _, row in candidates.iterrows():
            if taken >= slots:
                break
            if row.Id in picked:
                continue
            if spent + row.prezzo > budget - (slots - taken - 1):
                continue
            picked.append(row.Id)
            spent += row.prezzo
            taken += 1
        if taken < slots:
            return None
    roster = frame[frame.Id.isin(picked)].copy()
    return roster


def defense_bonus(keeper_vote, defender_votes):
    if keeper_vote is None or len(defender_votes) < 4:
        return 0
    average = (keeper_vote + sum(sorted(defender_votes, reverse=True)[:3])) / 4
    bonus = 0
    for threshold, value in DEFENSE_TIERS:
        if average >= threshold:
            bonus = value
    return bonus


def season_score(roster: pd.DataFrame, rng, iterations: int = ITERATIONS) -> np.ndarray:
    """Punti stagione simulati: disponibilita' casuale, fantamedia realizzata."""
    role = roster.R.to_numpy()
    prob = roster.p_gioca.to_numpy()
    fm = roster.Fm.to_numpy()
    mv = roster.Mv.to_numpy()
    counts = [tuple(int(v) for v in f.split("-")) for f in FORMATIONS]
    totals = np.zeros(iterations)
    for it in range(iterations):
        total = 0.0
        for _ in range(MATCHDAYS):
            plays = rng.random(len(prob)) < prob
            votes = mv + rng.normal(0, VOTE_SD, len(mv))
            best = None
            for d, c, a in counts:
                need = {"P": 1, "D": d, "C": c, "A": a}
                lineup, ok = [], True
                for r, k in need.items():
                    idx = np.where(plays & (role == r))[0]
                    if len(idx) < k:
                        ok = False
                        break
                    idx = idx[np.argsort(-fm[idx])][:k]
                    lineup.append((r, idx))
                if not ok:
                    continue
                points = sum(fm[idx].sum() for _, idx in lineup)
                keeper = next((votes[idx][0] for r, idx in lineup if r == "P"), None)
                defenders = next((list(votes[idx]) for r, idx in lineup if r == "D"), [])
                points += defense_bonus(keeper, defenders)
                if best is None or points > best:
                    best = points
            total += best if best is not None else 0.0
        totals[it] = total
    return totals


def main() -> None:
    # Ripartizioni da confrontare. La prima e' quella cablata nel repo.
    SPLITS = {
        "repo 7/18/25/50":   {"P": .07, "D": .18, "C": .25, "A": .50},
        "difesa 10/30/30/30": {"P": .10, "D": .30, "C": .30, "A": .30},
        "equilibrata 8/25/32/35": {"P": .08, "D": .25, "C": .32, "A": .35},
        "attacco 5/12/23/60": {"P": .05, "D": .12, "C": .23, "A": .60},
    }
    TOP_SHARES = [0.25, 0.45, 0.65]
    rng = np.random.default_rng(20262027)
    results = []
    for season in SEASONS:
        frame = load(season)
        frame["prezzo"] = price_scale(frame)
        frame = frame[frame.prezzo >= 1]
        for regime, column in (("oracolo", "valore_vero"), ("realistico", "prezzo")):
            for split_name, split in SPLITS.items():
                for top in TOP_SHARES:
                    roster = build_roster(frame, column, split, top)
                    if roster is None or len(roster) != sum(SLOTS.values()):
                        continue
                    scores = season_score(roster, rng, iterations=60)
                    results.append({
                        "stagione": season[2:7], "regime": regime,
                        "ripartizione": split_name, "concentrazione": top,
                        "punti": scores.mean(), "sd_interna": scores.std(),
                        "spesa": roster.prezzo.sum(),
                        "p_gioca_media": roster.p_gioca.mean(),
                        "portiere_titolare": roster[roster.R == "P"].p_gioca.max(),
                    })
    table = pd.DataFrame(results)
    if table.empty:
        print("nessuna rosa costruibile")
        return
    print("Punti stagione simulati, media sulle 8 stagioni\n")
    for regime in ("realistico", "oracolo"):
        sub = table[table.regime == regime]
        print(f"  REGIME {regime.upper()}")
        piv = sub.pivot_table(index="ripartizione", columns="concentrazione", values="punti")
        print(piv.round(0).to_string())
        print()
    print("RISCHIO nel regime realistico: stagione peggiore fra le 8")
    sub = table[table.regime == "realistico"]
    print(sub.pivot_table(index="ripartizione", columns="concentrazione",
                          values="punti", aggfunc="min").round(0).to_string())
    print()
    print("CONTROLLO DI SANITA' (deve essere ~500 di spesa e portiere che gioca)")
    print(table.groupby("ripartizione")[["spesa", "p_gioca_media", "portiere_titolare"]]
          .mean().round(2).to_string())
    table.to_csv("data/processed/concentrazione.csv", index=False)
    print("\nsalvato in data/processed/concentrazione.csv")


if __name__ == "__main__":
    main()
