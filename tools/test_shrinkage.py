"""Test della predizione fissata in tools/shrinkage.py.

Con lo shrinkage devono succedere DUE cose insieme:
  1. il guadagno del knapsack sull'obiettivo somma(v_i) SCENDE (sfrutta meno rumore);
  2. il guadagno sul risultato realizzato SALE sopra lo zero attuale (-3 +- 13).
Se succede solo la 1, la teoria non si applica e va abbandonata.
"""
from __future__ import annotations
import numpy as np, pandas as pd, warnings
import knapsack as K
from selezione import build, prepare, DEMAND
from confronto_draft import (market_price, fit_predict, draft, season_points,
                             SLOTS, PARTICIPANTS, CREDITS, SPLIT_MERCATO, MODEL_PRESENZE)
from shrinkage import estimate_variances, shrink
warnings.filterwarnings("ignore")

def main() -> None:
    s2, _, role_tau2 = estimate_variances()
    frame = build()
    realised = {}
    for season in frame.stagione.unique():
        stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
        realised[season] = stats.set_index("Id")[["Mv", "Fm"]]

    pool_all = pd.concat([g.nlargest(DEMAND[r], "prezzo")
                          for (_, r), g in frame.groupby(["stagione", "R"]) for r in [r]],
                         ignore_index=True)

    # L'eterogeneita' che conta non e' nella fantamedia: il modello per le presenze non
    # la usa. Sta in QUANTA informazione abbiamo su ciascun giocatore. Circa il 40% dei
    # sorteggiabili non ha la stagione precedente (neopromossi, acquisti dall'estero,
    # giovani): per loro pv_prec e' imputato e la predizione e' molto piu' incerta.
    #
    # Var(pv_prec) come stima della disponibilita' vera: pv = 38 p_hat con p_hat media di
    # 38 prove di Bernoulli, quindi Var(pv) = 38 p (1-p). Chi non ha storico ha varianza
    # pari all'intera varianza fra giocatori, cioe' fattore di restringimento zero: la
    # sua unica informazione e' la media di ruolo.
    shrunk = pool_all.copy()
    observed = pool_all.pv_prec.notna()
    p_hat = (pool_all.pv_prec / 38).clip(0.01, 0.99)
    sigma2_pv = 38 * p_hat * (1 - p_hat)
    values = pool_all.pv_prec.copy()
    for role in pool_all.R.unique():
        mask = pool_all.R == role
        known = mask & observed
        if not known.any():
            continue
        mu = float(pool_all.loc[known, "pv_prec"].mean())
        tau2 = float(pool_all.loc[known, "pv_prec"].var(ddof=1)) - float(sigma2_pv[known].mean())
        tau2 = max(1e-6, tau2)
        weight = tau2 / (tau2 + sigma2_pv[mask])
        values[mask & observed] = mu + weight[observed[mask]] * (pool_all.loc[known, "pv_prec"] - mu)
        values[mask & ~observed] = mu          # nessuna informazione: solo la media di ruolo
    shrunk["pv_prec"] = values

    rows, objective = [], []
    for label, source in (("grezzo", pool_all), ("ristretto", shrunk)):
        data = prepare(source, "presenze")
        for season in sorted(frame.stagione.unique()):
            pool = source[source.stagione == season].copy().reset_index(drop=True)
            pool["costo"] = market_price(pool)
            pool["mv_realizzata"] = pool.Id.map(realised[season].Mv).fillna(0.0)
            pool["fm_realizzata"] = pool.Id.map(realised[season].Fm).fillna(0.0)
            values = fit_predict(data, MODEL_PRESENZE, season).to_numpy()
            costs = pool.costo.to_numpy()
            seed = abs(hash(season)) % (2 ** 32)

            greedy = draft(pool, pd.Series(values, index=pool.index), SPLIT_MERCATO)
            picks = K.solve(pool, values, costs, SLOTS, CREDITS)
            optimal = pool.iloc[picks]
            g_obj = float(values[greedy.index.to_numpy()].sum()) if len(greedy) else np.nan
            k_obj = float(values[picks].sum())
            objective.append({"versione": label, "stagione": season,
                              "guadagno_obiettivo": (k_obj - g_obj) / abs(g_obj)})
            for allocator, roster in (("greedy", greedy), ("knapsack", optimal)):
                if roster.empty or len(roster) != sum(SLOTS.values()):
                    continue
                rows.append({"versione": label, "stagione": season, "allocatore": allocator,
                             "punti": season_points(roster, seed)})

    obj = pd.DataFrame(objective).groupby("versione").guadagno_obiettivo.mean()
    table = pd.DataFrame(rows)
    wide = table.pivot_table(index=["versione", "stagione"], columns="allocatore", values="punti")
    print("PREDIZIONE 1: il guadagno del knapsack sull'obiettivo deve SCENDERE")
    for version in ["grezzo", "ristretto"]:
        print(f"  {version:10s} {obj[version] * 100:+6.1f}%")
    print(f"  esito: {'CONFERMATA' if obj['ristretto'] < obj['grezzo'] else 'SMENTITA'}\n")

    print("PREDIZIONE 2: il guadagno sul risultato realizzato deve SALIRE sopra zero")
    for version in ["grezzo", "ristretto"]:
        d = (wide.loc[version, "knapsack"] - wide.loc[version, "greedy"]).dropna()
        se = d.std(ddof=1) / np.sqrt(len(d))
        print(f"  {version:10s} {d.mean():+7.1f} +- {se:5.1f}  t = {d.mean()/se if se>0 else 0:5.2f}")

    print("\nEFFETTO DELLO SHRINKAGE SUL RISULTATO, a allocatore fisso")
    for allocator in ["greedy", "knapsack"]:
        d = (wide.loc["ristretto", allocator] - wide.loc["grezzo", allocator]).dropna()
        se = d.std(ddof=1) / np.sqrt(len(d))
        t = d.mean() / se if se > 0 else 0
        print(f"  {allocator:10s} ristretto - grezzo: {d.mean():+7.1f} +- {se:5.1f}  t = {t:5.2f}  "
              f"{'REALE' if abs(t) > 2 else 'non distinguibile'}")
    table.to_csv("data/processed/test_shrinkage.csv", index=False)

if __name__ == "__main__":
    main()
