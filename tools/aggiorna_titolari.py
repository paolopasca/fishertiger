"""Riscrive titolari.csv dalle presenze REALI delle giornate gia' giocate.

Perche' serve. `data/raw/titolari.csv` porta lo stato TITOLARE / BALLOTTAGGIO / RISERVA
letto dalle probabili formazioni, ed e' datato 23/08/2026, cioe' prima della prima
giornata. Sono previsioni. Dopo qualche giornata si sa chi gioca davvero, e le presenze
sono l'83-94% della varianza dei punti stagionali: nessun ritocco al modello vale quanto
sostituire una previsione con un'osservazione.

Perche' il file va scaricato a mano. Fantacalcio.it ha messo i download Excel dietro
login (l'endpoint pubblico che la repo usava, /api/v1/Excel/..., ora risponde 401), quindi
lo scarica l'utente da loggato:

    Statistiche Serie A  ->  scarica Excel  ->  salvalo come
    data/raw/statistiche_2026_27.xlsx

Poi:

    .venv/bin/python tools/aggiorna_titolari.py

Cosa fa. Per ogni giocatore con presenze osservate calcola la quota Pv/giornate giocate e
la traduce in stato. Le soglie sono volutamente prudenti: con poche giornate una presenza
saltata puo' essere turnover, quindi si passa a BALLOTTAGGIO invece che a RISERVA.

    quota >= 0.70   TITOLARE
    quota <= 0.20   RISERVA
    altrimenti      BALLOTTAGGIO

Chi non compare nelle statistiche mantiene lo stato che aveva: assenza di dato non e'
prova di panchina. Lo stato precedente finisce nella nota, cosi' la modifica resta
verificabile. Il file originale viene salvato accanto con suffisso .backup.
"""
from __future__ import annotations

import shutil
import sys
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import warnings
from rapidfuzz import fuzz

warnings.filterwarnings("ignore")

RAW = Path("data/raw")
STATS = RAW / "statistiche_2026_27.xlsx"
STARTERS = RAW / "titolari.csv"
LISTONE = RAW / "listone_2026_27.xlsx"
TITOLARE, BALLOTTAGGIO, RISERVA = 0.70, 0.20, None


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "".join(c for c in text if c.isalnum() or c == " ").strip()


def status_for(share: float) -> str:
    if share >= TITOLARE:
        return "TITOLARE"
    if share <= BALLOTTAGGIO:
        return "RISERVA"
    return "BALLOTTAGGIO"


