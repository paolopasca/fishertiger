"""Modello di avversario realistico, dalla descrizione di chi gioca in quella lega.

Tre tipi, come descritti da Paolo:

  PIANIFICATORE   fissa una ripartizione per ruolo (P 5-10%, D 15-25%, C 25-35%, resto
                  agli attaccanti) e la rispetta, sforando di pochissimo. Sono 4-5 su 10.
  CENTROCAMPISTA  come il pianificatore ma carica il centrocampo (40-45%), coerente con
                  chi gioca 4-4-2, 4-5-1 o 3-5-2.
  A SENTIMENTO    nessun piano: offre attorno al prezzo di mercato e finisce i crediti
                  quando capita.

Serve perche' il calo dei prezzi di fine fase misurato prima (fino al 91% di sconto sugli
attaccanti) era gonfiato da avversari che non pianificavano fra le fasi: chi non riserva
budget arriva all'ultima fase senza crediti e i prezzi collassano piu' del dovuto.
La DIREZIONE del calo e' strutturale (viene dalla statistica d'ordine), la DIMENSIONE no.
"""
from __future__ import annotations
import numpy as np

ORDER = ["P", "D", "C", "A"]


def make_opponents(rng, participants: int, planners: int = 5, midfield: int = 2):
    """Restituisce una lista di profili, uno per squadra."""
    profiles = []
    for _ in range(planners):
        p = rng.uniform(5, 10); d = rng.uniform(15, 25); c = rng.uniform(25, 35)
        profiles.append({"tipo": "pianificatore",
                         "split": {"P": p, "D": d, "C": c, "A": 100 - p - d - c},
                         "tolleranza": float(rng.uniform(0.02, 0.08)),
                         "rumore": (0.9, 1.15)})
    for _ in range(midfield):
        p = rng.uniform(5, 8); d = rng.uniform(13, 20); c = rng.uniform(40, 45)
        profiles.append({"tipo": "centrocampista",
                         "split": {"P": p, "D": d, "C": c, "A": 100 - p - d - c},
                         "tolleranza": float(rng.uniform(0.02, 0.08)),
                         "rumore": (0.9, 1.15)})
    while len(profiles) < participants:
        profiles.append({"tipo": "a sentimento", "split": None,
                         "tolleranza": 1.0, "rumore": (0.7, 1.4)})
    rng.shuffle(profiles)
    return profiles


def willingness(profile, market_price, role, credits, spent_by_role, need, slots,
                reserve, min_price, rng):
    """Quanto e' disposto a offrire questa squadra per questo giocatore."""
    open_slots = sum(need.values())
    legal_max = credits - reserve * (open_slots - 1)
    if legal_max < min_price:
        return 0
    base = market_price * rng.uniform(*profile["rumore"])
    if profile["split"] is not None:
        # Budget di ruolo residuo, con la tolleranza di sforamento.
        role_budget = profile["split"][role] / 100 * profile["crediti_iniziali"]
        left = role_budget * (1 + profile["tolleranza"]) - spent_by_role[role]
        left -= max(0, need[role] - 1) * min_price
        base = min(base, max(min_price, left))
    return int(min(legal_max, max(min_price, round(base))))
