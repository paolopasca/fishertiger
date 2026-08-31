"""Inferenza fatta come si deve: test di Wald, errori robusti e diagnostica.

Tre cose che servono e che finora mancavano.

1. TEST DI WALD (o F per modelli annidati). Guardare i t uno a uno risponde a "questa
   variabile serve?", non a "questo GRUPPO di variabili serve?". Con dieci variabili
   inutili, una avra' |t| > 2 per caso circa una volta su venti. Il test di Wald misura
   il gruppo insieme:

       W = (R b - r)' [R V R']^-1 (R b - r)

   dove R seleziona i coefficienti da testare. Sotto l'ipotesi che siano tutti zero, W si
   distribuisce come un chi-quadro con tanti gradi di liberta' quante le restrizioni. Per
   modelli annidati la versione equivalente e' l'F, che si calcola dai due R2:

       F = [(R2_grande - R2_piccolo) / q] / [(1 - R2_grande) / (n - k - 1)]

2. ERRORI STANDARD RAGGRUPPATI PER STAGIONE. Le osservazioni sono giocatori dentro
   stagioni, e dentro una stagione gli errori sono correlati: un anno con molti infortuni
   sposta tutti insieme. La formula classica assume errori indipendenti e quindi
   sottostima l'incertezza, gonfiando i t. Con G gruppi si usa

       V = (X'X)^-1 [somma_g X_g' u_g u_g' X_g] (X'X)^-1

   che non assume indipendenza dentro il gruppo. Con sole 8 stagioni i gruppi sono pochi
   e la correzione e' rozza, ma e' comunque piu' onesta della versione classica.

3. VIF, per la multicollinearita'. Se una variabile e' quasi combinazione lineare delle
   altre, il suo coefficiente diventa instabile: il segno puo' ribaltarsi cambiando poco
   i dati. VIF_j = 1 / (1 - R2_j), con R2_j della regressione di quella variabile sulle
   altre. Sopra 5 il coefficiente non e' interpretabile da solo.

Uso: .venv/bin/python tools/inferenza.py [presenze|punti]
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import warnings
from scipy import stats as scipy_stats

from selezione import build, prepare, FEATURES, DEMAND

warnings.filterwarnings("ignore")


def ols(X: np.ndarray, y: np.ndarray):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return beta, resid


def classic_cov(X: np.ndarray, resid: np.ndarray) -> np.ndarray:
    dof = len(y_global) - X.shape[1]
    return (resid @ resid / dof) * np.linalg.inv(X.T @ X)


def cluster_cov(X: np.ndarray, resid: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Sandwich raggruppato: non assume indipendenza dentro la stagione."""
    xtx_inv = np.linalg.inv(X.T @ X)
    meat = np.zeros((X.shape[1], X.shape[1]))
    unique = np.unique(groups)
    for g in unique:
        mask = groups == g
        Xg, ug = X[mask], resid[mask]
        score = Xg.T @ ug
        meat += np.outer(score, score)
    n, k, G = len(resid), X.shape[1], len(unique)
    correction = (G / max(1, G - 1)) * ((n - 1) / max(1, n - k))
    return correction * xtx_inv @ meat @ xtx_inv


def wald(beta, cov, indices, n_groups):
    """Ipotesi: i coefficienti indicati sono tutti zero contemporaneamente.

    Due vincoli teorici, da verificare PRIMA di calcolare qualcosa.

    Rango. La covarianza raggruppata e' una somma di G prodotti esterni di rango 1,
    quindi ha rango al piu' G. Per invertire R V R' (q x q) serve rango almeno q: con
    q > G-1 il test non e' identificato e il solve restituisce spazzatura, non un
    risultato conservativo. Va rifiutato prima, non interpretato dopo.

    Distribuzione di riferimento. Il chi-quadro vale asintoticamente nel numero di
    GRUPPI, non di osservazioni. Con pochi gruppi la referenza corretta e' una F con
    (q, G-q) gradi di liberta', che e' sensibilmente piu' conservativa.
    """
    q = len(indices)
    if q > n_groups - 1:
        return float("nan"), q, float("nan"), "non identificato: q > G-1"
    R = np.zeros((len(indices), len(beta)))
    for row, column in enumerate(indices):
        R[row, column] = 1.0
    middle = R @ cov @ R.T
    if np.linalg.matrix_rank(middle) < q:
        return float("nan"), q, float("nan"), "matrice singolare"
    difference = R @ beta
    statistic = float(difference @ np.linalg.solve(middle, difference))
    dof2 = n_groups - q
    f_stat = statistic / q
    p = float(1 - scipy_stats.f.cdf(f_stat, q, dof2)) if dof2 > 0 else float("nan")
    return f_stat, q, p, ""


def vif(data: pd.DataFrame, columns: list[str]) -> dict[str, float]:
    result = {}
    for column in columns:
        others = [c for c in columns if c != column]
        X = np.column_stack([np.ones(len(data))] + [data[c].to_numpy() for c in others])
        y = data[column].to_numpy()
        _, resid = ols(X, y)
        r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
        result[column] = 1 / max(1e-9, 1 - r2)
    return result


