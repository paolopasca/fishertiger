"""Quale insieme di variabili predice meglio, misurato FUORI campione.

Perche' non si sceglie con l'R2 semplice. L'R2 misura quanta varianza il modello spiega
SUI DATI CON CUI E' STATO ADDESTRATO, e aggiungendo variabili non puo' che salire: anche
una colonna di numeri casuali abbassa un po' i residui. Con abbastanza variabili si
arriva a R2 = 1 su qualunque cosa, e il modello non predice niente.

Il criterio corretto e' l'R2 fuori campione. Qui si usa leave-one-season-out: si stima il
modello su tutte le stagioni tranne una, si predice quella, si misura li'. Una variabile
che serve davvero alza l'R2 anche sulla stagione che non ha visto; una che cattura rumore
lo abbassa.

Si prova ogni sottoinsieme di variabili fino a sei, si tiene il migliore per ogni
dimensione, e si guarda dove smette di migliorare.

Uso: .venv/bin/python tools/selezione.py [presenze|punti]
"""
from __future__ import annotations

import itertools
import sys

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

SEASONS = ["2015_16", "2016_17", "2017_18", "2018_19", "2019_20", "2020_21",
           "2021_22", "2022_23", "2023_24", "2024_25", "2025_26"]
DEMAND = {"P": 30, "D": 80, "C": 80, "A": 60}


def read(season: str) -> pd.DataFrame:
    listone = pd.read_excel(f"data/raw/listone_{season}.xlsx", sheet_name="Tutti", header=1)
    stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
    frame = listone[["Id", "R", "Nome", "Squadra", "Qt.I", "Qt.A"]].merge(
        stats[["Id", "Pv", "Mv", "Fm", "Gf", "Ass", "Amm", "Esp"]], on="Id", how="inner")
    frame["punti"] = frame.Fm * frame.Pv
    return frame


def build() -> pd.DataFrame:
    frames = {s: read(s) for s in SEASONS}
    rows = []
    for i in range(3, len(SEASONS)):
        season = SEASONS[i]
        now = frames[season]
        prev1 = frames[SEASONS[i - 1]].set_index("Id")
        prev2 = frames[SEASONS[i - 2]].set_index("Id")
        prev3 = frames[SEASONS[i - 3]].set_index("Id")
        d = now.set_index("Id")
        out = pd.DataFrame(index=d.index)
        out["stagione"] = season
        out["R"] = d.R
        out["squadra"] = d.Squadra
        out["prezzo"] = d["Qt.I"]
        out["punti"] = d.punti
        out["presenze"] = d.Pv

        out["pv_prec"] = prev1.Pv.reindex(d.index)
        out["pv_prec2"] = prev2.Pv.reindex(d.index)
        out["fm_prec"] = prev1.Fm.reindex(d.index)
        out["mv_prec"] = prev1.Mv.reindex(d.index)
        out["punti_prec"] = (prev1.Fm * prev1.Pv).reindex(d.index)
        out["gol90_prec"] = (prev1.Gf / prev1.Pv.replace(0, np.nan)).reindex(d.index)
        out["ass90_prec"] = (prev1.Ass / prev1.Pv.replace(0, np.nan)).reindex(d.index)
        out["amm90_prec"] = (prev1.Amm / prev1.Pv.replace(0, np.nan)).reindex(d.index)
        out["trend_presenze"] = out.pv_prec - out.pv_prec2
        out["costanza_presenze"] = -pd.concat(
            [prev1.Pv, prev2.Pv, prev3.Pv], axis=1).reindex(d.index).std(axis=1)
        out["esperienza"] = pd.concat(
            [prev1.Pv.notna(), prev2.Pv.notna(), prev3.Pv.notna()], axis=1
        ).reindex(d.index).sum(axis=1)
        out["cambio_squadra"] = (d.Squadra != prev1.Squadra.reindex(d.index)).astype(float)
        out["revisione_mercato"] = d["Qt.I"] - prev1["Qt.A"].reindex(d.index)

        # --- variabili nuove ---------------------------------------------------------
        # Concorrenza nel ruolo dentro la squadra: quanti compagni dello stesso ruolo
        # costano piu' di lui. E' la misura piu' diretta della posizione nelle gerarchie,
        # ed e' nota prima che la stagione inizi.
        out["concorrenza_ruolo"] = now.groupby(["Squadra", "R"])["Qt.I"].rank(
            ascending=False, method="min").to_numpy() - 1

        # Forza della squadra: somma delle quotazioni della rosa. Proxy della qualita'
        # del club, che muove sia il rendimento sia la probabilita' di giocare.
        team_strength = now.groupby("Squadra")["Qt.I"].sum()
        out["forza_squadra"] = d.Squadra.map(team_strength).to_numpy()

        # Salto di livello: differenza di forza fra la squadra nuova e quella vecchia.
        prev_strength = frames[SEASONS[i - 1]].groupby("Squadra")["Qt.I"].sum()
        out["forza_squadra_prec"] = prev1.Squadra.reindex(d.index).map(prev_strength).to_numpy()
        out["salto_squadra"] = out.forza_squadra - out.forza_squadra_prec

        # Neopromossa: la squadra non c'era in Serie A l'anno prima.
        previous_teams = set(frames[SEASONS[i - 1]].Squadra.unique())
        out["neopromossa"] = (~d.Squadra.isin(previous_teams)).astype(float).to_numpy()

        # Peso dentro la propria squadra: quota della quotazione totale del club.
        out["peso_in_squadra"] = out.prezzo / out.forza_squadra

        # Quanto era titolare rispetto ai compagni di ruolo l'anno prima.
        pv_by_role = prev1.groupby(["Squadra", "R"]).Pv.rank(ascending=False, method="min")
        out["gerarchia_prec"] = pv_by_role.reindex(d.index).to_numpy()
        rows.append(out.reset_index())
    return pd.concat(rows, ignore_index=True)


