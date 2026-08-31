"""Esporta le stagioni storiche nel formato che il worker JS si aspetta.

Serve per il confronto prodotto contro prodotto: finora ho sempre confrontato una mia
riscrittura del metodo della repo, mai il loro codice. Il worker consuma
`auction_data.json` prodotto dalla pipeline, che per le stagioni passate non esiste
(mancano titolari.csv, squadre.csv di quegli anni). Qui lo si ricostruisce dai dati che
ci sono, dando al worker ESATTAMENTE la stessa informazione preseason che ricevono gli
altri metodi: proiezioni dalla media pesata dello storico, e la quotazione iniziale come
ancora di mercato al posto del FVM (che prima del 2022/23 e' zero).

Uso: .venv/bin/python tools/esporta_per_js.py
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np, pandas as pd, warnings
from selezione import build, prepare, DEMAND
from confronto_draft import fit_predict, MODEL_PRESENZE
from confronto_draft import market_price, SLOTS, PARTICIPANTS, CREDITS
warnings.filterwarnings("ignore")

MATCHDAYS = 38
OUT = Path("data/processed/js_backtest")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frame = build()
    pool_all = pd.concat([g.nlargest(DEMAND[r], "prezzo")
                          for (_, r), g in frame.groupby(["stagione", "R"]) for r in [r]],
                         ignore_index=True)
    # Predizione del modello, addestrata SOLO sulle altre stagioni.
    data = prepare(pool_all, "presenze")
    for season in sorted(frame.stagione.unique()):
        pool = pool_all[pool_all.stagione == season].copy().reset_index(drop=True)
        pool["costo"] = market_price(pool)
        stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx",
                              sheet_name="Tutti", header=1).set_index("Id")
        realised_mv = pool.Id.map(stats.Mv).fillna(0.0)
        realised_fm = pool.Id.map(stats.Fm).fillna(0.0)
        # Tassi eventi realizzati per presenza: servono al Monte Carlo della repo, che
        # costruisce il punteggio estraendo da Poisson su questi e NON dal bonus atteso.
        pv_real = pool.Id.map(stats.Pv).fillna(0.0).clip(lower=1)
        rate = lambda col: (pool.Id.map(stats[col]).fillna(0.0) / pv_real).clip(0, 3)
        eventi = {"gol": rate("Gf"), "assist": rate("Ass"), "ammonizioni": rate("Amm"),
                  "espulsioni": rate("Esp"), "autogol": rate("Au"),
                  "gol_subiti": rate("Gs")}

        # Proiezione preseason: disponibilita' dalle presenze dell'anno prima, voto e
        # bonus dalla fantamedia dell'anno prima. Nessuna informazione dalla stagione.
        pv = pool.pv_prec.fillna(pool.groupby("R").pv_prec.transform("median")).fillna(10.0)
        fm = pool.fm_prec.fillna(pool.groupby("R").fm_prec.transform("median")).fillna(5.5)
        mv = pool.mv_prec.fillna(pool.groupby("R").mv_prec.transform("median")).fillna(5.8)
        p_gioca = (pv / MATCHDAYS).clip(0.05, 0.95)
        bonus = (fm - mv).fillna(0.0)

        prediction = fit_predict(data, MODEL_PRESENZE, season).to_numpy()
        # Rimappatura dei ranghi sulla STESSA distribuzione di prezzi del mercato, dentro
        # ogni ruolo: al k-esimo del modello si assegna il k-esimo prezzo di mercato. Cosi'
        # i due metodi hanno identico potere d'acquisto e identica dispersione, e il
        # confronto isola l'ORDINAMENTO. Convertire il rango in prezzo linearmente
        # appiattirebbe la scala e farebbe spargere il budget in modo uniforme.
        modello = np.zeros(len(pool))
        for role in pool.R.unique():
            idx = np.where((pool.R == role).to_numpy())[0]
            prices = np.sort(pool.costo.to_numpy()[idx])[::-1]
            order = idx[np.argsort(-prediction[idx])]
            modello[order] = prices

        players = []
        for i, row in pool.iterrows():
            players.append({
                "id": int(row.Id), "nome": f"g{int(row.Id)}", "ruolo": str(row.R),
                "squadra": str(row.squadra),
                # ancora di mercato: la quotazione riscalata prende il posto del FVM
                "fvm_original": float(row.costo),
                "fvm_scaled": float(row.costo) * 0.75,
                "p_gioca_per_giornata": [round(float(p_gioca[i]), 4)] * MATCHDAYS,
                "voto_puro_mean_per_giornata": [round(float(mv[i]), 3)] * MATCHDAYS,
                "voto_puro_std_per_giornata": [0.8] * MATCHDAYS,
                "bonus_atteso_per_giornata": [round(float(bonus[i]), 3)] * MATCHDAYS,
                "proiezione": {"p_gioca": round(float(p_gioca[i]), 4),
                               "voto_puro": round(float(mv[i]), 3),
                               "bonus": round(float(bonus[i]), 3),
                               "fantavoto": round(float(mv[i] + bonus[i]), 3)},
                # esito realizzato, usato SOLO per il voto finale
                "realizzato": {"pv": float(pool.presenze[i]),
                               "mv": float(realised_mv[i]), "fm": float(realised_fm[i])},
                "event_rates_reali": {k: round(float(v[i]), 4) for k, v in eventi.items()},
                "costo_mercato": int(row.costo),
                "valore_modello": float(round(modello[i], 2)),
            })
        path = OUT / f"{season}.json"
        path.write_text(json.dumps({"stagione": season, "players": players},
                                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {season}: {len(players)} giocatori -> {path}")


if __name__ == "__main__":
    main()
