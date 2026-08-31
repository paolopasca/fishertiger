"""P1 rimisurata contro avversari realistici (tools/avversari.py)."""
from __future__ import annotations
import numpy as np, pandas as pd, warnings
from selezione import build, DEMAND
from confronto_draft import market_price, SLOTS, PARTICIPANTS, CREDITS, MIN_PRICE
from avversari import make_opponents, willingness, ORDER
warnings.filterwarnings("ignore")
RESERVE = 1

def auction(pool, rng):
    profiles = make_opponents(rng, PARTICIPANTS)
    for p in profiles:
        p["crediti_iniziali"] = CREDITS
    credits = [CREDITS] * PARTICIPANTS
    spent = [{r: 0.0 for r in SLOTS} for _ in range(PARTICIPANTS)]
    need = [dict(SLOTS) for _ in range(PARTICIPANTS)]
    log = []
    for role in ORDER:
        for _, row in pool[pool.R == role].sort_values("costo", ascending=False).iterrows():
            buyers = [t for t in range(PARTICIPANTS) if need[t][role] > 0]
            if not buyers:
                break
            bids = []
            for t in buyers:
                want = willingness(profiles[t], row.costo, role, credits[t], spent[t],
                                   need[t], SLOTS, RESERVE, MIN_PRICE, rng)
                if want >= MIN_PRICE:
                    bids.append((want, float(rng.random()), t))
            if not bids:
                continue
            bids.sort(reverse=True)
            price = max(MIN_PRICE, min(bids[0][0], (bids[1][0] + 1) if len(bids) > 1 else MIN_PRICE))
            w = bids[0][2]
            credits[w] -= price; spent[w][role] += price; need[w][role] -= 1
            log.append({"ruolo": role, "domanda_residua": len(buyers), "prezzo": price,
                        "valore_mercato": row.costo, "rapporto": price / max(1.0, row.costo),
                        "tipo_vincitore": profiles[w]["tipo"]})
    return pd.DataFrame(log), profiles, credits

def main():
    frame = build()
    pool_all = pd.concat([g.nlargest(DEMAND[r], "prezzo")
                          for (_, r), g in frame.groupby(["stagione", "R"]) for r in [r]],
                         ignore_index=True)
    logs = []
    for season in sorted(frame.stagione.unique()):
        pool = pool_all[pool_all.stagione == season].copy().reset_index(drop=True)
        pool["costo"] = market_price(pool)
        for rep in range(15):
            rng = np.random.default_rng(abs(hash((season, rep))) % (2**32))
            log, _, _ = auction(pool, rng)
            logs.append(log)
    data = pd.concat(logs, ignore_index=True)
    print("P1 CON AVVERSARI REALISTICI (5 pianificatori, 2 centrocampisti, 3 a sentimento)\n")
    print(f"  {'domanda residua':>16s} {'n':>7s} {'prezzo/valore':>14s}")
    s = data.groupby("domanda_residua").agg(n=("rapporto","size"), r=("rapporto","mean"))
    for d, row in s.sort_index(ascending=False).iterrows():
        print(f"  {d:16d} {int(row.n):7d} {row.r:14.3f}  " + "#"*int(row.r*40))
    d = data[data.domanda_residua > 0]
    X = np.column_stack([np.ones(len(d)), d.domanda_residua.to_numpy()]); y = d.rapporto.to_numpy()
    b, *_ = np.linalg.lstsq(X, y, rcond=None); res = y - X@b
    cov = (res@res/(len(d)-2))*np.linalg.inv(X.T@X); t = b[1]/np.sqrt(cov[1,1])
    print(f"\n  pendenza {b[1]:+.4f}  t = {t:.1f}   {'P1 CONFERMATA' if b[1]>0 and t>2 else 'P1 NON CONFERMATA'}")
    print("\n  sconto fra inizio e fine fase, per ruolo:")
    for role in ORDER:
        g = data[data.ruolo == role]
        top = g[g.domanda_residua >= PARTICIPANTS-1].rapporto.mean()
        bot = g[g.domanda_residua <= 2].rapporto.mean()
        print(f"    {role}: {top:.3f} -> {bot:.3f}   sconto {(1-bot/top)*100:5.0f}%")
    print("\n  chi vince i giocatori, per tipo:")
    print(data.groupby("tipo_vincitore").agg(n=("prezzo","size"), prezzo_medio=("prezzo","mean"),
          rapporto=("rapporto","mean")).round(2).to_string())
    data.to_csv("data/processed/p1_realistico.csv", index=False)

if __name__ == "__main__":
    main()