FEATURES = [
    "pv_prec", "punti_prec", "fm_prec", "mv_prec", "gol90_prec", "ass90_prec",
    "amm90_prec", "trend_presenze", "costanza_presenze", "esperienza",
    "cambio_squadra", "revisione_mercato", "concorrenza_ruolo", "forza_squadra",
    "salto_squadra", "neopromossa", "peso_in_squadra", "gerarchia_prec",
]


def prepare(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    """Ranghi dentro ogni stagione, cosi' le scale diverse fra stagioni non contano."""
    pieces = []
    for season, group in frame.groupby("stagione"):
        piece = {"stagione": season, "y": group[target].rank(pct=True),
                 "prezzo": group["prezzo"].rank(pct=True)}
        for column in FEATURES:
            values = group[column]
            piece[column] = values.fillna(values.median()).rank(pct=True)
        pieces.append(pd.DataFrame(piece))
    return pd.concat(pieces, ignore_index=True)


def cv_r2(data: pd.DataFrame, columns: list[str]) -> float:
    """R2 fuori campione, leave-one-season-out."""
    residual, total = 0.0, 0.0
    for season in data.stagione.unique():
        train = data[data.stagione != season]
        test = data[data.stagione == season]
        X = np.column_stack([np.ones(len(train))] + [train[c].to_numpy() for c in columns])
        beta, *_ = np.linalg.lstsq(X, train.y.to_numpy(), rcond=None)
        Xt = np.column_stack([np.ones(len(test))] + [test[c].to_numpy() for c in columns])
        prediction = Xt @ beta
        y = test.y.to_numpy()
        residual += float(((y - prediction) ** 2).sum())
        total += float(((y - y.mean()) ** 2).sum())
    return 1 - residual / total


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "punti"
    frame = build()
    drafted = pd.concat([
        g.nlargest(DEMAND[role], "prezzo")
        for (_, role), g in frame.groupby(["stagione", "R"]) for role in [role]
    ], ignore_index=True)
    data = prepare(drafted, target)

    print(f"SELEZIONE DELLE VARIABILI, bersaglio {target.upper()}, n = {len(data)}")
    print("R2 misurato FUORI campione (leave-one-season-out): una variabile inutile lo")
    print("abbassa invece di alzarlo, quindi si puo' usare per scegliere.\n")

    base = cv_r2(data, ["prezzo"])
    print(f"  solo prezzo di mercato: R2 = {base:.4f}\n")

    print("  MIGLIORE PER OGNI NUMERO DI VARIABILI AGGIUNTE AL PREZZO")
    print(f"  {'k':>2s} {'R2 fuori campione':>18s} {'guadagno':>9s}   variabili")
    best_overall, best_columns = base, ["prezzo"]
    previous = base
    for k in range(1, 6):
        best_score, best_set = -np.inf, None
        for combination in itertools.combinations(FEATURES, k):
            score = cv_r2(data, ["prezzo", *combination])
            if score > best_score:
                best_score, best_set = score, combination
        marker = "" if best_score > previous else "   <- non migliora piu'"
        print(f"  {k:2d} {best_score:18.4f} {best_score - base:+9.4f}   {', '.join(best_set)}{marker}")
        if best_score > best_overall:
            best_overall, best_columns = best_score, ["prezzo", *best_set]
        previous = best_score

    print(f"\n  migliore in assoluto: R2 = {best_overall:.4f} con {best_columns}")

    # Coefficienti del modello scelto, stimati su tutto.
    X = np.column_stack([np.ones(len(data))] + [data[c].to_numpy() for c in best_columns])
    y = data.y.to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    cov = (resid @ resid / (len(data) - X.shape[1])) * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    print("\n  coefficienti del modello scelto:")
    for name, b, s in zip(best_columns, beta[1:], se[1:]):
        print(f"    {name:20s} {b:+7.3f}  t = {b / s:6.2f}")


if __name__ == "__main__":
    main()
