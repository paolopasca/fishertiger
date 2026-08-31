"""Quale ripartizione del budget per ruolo massimizza i punti, contro avversari veri.

Da P1: chi pianifica si ferma di netto al budget di reparto, quindi arrivare a una fase
con crediti quando gli altri sono a secco vale molto. Da P2: i crediti avanzati valgono
zero, quindi la ripartizione deve sommare a 100 e spendersi tutta.

Restano da confrontare i profili di spesa. Gli avversari sono quelli descritti da Paolo:
5 pianificatori (P 5-10, D 15-25, C 25-35, resto), 2 che caricano il centrocampo (40-45),
2 a sentimento.
"""
from __future__ import annotations
import numpy as np, pandas as pd, warnings
from selezione import build, DEMAND
from confronto_draft import (market_price, season_points, SLOTS, PARTICIPANTS,
                             CREDITS, MIN_PRICE)
from avversari import make_opponents, willingness, ORDER
warnings.filterwarnings("ignore")
RESERVE = 1

SPLITS = {
    "repo cablata 7/18/25/50":    {"P": 7,  "D": 18, "C": 25, "A": 50},
    "mercato 7/19/35/39":         {"P": 7,  "D": 19, "C": 35, "A": 39},
    "pianificatore tipo 7/20/30/43": {"P": 7, "D": 20, "C": 30, "A": 43},
    "difesa 10/30/30/30":         {"P": 10, "D": 30, "C": 30, "A": 30},
    "attacco 5/15/25/55":         {"P": 5,  "D": 15, "C": 25, "A": 55},
    "centrocampo 6/17/42/35":     {"P": 6,  "D": 17, "C": 42, "A": 35},
    "equilibrata 8/25/32/35":     {"P": 8,  "D": 25, "C": 32, "A": 35},
}

def auction(pool, rng, my_split):
    profiles = make_opponents(rng, PARTICIPANTS - 1)
    mine = {"tipo": "noi", "split": my_split, "tolleranza": 0.05, "rumore": (0.95, 1.10)}
    profiles = [mine] + profiles
    for p in profiles:
        p["crediti_iniziali"] = CREDITS
    credits = [CREDITS] * PARTICIPANTS
    spent = [{r: 0.0 for r in SLOTS} for _ in range(PARTICIPANTS)]
    need = [dict(SLOTS) for _ in range(PARTICIPANTS)]
    picked = []
    for role in ORDER:
        for position, row in pool[pool.R == role].sort_values("costo", ascending=False).iterrows():
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
            if w == 0:
                picked.append(position)
    if sum(need[0].values()) > 0:
        return None, None
    return pool.loc[picked], CREDITS - credits[0]

def main():
    frame = build()
    realised = {}
    for season in frame.stagione.unique():
        stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
        realised[season] = stats.set_index("Id")[["Mv", "Fm"]]
    pool_all = pd.concat([g.nlargest(DEMAND[r], "prezzo")
                          for (_, r), g in frame.groupby(["stagione", "R"]) for r in [r]],
                         ignore_index=True)
    rows = []
    for season in sorted(frame.stagione.unique()):
        pool = pool_all[pool_all.stagione == season].copy().reset_index(drop=True)
        pool["costo"] = market_price(pool)
        pool["mv_realizzata"] = pool.Id.map(realised[season].Mv).fillna(0.0)
        pool["fm_realizzata"] = pool.Id.map(realised[season].Fm).fillna(0.0)
        for rep in range(10):
            for name, split in SPLITS.items():
                rng = np.random.default_rng(abs(hash((season, rep))) % (2**32))
                roster, spent = auction(pool, rng, split)
                if roster is None or len(roster) != sum(SLOTS.values()):
                    continue
                rows.append({"stagione": season, "ripetizione": rep, "ripartizione": name,
                             "punti": season_points(roster, abs(hash((season, rep))) % (2**30)),
                             "spesa": spent, "presenze_medie": float(roster.presenze.mean())})
    table = pd.DataFrame(rows)
    s = table.groupby("ripartizione").agg(punti=("punti","mean"), spesa=("spesa","mean"),
                                          presenze=("presenze_medie","mean"), aste=("punti","size"))
    print("PUNTI STAGIONE PER RIPARTIZIONE DEL BUDGET\n")
    print(s.sort_values("punti", ascending=False).round(1).to_string())
    wide = table.pivot_table(index=["stagione","ripetizione"], columns="ripartizione", values="punti")
    base = "repo cablata 7/18/25/50"
    print(f"\nCONFRONTI APPAIATI contro '{base}' (medie per stagione, n=8)")
    for name in s.sort_values("punti", ascending=False).index:
        if name == base or name not in wide: continue
        d = (wide[name] - wide[base]).groupby("stagione").mean()
        se = d.std(ddof=1)/np.sqrt(len(d)); t = d.mean()/se if se>0 else 0
        print(f"  {name:32s} {d.mean():+8.1f} +- {se:5.1f}  t = {t:5.2f}  "
              f"{'REALE' if abs(t)>2 else ''}")
    table.to_csv("data/processed/p4_ripartizione.csv", index=False)

if __name__ == "__main__":
    main()