def main() -> int:
    if not STATS.exists():
        print(f"manca {STATS}")
        print("Scaricalo da Fantacalcio.it (Statistiche Serie A, pulsante Excel) da loggato:")
        print("il download pubblico non e' piu' accessibile senza account (risponde 401).")
        return 1

    stats = pd.read_excel(STATS, sheet_name="Tutti", header=1)
    listone = pd.read_excel(LISTONE, sheet_name="Tutti", header=1)
    starters = pd.read_csv(STARTERS)

    matchdays = int(stats.Pv.max())
    if matchdays < 1:
        print("le statistiche non contengono ancora presenze: nulla da aggiornare")
        return 1
    played = int((stats.Pv > 0).sum())
    print(f"giornate rilevate dalle statistiche: {matchdays}")
    print(f"giocatori con almeno una presenza a voto: {played}\n")

    # Chiave di aggancio: id quando c'e', altrimenti nome normalizzato dentro la squadra.
    stats_by_id = stats.set_index("Id")
    key = lambda team, name: f"{normalize(team)}|{normalize(name)}"
    stats_by_name = {key(row.Squadra, row.Nome): row for _, row in stats.iterrows()}
    listone_by_name = {key(row.Squadra, row.Nome): int(row.Id) for _, row in listone.iterrows()}
    # Ripiego per somiglianza dentro la stessa squadra. I due file scrivono i nomi in modo
    # diverso ("Paz" contro "Paz N."), e il confronto esatto perde una cinquantina di
    # giocatori. La soglia e' alta e il confronto e' ristretto alla squadra, quindi il
    # rischio di scambiare due omonimi resta basso.
    by_team: dict[str, list] = {}
    for _, row in stats.iterrows():
        by_team.setdefault(normalize(row.Squadra), []).append(row)

    def tokens(name: str) -> set[str]:
        """Parole del nome senza le iniziali puntate: 'Martinez L.' -> {martinez}."""
        return {t for t in normalize(name).split() if len(t) > 1}

    def similar(team: str, name: str, threshold: int = 82):
        target = normalize(name)
        candidates = by_team.get(normalize(team), [])
        best, best_score = None, 0
        for candidate in candidates:
            score = fuzz.token_sort_ratio(target, normalize(candidate.Nome))
            if score > best_score:
                best, best_score = candidate, score
        if best_score >= threshold:
            return best
        # Regola del cognome: i due file scrivono "Lautaro Martinez" e "Martinez L.".
        # Le parole di uno sono contenute in quelle dell'altro. Si accetta solo se il
        # candidato e' unico nella squadra, altrimenti due fratelli o due omonimi si
        # scambierebbero.
        mine = tokens(name)
        if not mine:
            return None
        hits = [c for c in candidates
                if mine <= tokens(c.Nome) or tokens(c.Nome) <= mine]
        return hits[0] if len(hits) == 1 else None

    updated = starters.copy()
    changes, filled_ids, unmatched = [], 0, []
    for index, row in starters.iterrows():
        record = None
        identifier = row.get("id_fantacalcio")
        if pd.notna(identifier) and int(identifier) in stats_by_id.index:
            record = stats_by_id.loc[int(identifier)]
        else:
            # `or` non si puo' usare: su una Series pandas la valutazione booleana e'
            # ambigua e solleva. Serve il controllo esplicito su None.
            record = stats_by_name.get(key(row.squadra, row.nome))
            if record is None:
                record = similar(row.squadra, row.nome)
            # Occasione per riempire gli id mancanti: titolari.csv ne ha solo 73 su 367,
            # e i restanti vengono agganciati per somiglianza, che sbaglia sugli omonimi.
            found = listone_by_name.get(key(row.squadra, row.nome))
            if found is not None and pd.isna(identifier):
                updated.at[index, "id_fantacalcio"] = found
                filled_ids += 1
        if record is None:
            unmatched.append(f"{row.squadra} {row.nome}")
            continue

        share = float(record.Pv) / matchdays
        new_status = status_for(share)
        if new_status != row.status:
            changes.append((row.squadra, row.nome, row.status, new_status,
                            int(record.Pv), matchdays))
        updated.at[index, "status"] = new_status
        updated.at[index, "note"] = (
            f"{int(record.Pv)}/{matchdays} presenze a voto nelle giornate giocate "
            f"(prima era {row.status}, agg. {date.today().isoformat()})"
        )

    print(f"stati cambiati: {len(changes)} su {len(starters)}")
    if filled_ids:
        print(f"id_fantacalcio riempiti: {filled_ids}")
    if unmatched:
        print(f"non agganciati alle statistiche: {len(unmatched)}")
        for name in unmatched[:10]:
            print(f"    {name}")
        if len(unmatched) > 10:
            print(f"    e altri {len(unmatched) - 10}")

    if changes:
        print("\nprime venti modifiche:")
        print(f"  {'squadra':12s} {'giocatore':18s} {'da':13s} {'a':13s} presenze")
        for team, name, before, after, appearances, total in changes[:20]:
            print(f"  {team[:11]:12s} {str(name)[:17]:18s} {before:13s} {after:13s} "
                  f"{appearances}/{total}")

    if "--prova" in sys.argv:
        print("\nprova a vuoto: nessun file scritto (togli --prova per applicare)")
        return 0

    shutil.copy2(STARTERS, STARTERS.with_suffix(".csv.backup"))
    updated.to_csv(STARTERS, index=False)
    print(f"\nscritto {STARTERS}  (copia dell'originale in {STARTERS.with_suffix('.csv.backup')})")
    print("Ora rigenera i dati: Impostazioni -> Genera dati, oppure")
    print("  .venv/bin/python -m advisor.pipeline --profile config/profiles/lega-paolo.json \\")
    print("      --raw-dir data/raw --output-dir data/processed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
