"""P2: esiste un profilo di attesa che domina quello ingenuo?

TEORIA. Da P1 il rapporto prezzo/valore cala dentro la fase (t = 201). Il problema di
arresto ottimo e'

    W(B, m, S, q) = max { v_i - p_i + W(B-p_i, m-1, S\\i, q'),  W(B, m, S\\i, q'') }

e la regola ottima e' di soglia. Qui si parametrizza la soglia con la PAZIENZA theta:
si compra solo se il prezzo richiesto e' al piu' theta volte il valore di mercato del
giocatore, con una rete di sicurezza che obbliga a comprare quando gli slot residui
eguagliano i candidati residui accettabili (altrimenti la rosa non si completa).

PREDIZIONE, fissata prima di girare: esiste un ottimo interno. theta molto basso lascia
senza qualita' (si aspetta troppo e restano solo scarti), theta molto alto fa pagare la
concorrenza di inizio fase. Se il massimo cade a un estremo, la teoria dell'arresto non
sta descrivendo il fenomeno.
"""
from __future__ import annotations
import numpy as np, pandas as pd, warnings
from selezione import build, DEMAND
from confronto_draft import (market_price, season_points, SLOTS, PARTICIPANTS,
                             CREDITS, MIN_PRICE)
from avversari import make_opponents, willingness, ORDER
warnings.filterwarnings("ignore")
RESERVE = 1

def auction(pool, rng, theta, realised):
    """La squadra 0 usa la soglia di pazienza theta, le altre sono avversari realistici."""
    profiles = make_opponents(rng, PARTICIPANTS - 1)
    for p in profiles:
        p["crediti_iniziali"] = CREDITS
    profiles = [None] + profiles                       # posto 0 = noi
    credits = [CREDITS] * PARTICIPANTS
    spent = [{r: 0.0 for r in SLOTS} for _ in range(PARTICIPANTS)]
    need = [dict(SLOTS) for _ in range(PARTICIPANTS)]
    mine = []
    for role in ORDER:
        candidates = pool[pool.R == role].sort_values("costo", ascending=False)
        remaining = len(candidates)
        for position, row in candidates.iterrows():
            remaining -= 1
            buyers = [t for t in range(PARTICIPANTS) if need[t][role] > 0]
            if not buyers:
                break
            bids = []
            for t in buyers:
                if t == 0:
                    open_slots = sum(need[0].values())
                    legal = credits[0] - RESERVE * (open_slots - 1)
                    if legal < MIN_PRICE:
                        continue
                    # Rete di sicurezza: se i candidati che restano non bastano a
                    # riempire gli slot, si compra comunque.
                    forced = remaining <= need[0][role]
                    cap = legal if forced else min(legal, max(MIN_PRICE, round(theta * row.costo)))
                    bids.append((int(cap), float(rng.random()), 0))
                else:
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
                mine.append(position)
    if sum(need[0].values()) > 0:
        return None, None
    roster = pool.loc[mine]
    return roster, CREDITS - credits[0]

def main():
    frame = build()
    realised = {}
    for season in frame.stagione.unique():
        stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
        realised[season] = stats.set_index("Id")[["Mv", "Fm"]]
    pool_all = pd.concat([g.nlargest(DEMAND[r], "prezzo")
                          for (_, r), g in frame.groupby(["stagione", "R"]) for r in [r]],
                         ignore_index=True)
    thetas = [0.30, 0.50, 0.70, 0.85, 1.00, 1.20, 1.50]
    rows = []
    for season in sorted(frame.stagione.unique()):
        pool = pool_all[pool_all.stagione == season].copy().reset_index(drop=True)
        pool["costo"] = market_price(pool)
        pool["mv_realizzata"] = pool.Id.map(realised[season].Mv).fillna(0.0)
        pool["fm_realizzata"] = pool.Id.map(realised[season].Fm).fillna(0.0)
        for rep in range(6):
            for theta in thetas:
                rng = np.random.default_rng(abs(hash((season, rep))) % (2**32))
                roster, spent = auction(pool, rng, theta, realised)
                if roster is None or len(roster) != sum(SLOTS.values()):
                    continue
                rows.append({"stagione": season, "ripetizione": rep, "theta": theta,
                             "punti": season_points(roster, abs(hash((season, rep))) % (2**30)),
                             "spesa": spent, "presenze_medie": float(roster.presenze.mean()),
                             "valore_acquistato": float(roster.costo.sum())})
    table = pd.DataFrame(rows)
    if table.empty:
        print("nessuna asta completata"); return
    print("P2: PAZIENZA (compra solo se prezzo <= theta x valore di mercato)\n")
    s = table.groupby("theta").agg(punti=("punti","mean"), spesa=("spesa","mean"),
                                   valore=("valore_acquistato","mean"),
                                   presenze=("presenze_medie","mean"),
                                   aste=("punti","size"))
    s["valore_per_credito"] = s.valore / s.spesa
    print(s.round(2).to_string())
    best = s.punti.idxmax()
    interior = best not in (min(thetas), max(thetas))
    print(f"\n  massimo a theta = {best}  ->  "
          f"{'ottimo INTERNO, coerente con la teoria dell arresto' if interior else 'ottimo a un ESTREMO: la teoria non descrive il fenomeno'}")
    print("\n  confronti appaiati contro theta = 1.20 (comportamento tipico)")
    wide = table.pivot_table(index=["stagione","ripetizione"], columns="theta", values="punti")
    if 1.20 in wide:
        for th in thetas:
            if th == 1.20 or th not in wide: continue
            d = (wide[th] - wide[1.20]).groupby("stagione").mean()
            se = d.std(ddof=1)/np.sqrt(len(d)); t = d.mean()/se if se>0 else 0
            print(f"    theta {th:4.2f}: {d.mean():+8.1f} +- {se:5.1f}  t = {t:5.2f}  "
                  f"{'REALE' if abs(t)>2 else ''}")
    table.to_csv("data/processed/p2_pazienza.csv", index=False)

if __name__ == "__main__":
    main()
