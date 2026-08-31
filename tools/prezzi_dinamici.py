"""P1: dentro una fase di ruolo il rapporto prezzo/valore cala al calare della domanda.

DERIVAZIONE (vedi discussione). Nell'asta inglese il prezzo e' fissato dalla q-esima
statistica d'ordine dei valori residui, con q = squadre ancora bisognose del ruolo.
Dentro la fase q e' non crescente e la qualita' del pool e' non crescente: entrambe le
forze spingono il prezzo in giu', quindi prezzo/valore deve calare, e collassare per q->1.

La martingala di Milgrom-Weber prevede invece prezzi costanti in valore atteso: quel
risultato assume domanda costante, che qui e' violata per costruzione.

Il test misura, su aste simulate, il rapporto fra prezzo pagato e valore del giocatore in
funzione di quante squadre cercano ancora quel ruolo.

Uso: .venv/bin/python tools/prezzi_dinamici.py
"""
from __future__ import annotations
import numpy as np, pandas as pd, warnings
from selezione import build, DEMAND
from confronto_draft import market_price, SLOTS, PARTICIPANTS, CREDITS, MIN_PRICE
warnings.filterwarnings("ignore")

RESERVE = 1
ORDER = ["P", "D", "C", "A"]


def auction(pool: pd.DataFrame, rng) -> pd.DataFrame:
    """Asta per ruolo, tutti offrono attorno al prezzo di mercato. Registra ogni scambio
    con la domanda residua al momento dello scambio."""
    credits = [CREDITS] * PARTICIPANTS
    need = [dict(SLOTS) for _ in range(PARTICIPANTS)]
    log = []
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
                want = min(legal_max, max(MIN_PRICE, round(row.costo * rng.uniform(0.8, 1.25))))
                bids.append((want, float(rng.random()), team))
            if not bids:
                continue
            bids.sort(reverse=True)
            price = max(MIN_PRICE, min(bids[0][0], (bids[1][0] + 1) if len(bids) > 1 else MIN_PRICE))
            winner = bids[0][2]
            credits[winner] -= price
            need[winner][role] -= 1
            log.append({"ruolo": role, "domanda_residua": len(buyers),
                        "prezzo": price, "valore_mercato": row.costo,
                        "rapporto": price / max(1.0, row.costo)})
    return pd.DataFrame(log)


def main() -> None:
    frame = build()
    pool_all = pd.concat([g.nlargest(DEMAND[r], "prezzo")
                          for (_, r), g in frame.groupby(["stagione", "R"]) for r in [r]],
                         ignore_index=True)
    logs = []
    for season in sorted(frame.stagione.unique()):
        pool = pool_all[pool_all.stagione == season].copy().reset_index(drop=True)
        pool["costo"] = market_price(pool)
        for repetition in range(15):
            rng = np.random.default_rng(abs(hash((season, repetition))) % (2 ** 32))
            log = auction(pool, rng)
            log["stagione"] = season
            logs.append(log)
    data = pd.concat(logs, ignore_index=True)

    print("P1: RAPPORTO PREZZO / VALORE DI MERCATO, per domanda residua\n")
    print(f"  {'squadre che cercano il ruolo':30s} {'n scambi':>9s} {'prezzo/valore':>14s}")
    summary = data.groupby("domanda_residua").agg(n=("rapporto", "size"),
                                                  rapporto=("rapporto", "mean"))
    for demand, row in summary.sort_index(ascending=False).iterrows():
        bar = "#" * int(row.rapporto * 40)
        print(f"  {demand:30d} {int(row.n):9d} {row.rapporto:14.3f}  {bar}")

    # Test formale: il rapporto e' crescente nella domanda residua?
    d = data[data.domanda_residua > 0]
    X = np.column_stack([np.ones(len(d)), d.domanda_residua.to_numpy()])
    y = d.rapporto.to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    cov = (resid @ resid / (len(d) - 2)) * np.linalg.inv(X.T @ X)
    t = beta[1] / np.sqrt(cov[1, 1])
    print(f"\n  pendenza su domanda residua: {beta[1]:+.4f}  t = {t:.1f}")
    print(f"  esito: {'P1 CONFERMATA' if beta[1] > 0 and t > 2 else 'P1 NON CONFERMATA'}"
          " (prezzo/valore cala al calare della domanda)")

    print("\n  per ruolo:")
    for role in ORDER:
        g = data[data.ruolo == role]
        top = g[g.domanda_residua >= PARTICIPANTS - 1].rapporto.mean()
        bottom = g[g.domanda_residua <= 2].rapporto.mean()
        print(f"    {role}: con domanda piena {top:.3f}, a fine fase {bottom:.3f}  "
              f"-> sconto {(1 - bottom / top) * 100:.0f}%")
    data.to_csv("data/processed/prezzi_dinamici.csv", index=False)


if __name__ == "__main__":
    main()
