"""Valuta le rose con il Monte Carlo DELLA REPO, non col mio.

Finora ho valutato le rose con una simulazione scritta da me. Qui si usa
advisor/simulation.py:simulate_season, cioe' il loro codice, che oltre ai punti produce
quello che conta davvero: la distribuzione dei piazzamenti e l'utilita' attesa in euro.

Differenze rispetto alla mia valutazione, che vanno dichiarate:
  - gioca un calendario di lega vero (girone all'italiana) invece di sommare punti;
  - converte i punti in gol virtuali e poi in punti classifica 3/1/0;
  - applica panchina e sostituzioni secondo le regole del profilo;
  - estrae gli eventi (gol, assist, ammonizioni) da Poisson invece di usare la fantamedia.

Le rose in ingresso arrivano dalle aste simulate in web/tools_confronto_reale.mjs.

Uso: .venv/bin/python tools/valuta_con_loro_mc.py rose.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, warnings
from advisor.config import LeagueConfig
from advisor.simulation import simulate_season
warnings.filterwarnings("ignore")

MATCHDAYS = 38
PARTICIPANTS = 10


def round_robin(names: list[str], days: int) -> list[dict]:
    """Girone all'italiana ripetuto fino a coprire `days` giornate."""
    rotation = list(range(len(names)))
    base = []
    for _ in range(len(names) - 1):
        fixtures = [(rotation[i], rotation[-1 - i]) for i in range(len(names) // 2)]
        base.append(fixtures)
        rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]
    out = []
    for day in range(days):
        pairs = base[day % len(base)]
        flip = (day // len(base)) % 2
        out.append({
            "number": day + 1, "serie_a_matchday": day + 1,
            "fixtures": [{"home": names[b if flip else a], "away": names[a if flip else b]}
                         for a, b in pairs],
        })
    return out


def build_payload(players: list[dict], names: list[str]) -> dict:
    """Il payload nel formato che simulate_season si aspetta."""
    teams = sorted({p["squadra"] for p in players})
    serie_a = []
    for day in range(1, MATCHDAYS + 1):
        for i in range(0, len(teams) - 1, 2):
            serie_a.append({"matchday": day, "home_team": teams[i], "away_team": teams[i + 1]})
    return {
        "players": players,
        "calendario_serie_a": serie_a,
        "calendario_lega": {"teams": names, "matchdays": round_robin(names, MATCHDAYS)},
    }


def main() -> None:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "data/processed/rose_simulate.json")
    payload_in = json.loads(source.read_text(encoding="utf-8"))
    league = LeagueConfig(
        participants=PARTICIPANTS, starting_credits=500,
        score_threshold=66, points_per_virtual_goal=6,
        defense_modifier_enabled=True, defense_table="LEAGUE",
        defense_tiers=((6.0, 1), (6.5, 3), (7.0, 6)),
        slots=(("P", 3), ("D", 8), ("C", 8), ("A", 6)),
        team_names=tuple(payload_in["nomi"]),
    )
    rows = []
    for case in payload_in["casi"]:
        players = case["players"]
        rosters = {name: ids for name, ids in case["rosters"].items()}
        payload = build_payload(players, list(rosters))
        try:
            result = simulate_season(payload, rosters, iterations=200, seed=case["seed"], league=league)
        except Exception as error:
            print(f"  {case['stagione']}: simulazione rifiutata ({error})")
            continue
        for name, stats in result.teams.items():
            rows.append({"stagione": case["stagione"], "squadra": name,
                         "punti_attesi": stats["expected_points"],
                         "punteggio_atteso": stats["expected_score"],
                         "prob_top3": stats["top3_probability"],
                         "utilita_eur": stats["expected_utility"]})
    table = pd.DataFrame(rows)
    if table.empty:
        print("nessuna simulazione completata"); return
    print("VALUTAZIONE COL MONTE CARLO DELLA REPO\n")
    summary = table.groupby("squadra").agg(
        punti_classifica=("punti_attesi", "mean"),
        punteggio=("punteggio_atteso", "mean"),
        prob_top3=("prob_top3", "mean"),
        utilita_eur=("utilita_eur", "mean"),
    ).sort_values("punti_classifica", ascending=False)
    print(summary.round(3).to_string())
    table.to_csv("data/processed/valutazione_loro_mc.csv", index=False)


if __name__ == "__main__":
    main()
