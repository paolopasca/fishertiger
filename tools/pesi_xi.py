"""Pesi posizionali: quanto vale davvero il j-esimo giocatore di un ruolo in rosa.

Il problema. Il modello somma i punti attesi di tutti e 25 i giocatori, ma ogni
giornata ne schieri 11. L'ottavo difensore entra solo quando ne mancano tanti, quindi
vale una frazione del primo. L'obiettivo vero

    V(R) = somma_t E[ max_{XI legale} somma_i X_it ]

non e' additivo, quindi non entra in un knapsack. Ma se si ordinano i giocatori di un
ruolo per valore decrescente, il j-esimo scelto e' sempre il j-esimo migliore, e si puo'
scrivere

    V(R) ~ somma_r somma_j  w_r(j) * v_(j)

con w_r(j) la probabilita' che il j-esimo di quel ruolo finisca schierato. Questo SI'
e' additivo nella posizione, e il DP esistente lo regge senza cambiare struttura.

Qui w_r(j) si misura per simulazione sulle disponibilita' vere del dataset.

Uso: .venv/bin/python tools/pesi_xi.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

DATA = Path("data/processed/lega-paolo-2026-27/2026-27/auction_data.json")
SLOTS = {"P": 3, "D": 8, "C": 8, "A": 6}
FORMATIONS = ["3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-3-2", "5-4-1"]
PARTICIPANTS = 10
MATCHDAYS = 38
ITERATIONS = 3000
BENCH_ROLES = ("P", "P", "D", "D", "D", "C", "C", "C", "A", "A", "A")
MAX_SUBSTITUTIONS = 3


def load_players() -> list[dict]:
    return json.loads(DATA.read_text(encoding="utf-8"))["players"]


def season_value(player: dict) -> float:
    chances = player.get("p_gioca_per_giornata") or []
    votes = player.get("voto_puro_mean_per_giornata") or []
    bonuses = player.get("bonus_atteso_per_giornata") or []
    return float(sum(c * (votes[d] + bonuses[d]) for d, c in enumerate(chances)))


def sample_roster(players: list[dict], offset: int) -> dict[str, list[dict]]:
    """Una delle dieci rose plausibili: per ogni ruolo pesca a scacchiera dal pool
    sorteggiato, partendo da `offset`. Le squadre della lega differiscono cosi'."""
    roster: dict[str, list[dict]] = {}
    for role, slots in SLOTS.items():
        pool = sorted(
            (p for p in players if p["ruolo"] == role),
            key=season_value,
            reverse=True,
        )
        drafted = pool[: slots * PARTICIPANTS]
        picks = [drafted[min(len(drafted) - 1, i * PARTICIPANTS + offset)]
                 for i in range(slots)]
        roster[role] = picks
    return roster


def fielded_rates(roster: dict[str, list[dict]], rng) -> dict[str, np.ndarray]:
    counts = [tuple(int(v) for v in f.split("-")) for f in FORMATIONS]
    roles = list(SLOTS)
    prob = {r: np.array([p["proiezione"]["p_gioca"] for p in roster[r]]) for r in roles}
    # Valore a partita: serve allo scegli-formazione ogni giornata.
    value = {r: np.array([
        p["proiezione"]["voto_puro"] + p["proiezione"]["bonus"] for p in roster[r]
    ]) for r in roles}
    # L'ordinamento delle posizioni deve essere lo STESSO che usa il DP, cioe' il valore
    # stagionale: altrimenti il peso w(j) verrebbe applicato a una posizione diversa.
    season = {r: np.array([season_value(p) for p in roster[r]]) for r in roles}
    order = {r: np.argsort(-season[r]) for r in roles}
    for r in roles:                     # rank 0 = migliore del ruolo
        prob[r] = prob[r][order[r]]
        value[r] = value[r][order[r]]
        season[r] = season[r][order[r]]
    # Serve P(schierato | disponibile), non P(schierato): la disponibilita' individuale
    # e' gia' dentro il valore stagionale, moltiplicarla di nuovo la conterebbe due volte.
    fielded = {r: np.zeros(SLOTS[r]) for r in roles}
    availables = {r: np.zeros(SLOTS[r]) for r in roles}
    draws = 0
    bench_limits = {r: BENCH_ROLES.count(r) for r in roles}

    for _ in range(ITERATIONS):
        available = {r: rng.random(SLOTS[r]) < prob[r] for r in roles}
        best_lineup, best_points = None, -1.0
        for d, c, a in counts:
            need = {"P": 1, "D": d, "C": c, "A": a}
            lineup, feasible = {}, True
            for r, k in need.items():
                idx = np.where(available[r])[0]
                if len(idx) < k:
                    feasible = False
                    break
                lineup[r] = idx[:k]     # gia' ordinati per valore decrescente
            if not feasible:
                continue
            points = sum(value[r][idx].sum() for r, idx in lineup.items())
            if points > best_points:
                best_lineup, best_points = lineup, points
        if best_lineup is None:
            # Formazione incompleta: si prova la sostituzione dalla panchina, che qui
            # coincide con il prendere comunque i disponibili fino al limite di ruolo.
            best_lineup = {}
            for r in roles:
                idx = np.where(available[r])[0]
                best_lineup[r] = idx[: min(len(idx), SLOTS[r])]
        for r in roles:
            availables[r] += available[r]
        for r, idx in best_lineup.items():
            fielded[r][idx] += 1
        draws += 1
    return {r: fielded[r] / np.maximum(availables[r], 1) for r in roles}


def main() -> None:
    players = load_players()
    rng = np.random.default_rng(20262027)
    # Media sulle dieci rose della lega: i pesi non devono dipendere da quale squadra
    # si guarda, e una sola rosa campione da stime rumorose.
    accumulated = {role: np.zeros(SLOTS[role]) for role in SLOTS}
    for offset in range(PARTICIPANTS):
        rates_one = fielded_rates(sample_roster(players, offset), rng)
        for role in SLOTS:
            accumulated[role] += rates_one[role]
    rates = {role: accumulated[role] / PARTICIPANTS for role in SLOTS}
    # Il peso deve essere non crescente nella posizione: il DP assegna al j-esimo scelto
    # il j-esimo peso, e con pesi non monotoni quell'accoppiamento non sarebbe ottimo.
    rates = {role: np.minimum.accumulate(rates[role]) for role in SLOTS}
    roster = sample_roster(players, PARTICIPANTS // 2)

    print("PESI POSIZIONALI: P(schierato | disponibile) per il j-esimo di ogni ruolo\n")
    total = 0.0
    for role in SLOTS:
        weights = rates[role]
        total += weights.sum()
        line = "  ".join(f"{w:.3f}" for w in weights)
        print(f"  {role} (rosa {SLOTS[role]}):  {line}")
        print(f"      disponibilita' dei giocatori campione: "
              + "  ".join(f"{p['proiezione']['p_gioca']:.2f}"
                          for p in sorted(roster[role], key=season_value, reverse=True)))
    print(f"\n  somma dei pesi = {total:.2f}  (non e' 11: qui sono condizionati alla disponibilita')")
    print("\n  rapporto primo/ultimo per ruolo:")
    for role in SLOTS:
        w = rates[role]
        print(f"    {role}: {w[0]:.3f} contro {w[-1]:.3f}  =  {w[0] / max(w[-1], 1e-9):.1f}x")

    export = {role: [round(float(x), 4) for x in rates[role]] for role in SLOTS}
    out = Path("config/pesi_xi.json")
    out.write_text(json.dumps(export, indent=2), encoding="utf-8")
    print(f"\n  scritti in {out}")


if __name__ == "__main__":
    main()
