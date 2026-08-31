"""Allocazione ottima della rosa: knapsack multi-scelta esatto, e il suo duale.

TEORIA

Il problema di scelta della rosa e'

    max   somma_i v_i x_i
    s.t.  somma_i p_i x_i <= B                      (budget)
          somma_{i in ruolo r} x_i = k_r   per ogni r
          x_i in {0,1}

cioe' un knapsack con vincoli di cardinalita' per classe. Non e' bin packing: li' si
minimizza il numero di contenitori, qui si massimizza il valore dentro un contenitore
solo. Si risolve esattamente in programmazione dinamica: per ogni ruolo si calcola la
frontiera valore-massimo(conteggio, budget), poi si convolvono i ruoli sul budget. Il
costo e' O(somma_r k_r n_r B + R B^2), che con B=500 e n=250 e' immediato.

IL DUALE, da cui viene il tetto d'offerta

Rilassando x_i in [0,1], la lagrangiana e'

    L = somma_i v_i x_i - lambda (somma_i p_i x_i - B) - somma_r mu_r (somma_{i in r} x_i - k_r)

e la stazionarieta' da', per ogni giocatore comprato,

    v_i - lambda p_i - mu_r = 0    ->    p_i* = (v_i - mu_r) / lambda

lambda e' il valore marginale di un credito, mu_r quello di uno slot nel ruolo r. Il
prezzo massimo razionale per il giocatore i e' quindi (v_i - mu_r) / lambda.

IL RIMPIAZZO RAGGIUNGIBILE

mu_r non e' il valore del giocatore al cutoff della domanda di lega. Con P avversari che
pescano dallo stesso pool, il rimpiazzo che TI RESTA per il tuo slot j non e' il j-esimo
del pool ma circa il ((j-1)P + P/2)-esimo: gli altri prendono la loro parte. Usare il
cutoff come benchmark rende il baseline irraggiungibile e schiaccia il prezzo di
indifferenza verso il basso, fino a dire di non comprare nessuno.

    mu_r(j) = v( rango_pool = (j-1) P + P/2 )
    b*_i    = ( v_i - mu_r(j_i) ) / lambda

con j_i la posizione che il candidato occuperebbe nella tua rosa, stimata come
floor(migliori_di_lui_nel_pool / P).

VERIFICA ATTESA: la somma dei prezzi cosi' ottenuti sui 250 sorteggiati deve eguagliare
i crediti della lega. E' una condizione di equilibrio, quindi un'identita' controllabile.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EMPTY = -1e15


def role_frontier(values: np.ndarray, costs: np.ndarray, count: int, budget: int):
    """best[c][b] = valore massimo scegliendo esattamente c giocatori con spesa <= b.

    I cicli sul budget vanno in ordine decrescente: cosi' ogni giocatore entra al piu'
    una volta (altrimenti si otterrebbe il knapsack con ripetizione).
    """
    best = np.full((count + 1, budget + 1), EMPTY)
    best[0, :] = 0.0
    taken = [[[] for _ in range(budget + 1)] for _ in range(count + 1)]
    for b in range(budget + 1):
        taken[0][b] = []
    for index in range(len(values)):
        cost = int(costs[index])
        if cost > budget:
            continue
        value = values[index]
        for c in range(count, 0, -1):
            for b in range(budget, cost - 1, -1):
                if best[c - 1, b - cost] > EMPTY / 2 and best[c - 1, b - cost] + value > best[c, b]:
                    best[c, b] = best[c - 1, b - cost] + value
                    taken[c][b] = taken[c - 1][b - cost] + [index]
    return best, taken


def solve(pool: pd.DataFrame, values: np.ndarray, costs: np.ndarray,
          slots: dict, budget: int) -> list:
    """Knapsack multi-scelta esatto. Restituisce le posizioni scelte in `pool`."""
    roles = list(slots)
    frontiers = {}
    for role in roles:
        mask = (pool.R == role).to_numpy()
        idx = np.where(mask)[0]
        best, taken = role_frontier(values[idx], costs[idx], slots[role], budget)
        frontiers[role] = (best[slots[role]], taken[slots[role]], idx)

    # Convoluzione fra ruoli: come spartire il budget totale fra i reparti.
    combined = np.full(budget + 1, EMPTY)
    combined[0] = 0.0
    combined_picks: list = [[] for _ in range(budget + 1)]
    for role in roles:
        role_values, role_taken, idx = frontiers[role]
        nxt = np.full(budget + 1, EMPTY)
        nxt_picks: list = [[] for _ in range(budget + 1)]
        for total in range(budget + 1):
            for spent in range(total + 1):
                if combined[total - spent] <= EMPTY / 2 or role_values[spent] <= EMPTY / 2:
                    continue
                candidate = combined[total - spent] + role_values[spent]
                if candidate > nxt[total]:
                    nxt[total] = candidate
                    nxt_picks[total] = combined_picks[total - spent] + [idx[i] for i in role_taken[spent]]
        combined, combined_picks = nxt, nxt_picks
    best_total = int(np.argmax(combined))
    return combined_picks[best_total]


def attainable_replacement(values_sorted: np.ndarray, slot: int, participants: int) -> float:
    """Valore del rimpiazzo che ti resta davvero per lo slot `slot` (0-based)."""
    rank = int(slot * participants + participants // 2)
    if not len(values_sorted):
        return 0.0
    return float(values_sorted[min(rank, len(values_sorted) - 1)])


def shadow_price(pool: pd.DataFrame, values: np.ndarray, slots: dict[str, int],
                 participants: int, credits_left: int, min_price: int = 1) -> float:
    """lambda: valore marginale di un credito, dal surplus ancora in palio.

    Il surplus di ogni giocatore sorteggiabile e' misurato contro il rimpiazzo
    RAGGIUNGIBILE per la posizione che occuperebbe, coerentemente col duale.
    """
    total_surplus = 0.0
    for role, count in slots.items():
        idx = np.where((pool.R == role).to_numpy())[0]
        ordered = np.sort(values[idx])[::-1]
        demand = count * participants
        for rank in range(min(demand, len(ordered))):
            slot = rank // participants
            total_surplus += max(0.0, ordered[rank] - attainable_replacement(ordered, slot, participants))
    seats = sum(slots.values()) * participants
    discretionary = max(1.0, credits_left - seats * min_price)
    return total_surplus / discretionary if total_surplus > 0 else 0.0


def bid_cap(value: float, pool_rank: int, values_sorted: np.ndarray,
            participants: int, lam: float, min_price: int = 1) -> float:
    """b* = (v - mu_r(j)) / lambda, con j stimato dal rango nel pool."""
    slot = pool_rank // participants
    mu = attainable_replacement(values_sorted, slot, participants)
    if lam <= 0:
        return float(min_price)
    return max(float(min_price), min_price + (value - mu) / lam)
