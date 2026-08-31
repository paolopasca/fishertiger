"""Chi sceglie meglio: il metodo della repo, il mercato, o il modello sui segnali.

Perche' non si usa la simulazione d'asta completa. Quella aggiunge il rumore delle
offerte casuali degli avversari, che alza la deviazione delle differenze appaiate a 683
punti stagione. Con 8 stagioni il minimo rilevabile diventa 188 punti, e sotto quella
soglia nessun confronto e' leggibile.

Qui si toglie il rumore. Ogni metodo costruisce la rosa dallo stesso pool, agli STESSI
prezzi di mercato, con lo stesso budget e gli stessi vincoli di ruolo. L'unica differenza
e' l'ordine con cui sceglie. Le rose vengono poi valutate con le STESSE estrazioni Monte
Carlo sui rendimenti realizzati. Resta solo la varianza fra stagioni.

Questo misura la qualita' dell'ordinamento, non la meccanica d'asta.

Uso: .venv/bin/python tools/confronto_draft.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import warnings

from selezione import build, prepare, FEATURES, DEMAND

warnings.filterwarnings("ignore")

SLOTS = {"P": 3, "D": 8, "C": 8, "A": 6}
PARTICIPANTS = 10
CREDITS = 500
MIN_PRICE = 1
FORMATIONS = [(3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2), (4, 5, 1), (5, 3, 2), (5, 4, 1)]
DEFENSE_TIERS = [(6.0, 1), (6.5, 3), (7.0, 6)]
VOTE_SD = 0.8
MATCHDAYS = 38
ITERATIONS = 200
# Ripartizione del budget: quella cablata nella repo contro quella implicita nel mercato.
SPLIT_REPO = {"P": 0.07, "D": 0.18, "C": 0.25, "A": 0.50}
SPLIT_MERCATO = {"P": 0.07, "D": 0.19, "C": 0.35, "A": 0.39}

MODEL_PRESENZE = ["prezzo", "pv_prec", "cambio_squadra", "forza_squadra"]
MODEL_PUNTI = ["prezzo", "punti_prec", "cambio_squadra", "peso_in_squadra"]


def market_price(frame: pd.DataFrame) -> pd.Series:
    drafted = sum(
        frame[frame.R == role].nlargest(slots * PARTICIPANTS, "prezzo")["prezzo"].sum()
        for role, slots in SLOTS.items())
    seats = sum(SLOTS.values()) * PARTICIPANTS
    factor = (CREDITS * PARTICIPANTS - seats) / max(1.0, drafted - seats)
    return (1 + (frame["prezzo"] - 1) * factor).clip(lower=MIN_PRICE).round()


def fit_predict(data: pd.DataFrame, columns: list[str], season: str) -> pd.Series:
    """Addestra sulle altre stagioni, predice questa. Nessuna informazione dal futuro."""
    train = data[data.stagione != season]
    test = data[data.stagione == season]
    X = np.column_stack([np.ones(len(train))] + [train[c].to_numpy() for c in columns])
    beta, *_ = np.linalg.lstsq(X, train.y.to_numpy(), rcond=None)
    Xt = np.column_stack([np.ones(len(test))] + [test[c].to_numpy() for c in columns])
    return pd.Series(Xt @ beta, index=test.index)


def draft(frame: pd.DataFrame, ranking: pd.Series, split: dict[str, float]) -> pd.DataFrame:
    """Compra il meglio per `ranking` dentro il budget di ogni ruolo.

    La condizione di ammissibilita' deve riservare il costo VERO degli slot che restano,
    non il prezzo minimo teorico di un credito. Nel listone il difensore piu' economico
    costa 10, quindi riservare 1 per slot fa accettare acquisti che rendono impossibile
    completare il reparto: si comprano due difensori cari e restano sei slot con dieci
    crediti. La condizione corretta e'

        speso + costo_i + somma dei (slots - presi - 1) piu' economici rimasti <= budget

    che e' esatta perche' i costi sono fissi e noti.
    """
    picked = []
    for role, slots in SLOTS.items():
        budget = split[role] * CREDITS
        candidates = frame[frame.R == role].assign(rank=ranking).sort_values(
            "rank", ascending=False)
        spent, taken = 0.0, 0
        chosen: set = set()
        for identifier, row in candidates.iterrows():
            if taken >= slots:
                break
            remaining_slots = slots - taken - 1
            others = candidates.drop(index=list(chosen) + [identifier]).costo
            reserve = float(others.nsmallest(remaining_slots).sum()) if remaining_slots else 0.0
            if spent + row.costo + reserve > budget:
                continue
            picked.append(identifier)
            chosen.add(identifier)
            spent += row.costo
            taken += 1
        if taken < slots:
            return pd.DataFrame()
    return frame.loc[picked]


def defense_bonus(keeper, defenders):
    if keeper is None or len(defenders) < 4:
        return 0
    average = (keeper + sum(sorted(defenders, reverse=True)[:3])) / 4
    bonus = 0
    for threshold, value in DEFENSE_TIERS:
        if average >= threshold:
            bonus = value
    return bonus


def season_points(roster: pd.DataFrame, seed: int) -> float:
    rng = np.random.default_rng(seed)
    role = roster.R.to_numpy()
    prob = (roster.presenze / MATCHDAYS).clip(0, 1).to_numpy()
    fm = roster.fm_realizzata.to_numpy()
    mv = roster.mv_realizzata.to_numpy()
    totals = []
    for _ in range(ITERATIONS):
        total = 0.0
        for _ in range(MATCHDAYS):
            plays = rng.random(len(prob)) < prob
            votes = mv + rng.normal(0, VOTE_SD, len(mv))
            best = None
            for d, c, a in FORMATIONS:
                need = {"P": 1, "D": d, "C": c, "A": a}
                picked, ok = {}, True
                for r, k in need.items():
                    idx = np.where(plays & (role == r))[0]
                    if len(idx) < k:
                        ok = False
                        break
                    picked[r] = idx[np.argsort(-fm[idx])][:k]
                if not ok:
                    continue
                points = sum(fm[i].sum() for i in picked.values())
                points += defense_bonus(votes[picked["P"]][0], list(votes[picked["D"]]))
                if best is None or points > best:
                    best = points
            total += best if best is not None else 0.0
        totals.append(total)
    return float(np.mean(totals))


def main() -> None:
    frame = build()
    raw = pd.read_pickle("data/processed/_draft_raw.pkl") if False else None
    # Rendimenti realizzati, che servono solo per il voto finale.
    frames = {}
    for season in frame.stagione.unique():
        stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
        frames[season] = stats.set_index("Id")[["Mv", "Fm"]]

    drafted_pool = pd.concat([
        g.nlargest(DEMAND[role], "prezzo")
        for (_, role), g in frame.groupby(["stagione", "R"]) for role in [role]
    ], ignore_index=True)
    data_presenze = prepare(drafted_pool, "presenze")
    data_punti = prepare(drafted_pool, "punti")

    rows = []
    for season in sorted(frame.stagione.unique()):
        pool = drafted_pool[drafted_pool.stagione == season].copy().reset_index(drop=True)
        pool["costo"] = market_price(pool)
        pool["mv_realizzata"] = pool.Id.map(frames[season].Mv).fillna(0.0)
        pool["fm_realizzata"] = pool.Id.map(frames[season].Fm).fillna(0.0)

        mask = data_punti.stagione == season
        idx = pool.index
        predictions = {
            "modello punti": fit_predict(data_punti, MODEL_PUNTI, season).to_numpy(),
            "modello presenze": fit_predict(data_presenze, MODEL_PRESENZE, season).to_numpy(),
        }
        methods = {
            "mercato": (pd.Series(pool.costo.rank(pct=True).to_numpy(), index=idx), SPLIT_MERCATO),
            "repo (FVM + ripartizione cablata)": (
                pd.Series(pool.costo.rank(pct=True).to_numpy(), index=idx), SPLIT_REPO),
            "modello punti": (pd.Series(predictions["modello punti"], index=idx), SPLIT_MERCATO),
            "modello presenze": (pd.Series(predictions["modello presenze"], index=idx), SPLIT_MERCATO),
        }
        seed = abs(hash(season)) % (2 ** 32)
        for name, (ranking, split) in methods.items():
            roster = draft(pool, ranking, split)
            if roster.empty:
                continue
            rows.append({"stagione": season, "metodo": name,
                         "punti": season_points(roster, seed),
                         "spesa": roster.costo.sum(),
                         "presenze_medie": roster.presenze.mean()})

    table = pd.DataFrame(rows)
    pivot = table.pivot_table(index="stagione", columns="metodo", values="punti")
    print("PUNTI STAGIONE DELLA ROSA COSTRUITA, stessi prezzi e stesso budget\n")
    print(pivot.round(0).to_string())
    print("\nmedie:")
    print(pivot.mean().round(1).to_string())
    print("\nCONFRONTI APPAIATI contro il metodo della repo")
    base = pivot["repo (FVM + ripartizione cablata)"]
    for column in pivot.columns:
        if column == base.name:
            continue
        d = (pivot[column] - base).dropna()
        se = d.std(ddof=1) / np.sqrt(len(d))
        t = d.mean() / se if se > 0 else 0
        print(f"  {column:36s} {d.mean():+8.1f} +- {se:5.1f}  t = {t:5.2f}  "
              f"{'REALE' if abs(t) > 2 else 'non distinguibile'}")
    table.to_csv("data/processed/confronto_draft.csv", index=False)


if __name__ == "__main__":
    main()
