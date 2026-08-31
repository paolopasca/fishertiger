"""Shrinkage empirical Bayes sui regressori, e la cura alla maledizione dell'ottimizzatore.

PERCHE'

La fantamedia di un giocatore in una stagione e' una media campionaria su Pv partite,
quindi ha varianza s^2 / Pv. Chi ha giocato 12 partite ha una stima tre volte piu'
rumorosa di chi ne ha giocate 35. Trattarle uguali e' dimostrabilmente subottimale:
per il teorema di Stein, in dimensione >= 3 la media campionaria e' inammissibile sotto
perdita quadratica, e lo stimatore che restringe verso la media la domina UNIFORMEMENTE,
cioe' per ogni valore vero del parametro, senza bisogno di credere a un prior.

La versione empirical Bayes, che e' quella operativa:

    E[v_i | v_hat_i] = mu_r + ( tau^2 / (tau^2 + sigma_i^2) ) (v_hat_i - mu_r)

con sigma_i^2 = s^2 / Pv_i. Il fattore di restringimento e' maggiore dove la stima e'
piu' rumorosa.

Nota che conta: uno shrinkage UNIFORME non cambia l'argmax, quindi non cambierebbe nulla
nella scelta della rosa. Serve che sia eterogeneo, e lo e' proprio perche' dipende da Pv.

IDENTIFICAZIONE DEI DUE PARAMETRI (metodo dei momenti, niente scelte arbitrarie)

    Fm_t - Fm_{t-1} = (v_t - v_{t-1}) + (eps_t - eps_{t-1}),   Var(eps_t) = s^2 / Pv_t

    E[(Delta Fm)^2] = 2 tau_drift^2 + s^2 (1/Pv_t + 1/Pv_{t-1})

Regredendo (Delta Fm)^2 su (1/Pv_t + 1/Pv_{t-1}): pendenza = s^2, intercetta = 2 tau_drift^2.
tau^2 fra giocatori si ricava poi come varianza totale meno la componente campionaria
media.

LA PREDIZIONE DA TESTARE, fissata prima di girare

Se la teoria si applica, con lo shrinkage devono succedere DUE cose insieme:
  1. il guadagno del knapsack sull'obiettivo somma(v_i) deve SCENDERE dal 35% attuale,
     perche' sfrutta meno rumore;
  2. il guadagno sul risultato realizzato deve SALIRE sopra lo zero attuale (-3 +- 13).
Se succede solo la 1, la teoria non si applica al nostro caso e va abbandonata.

Uso: .venv/bin/python tools/shrinkage.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

SEASONS = ["2015_16", "2016_17", "2017_18", "2018_19", "2019_20", "2020_21",
           "2021_22", "2022_23", "2023_24", "2024_25", "2025_26"]


def read(season: str) -> pd.DataFrame:
    stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
    return stats[["Id", "R", "Pv", "Mv", "Fm"]]


def estimate_variances(min_appearances: int = 5) -> tuple[float, float, dict]:
    """s^2 (varianza per partita) e tau^2 (varianza vera fra giocatori), per ruolo."""
    pairs = []
    for first, second in zip(SEASONS, SEASONS[1:]):
        a, b = read(first).set_index("Id"), read(second).set_index("Id")
        common = a.index.intersection(b.index)
        frame = pd.DataFrame({
            "R": b.loc[common, "R"],
            "fm_0": a.loc[common, "Fm"], "pv_0": a.loc[common, "Pv"],
            "fm_1": b.loc[common, "Fm"], "pv_1": b.loc[common, "Pv"],
        })
        frame = frame[(frame.pv_0 >= min_appearances) & (frame.pv_1 >= min_appearances)]
        pairs.append(frame)
    data = pd.concat(pairs, ignore_index=True)
    data["delta2"] = (data.fm_1 - data.fm_0) ** 2
    data["inv"] = 1 / data.pv_0 + 1 / data.pv_1

    X = np.column_stack([np.ones(len(data)), data.inv.to_numpy()])
    beta, *_ = np.linalg.lstsq(X, data.delta2.to_numpy(), rcond=None)
    intercept, slope = float(beta[0]), float(beta[1])
    s2 = max(1e-6, slope)
    tau2_drift = max(0.0, intercept / 2)

    # tau^2 fra giocatori: varianza totale delle fantamedie meno la componente campionaria.
    role_tau2 = {}
    for role, group in data.groupby("R"):
        total = float(group.fm_1.var(ddof=1))
        sampling = float((s2 / group.pv_1).mean())
        role_tau2[role] = max(1e-6, total - sampling)
    return s2, tau2_drift, role_tau2


def shrink(values: pd.Series, appearances: pd.Series, roles: pd.Series,
           s2: float, role_tau2: dict) -> pd.Series:
    """Media a posteriori: restringe verso la media di ruolo in proporzione al rumore."""
    result = values.copy().astype(float)
    for role in roles.unique():
        mask = roles == role
        if not mask.any():
            continue
        mu = float(values[mask].mean())
        tau2 = role_tau2.get(role, float(values[mask].var(ddof=1)))
        sigma2 = s2 / appearances[mask].clip(lower=1)
        weight = tau2 / (tau2 + sigma2)
        result[mask] = mu + weight * (values[mask] - mu)
    return result


def main() -> None:
    s2, tau2_drift, role_tau2 = estimate_variances()
    print("STIMA DEI PARAMETRI (metodo dei momenti su 10 transizioni di stagione)\n")
    print(f"  s^2  (varianza del punteggio per partita) = {s2:.3f}   -> s = {np.sqrt(s2):.3f}")
    print(f"  tau^2 di deriva anno su anno              = {tau2_drift:.4f}")
    print("\n  tau^2 fra giocatori, per ruolo (varianza vera dei valori):")
    for role, value in sorted(role_tau2.items()):
        print(f"    {role}: {value:.4f}   -> tau = {np.sqrt(value):.3f}")

    print("\nFATTORE DI RESTRINGIMENTO tau^2/(tau^2+s^2/Pv), per presenze e ruolo")
    print("  (1.00 = nessun restringimento, 0.00 = si usa solo la media di ruolo)\n")
    print(f"  {'Pv':>4s} " + " ".join(f"{r:>7s}" for r in sorted(role_tau2)))
    for pv in [5, 10, 15, 20, 25, 30, 35]:
        row = f"  {pv:4d} "
        for role in sorted(role_tau2):
            weight = role_tau2[role] / (role_tau2[role] + s2 / pv)
            row += f" {weight:7.3f}"
        print(row)
    print("\n  La riga a Pv=5 contro quella a Pv=35 e' la ragione per cui la correzione")
    print("  non e' uniforme e quindi cambia davvero l'ordinamento.")


if __name__ == "__main__":
    main()