def r2_of(data: pd.DataFrame, columns: list[str]) -> tuple[float, np.ndarray, np.ndarray]:
    X = np.column_stack([np.ones(len(data))] + [data[c].to_numpy() for c in columns])
    y = data.y.to_numpy()
    beta, resid = ols(X, y)
    r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
    return r2, beta, resid


def main() -> None:
    global y_global
    target = sys.argv[1] if len(sys.argv) > 1 else "punti"
    frame = build()
    drafted = pd.concat([
        g.nlargest(DEMAND[role], "prezzo")
        for (_, role), g in frame.groupby(["stagione", "R"]) for role in [role]
    ], ignore_index=True)
    data = prepare(drafted, target)
    y_global = data.y.to_numpy()
    groups = data.stagione.to_numpy()

    candidates = ["pv_prec", "punti_prec", "mv_prec", "fm_prec", "gol90_prec",
                  "cambio_squadra", "revisione_mercato", "concorrenza_ruolo",
                  "forza_squadra", "peso_in_squadra", "neopromossa", "esperienza"]
    columns = ["prezzo"] + candidates

    r2_full, beta, resid = r2_of(data, columns)
    X = np.column_stack([np.ones(len(data))] + [data[c].to_numpy() for c in columns])
    cov_classic = (resid @ resid / (len(data) - X.shape[1])) * np.linalg.inv(X.T @ X)
    cov_cluster = cluster_cov(X, resid, groups)
    se_classic = np.sqrt(np.diag(cov_classic))
    se_cluster = np.sqrt(np.diag(cov_cluster))

    print(f"MODELLO COMPLETO, bersaglio {target.upper()}, n = {len(data)}, "
          f"{len(np.unique(groups))} stagioni")
    print(f"R2 dentro campione = {r2_full:.4f}\n")
    print(f"{'variabile':20s} {'coeff':>8s} {'t classico':>11s} {'t raggruppato':>14s} {'VIF':>7s}")
    vifs = vif(data, columns)
    for i, name in enumerate(columns, start=1):
        t_classic = beta[i] / se_classic[i]
        t_cluster = beta[i] / se_cluster[i]
        print(f"{name:20s} {beta[i]:8.3f} {t_classic:11.2f} {t_cluster:14.2f} {vifs[name]:7.2f}")

    print("\n  Il t raggruppato e' quello da usare. Dove i due divergono molto, la stima")
    print("  classica stava sottostimando l'incertezza.\n")

    print("TEST DI WALD SU GRUPPI DI VARIABILI (ipotesi: sono tutte zero insieme)")
    print("  errori raggruppati per stagione\n")
    index_of = {name: i for i, name in enumerate(columns, start=1)}
    gruppi = {
        "tutte tranne il prezzo": candidates,
        "storico rendimento (pv, punti, mv, fm, gol90)":
            ["pv_prec", "punti_prec", "mv_prec", "fm_prec", "gol90_prec"],
        "contesto squadra (concorrenza, forza, peso, neopromossa)":
            ["concorrenza_ruolo", "forza_squadra", "peso_in_squadra", "neopromossa"],
        "cambio squadra da solo": ["cambio_squadra"],
        "revisione del mercato da sola": ["revisione_mercato"],
        "le scartate dalla selezione (gol90, fm, esperienza, neopromossa)":
            ["gol90_prec", "fm_prec", "esperienza", "neopromossa"],
    }
    n_groups = len(np.unique(groups))
    print(f"  {len(np.unique(groups))} stagioni = {n_groups} gruppi, quindi al massimo "
          f"{n_groups - 1} restrizioni testabili insieme\n")
    print(f"  {'gruppo':58s} {'F':>8s} {'q':>3s} {'p':>8s}   esito")
    for name, members in gruppi.items():
        indices = [index_of[m] for m in members if m in index_of]
        f_stat, q, p, problem = wald(beta, cov_cluster, indices, n_groups)
        if problem:
            print(f"  {name:58s} {'--':>8s} {q:3d} {'--':>8s}   {problem}")
            continue
        verdict = "SERVE" if p < 0.05 else "non distinguibile da zero"
        print(f"  {name:58s} {f_stat:8.2f} {q:3d} {p:8.4f}   {verdict}")

    print("\nTEST F SU MODELLI ANNIDATI (aggiungere il gruppo migliora l'adattamento?)")
    small = ["prezzo"]
    for extra in (["pv_prec"], ["pv_prec", "cambio_squadra"],
                  ["pv_prec", "cambio_squadra", "forza_squadra"],
                  ["pv_prec", "cambio_squadra", "forza_squadra", "concorrenza_ruolo"]):
        big = small + extra
        r2_small, _, _ = r2_of(data, small)
        r2_big, _, _ = r2_of(data, big)
        q = len(extra)
        n, k = len(data), len(big)
        f = ((r2_big - r2_small) / q) / ((1 - r2_big) / (n - k - 1))
        p = 1 - scipy_stats.f.cdf(f, q, n - k - 1)
        print(f"  prezzo + {', '.join(extra):48s} R2 {r2_big:.4f}  F {f:8.2f}  p {p:.2e}")


if __name__ == "__main__":
    main()
