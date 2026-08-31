"""Il modello batte chi segue il mercato? Asta simulata su stagioni vere.

Disegno. Per ogni stagione passata si simula un'asta a 10 squadre con le regole della
lega di Paolo (500 crediti, 3-8-8-6, offerta minima 1, rilancio 1, riserva 1 per slot
aperto). Una squadra offre secondo il modello, le altre nove secondo il prezzo di
mercato preseason. Chi vince paga il secondo prezzo piu' uno. A fine asta ogni rosa
viene valutata simulando le 38 giornate con presenze e fantamedie REALIZZATE, scegliendo
ogni giornata l'XI migliore fra i disponibili e applicando il modificatore difesa.

Informazione disponibile all'asta: solo quello che si sapeva prima che la stagione
iniziasse, cioe' la quotazione iniziale e lo storico delle stagioni precedenti. Il
rendimento realizzato serve soltanto a dare il voto finale.

RISULTATI DELL'ABLAZIONE (8 stagioni, 40 aste per arm, vantaggio in punti stagione):

    mercato puro (controllo)        +6.5 +- 78   t= 0.08   banco calibrato
    modello VOR senza assicurazione -54  +- 96   t=-0.56   indistinguibile dal mercato
    mercato + assicurazione         -771 +- 146  t=-5.29   decisamente peggio
    modello completo                -495 +- 119  t=-4.16   decisamente peggio

Due letture. La prima: il banco e' corretto, l'arm di controllo che bidda esattamente il
prezzo di mercato pareggia come deve (posizione 5.42 su 5.50 attesa, top3 al 30% contro
il 30% teorico). La seconda: il termine assicurativo contro la formazione incompleta,
per quanto il ragionamento sui portieri regga, in asta fa perdere. Il motivo e' che il
prezzo di mercato incorpora gia' l'affidabilita', quindi pagarla di nuovo e' puro
sovrapprezzo. Resta disattivato.

Il modello con valore sopra rimpiazzo non batte il mercato ma non lo perde: la macchina
dei prezzi e' neutra. Per battere il mercato serve un input di valore migliore, non una
matematica migliore sui prezzi.

Uso: .venv/bin/python tools/backtest.py [alpha ...]
     alpha -2 mercato puro | -3 modello senza assicurazione | -1 mercato + assicurazione
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

ALL_SEASONS = ["2015_16", "2016_17", "2017_18", "2018_19", "2019_20", "2020_21",
               "2021_22", "2022_23", "2023_24", "2024_25", "2025_26"]
TEST_SEASONS = ALL_SEASONS[3:]          # dalla 18/19 in poi: servono 3 anni di storico
SLOTS = {"P": 3, "D": 8, "C": 8, "A": 6}
PARTICIPANTS = 10
CREDITS = 500
RESERVE = 1
MIN_PRICE = 1
FORMATIONS = [(3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2), (4, 5, 1), (5, 3, 2), (5, 4, 1)]
DEFENSE_TIERS = [(6.0, 1), (6.5, 3), (7.0, 6)]
VOTE_SD = 0.8
MATCHDAYS = 38
REPETITIONS = 1
WEIGHTS = json.loads(Path("config/pesi_xi.json").read_text(encoding="utf-8"))


def weight(role: str, index: int) -> float:
    table = WEIGHTS[role]
    return table[index] if index < len(table) else table[-1]


def previous(season: str, count: int = 3) -> list[str]:
    i = ALL_SEASONS.index(season)
    return ALL_SEASONS[max(0, i - count):i][::-1]


def load(season: str) -> pd.DataFrame:
    listone = pd.read_excel(f"data/raw/listone_{season}.xlsx", sheet_name="Tutti", header=1)
    stats = pd.read_excel(f"data/raw/statistiche_{season}.xlsx", sheet_name="Tutti", header=1)
    frame = listone[["Id", "R", "Nome", "Squadra", "Qt.I"]].merge(
        stats[["Id", "Pv", "Mv", "Fm"]], on="Id", how="left")
    frame[["Pv", "Mv", "Fm"]] = frame[["Pv", "Mv", "Fm"]].fillna(0.0)
    frame["p_gioca"] = (frame.Pv / MATCHDAYS).clip(0, 1)
    frame["realizzato"] = frame.Fm * frame.Pv

    # Valore atteso con la sola informazione preseason: media pesata 60/30/10 dei punti
    # delle stagioni precedenti. Chi non ha storico prende il minimo del ruolo, non zero.
    total = pd.Series(0.0, index=frame.Id)
    used = pd.Series(0.0, index=frame.Id)
    for past_season, w in zip(previous(season), (0.6, 0.3, 0.1)):
        past = pd.read_excel(f"data/raw/statistiche_{past_season}.xlsx",
                             sheet_name="Tutti", header=1)
        past = past[past.Pv > 0].set_index("Id")
        points = (past.Fm * past.Pv).reindex(frame.Id)
        seen = points.notna()
        total[seen] += points[seen] * w
        used[seen] += w
    frame["punti_attesi"] = (total / used.replace(0, np.nan)).to_numpy()
    # Presenze e fantamedia attese separatamente: servono per il valore sopra rimpiazzo.
    pv_total = pd.Series(0.0, index=frame.Id)
    fm_total = pd.Series(0.0, index=frame.Id)
    used2 = pd.Series(0.0, index=frame.Id)
    for past_season, w in zip(previous(season), (0.6, 0.3, 0.1)):
        past = pd.read_excel(f"data/raw/statistiche_{past_season}.xlsx",
                             sheet_name="Tutti", header=1)
        past = past[past.Pv > 0].set_index("Id")
        pv = past.Pv.reindex(frame.Id)
        fm = past.Fm.reindex(frame.Id)
        seen = pv.notna()
        pv_total[seen] += pv[seen] * w
        fm_total[seen] += fm[seen] * w
        used2[seen] += w
    frame["pv_atteso"] = (pv_total / used2.replace(0, np.nan)).fillna(0.0).to_numpy()
    frame["fm_atteso"] = (fm_total / used2.replace(0, np.nan)).to_numpy()
    for role in SLOTS:
        mask = (frame.R == role) & frame.fm_atteso.isna()
        known = frame.loc[(frame.R == role) & frame.fm_atteso.notna(), "fm_atteso"]
        frame.loc[mask, "fm_atteso"] = known.quantile(0.10) if len(known) else 5.0

    # Segnali che aggiungono informazione oltre il prezzo di mercato.
    prev_seasons = previous(season)
    if prev_seasons:
        p1 = pd.read_excel(f"data/raw/statistiche_{prev_seasons[0]}.xlsx",
                           sheet_name="Tutti", header=1).set_index("Id")
        frame["pv_prec"] = p1.Pv.reindex(frame.Id).to_numpy()
        frame["fm_prec"] = p1.Fm.reindex(frame.Id).to_numpy()
        frame["punti_prec"] = (p1.Fm * p1.Pv).reindex(frame.Id).to_numpy()
        frame["gol90_prec"] = (p1.Gf / p1.Pv.replace(0, np.nan)).reindex(frame.Id).to_numpy()
        squadra_prec = p1.Squadra.reindex(frame.Id)
        frame["cambio_squadra"] = (
            frame.set_index("Id").Squadra.ne(squadra_prec).astype(float).to_numpy()
        )
        presence = []
        for past_season in prev_seasons:
            past = pd.read_excel(f"data/raw/statistiche_{past_season}.xlsx",
                                 sheet_name="Tutti", header=1).set_index("Id")
            presence.append(past.Pv.reindex(frame.Id).notna().astype(float).to_numpy())
        frame["esperienza"] = np.sum(presence, axis=0)
    else:
        for column in ("pv_prec", "fm_prec", "punti_prec", "gol90_prec",
                       "cambio_squadra", "esperienza"):
            frame[column] = np.nan

    # Valore sopra il rimpiazzo: quanto rende in piu' di chi giocherebbe al posto suo.
    # Sommare i punti attesi direbbe che nelle giornate saltate la squadra prende zero.
    fielded = {"P": 1 * PARTICIPANTS, "D": 4 * PARTICIPANTS,
               "C": 4 * PARTICIPANTS, "A": 2 * PARTICIPANTS}
    frame["valore"] = 0.0
    for role, count in fielded.items():
        group = frame[(frame.R == role) & (frame.pv_atteso >= MATCHDAYS * 0.5)]
        levels = group.fm_atteso.sort_values(ascending=False).to_numpy()
        level = levels[min(count, len(levels)) - 1] if len(levels) else 5.5
        mask = frame.R == role
        frame.loc[mask, "valore"] = frame.loc[mask, "pv_atteso"] * (frame.loc[mask, "fm_atteso"] - level)
    return frame


def market_price(frame: pd.DataFrame) -> pd.Series:
    """Quotazione riscalata perche' i 250 sorteggiati costino i crediti della lega."""
    drafted = sum(
        frame[frame.R == role].nlargest(slots * PARTICIPANTS, "Qt.I")["Qt.I"].sum()
        for role, slots in SLOTS.items()
    )
    seats = sum(SLOTS.values()) * PARTICIPANTS
    factor = (CREDITS * PARTICIPANTS - seats) / max(1.0, drafted - seats)
    return (1 + (frame["Qt.I"] - 1) * factor).clip(lower=MIN_PRICE).round()


def model_price(frame: pd.DataFrame, alpha: float = 1.0) -> pd.Series:
    """Prezzo del modello: quota del budget proporzionale al surplus PESATO per la
    posizione che il giocatore occuperebbe nella rosa di chi lo prende."""
    prices = pd.Series(MIN_PRICE, index=frame.index, dtype=float)
    surplus = pd.Series(0.0, index=frame.index, dtype=float)
    for role, slots in SLOTS.items():
        demand = slots * PARTICIPANTS
        group = frame[frame.R == role].sort_values("valore", ascending=False)
        if group.empty:
            continue
        level = group.valore.iloc[min(demand, len(group)) - 1]
        for rank, (idx, row) in enumerate(group.iterrows()):
            if rank >= demand:
                break
            surplus[idx] = weight(role, rank // PARTICIPANTS) * max(0.0, row.valore - level)
    seats = sum(SLOTS.values()) * PARTICIPANTS
    discretionary = CREDITS * PARTICIPANTS - seats
    # `alpha` regola quanto il listino e' concentrato. alpha=1 e' proporzionale al
    # surplus, e concentra moltissimo perche' il surplus e' fortemente asimmetrico.
    # alpha<1 appiattisce: in asta i 250 slot vanno riempiti comunque e la concorrenza
    # tiene su i prezzi di mezzo. Il valore giusto si cerca fuori campione.
    shaped = surplus.clip(lower=0) ** alpha
    rate = discretionary / shaped.sum() if shaped.sum() > 0 else 0.0
    prices = (MIN_PRICE + shaped * rate).round()
    return prices.clip(lower=MIN_PRICE)


USE_INSURANCE = False   # misurato dannoso: vedi ablazione nel docstring
MIN_BY_ROLE = {"P": 1, "D": min(f[0] for f in FORMATIONS), "C": min(f[1] for f in FORMATIONS),
               "A": min(f[2] for f in FORMATIONS)}
FILLER_AVAILABILITY = 0.45


def can_field(avail_by_role: dict[str, np.ndarray]) -> np.ndarray:
    """Per ogni estrazione, dice se esiste un modulo ammesso schierabile."""
    counts = {r: v.sum(axis=1) for r, v in avail_by_role.items()}
    ok = counts["P"] >= 1
    any_formation = np.zeros_like(ok)
    for d, c, a in FORMATIONS:
        any_formation |= (counts["D"] >= d) & (counts["C"] >= c) & (counts["A"] >= a)
    return ok & any_formation


def feasibility(profile: dict[str, list[float]], rng, draws: int = 400) -> float:
    """Probabilita' di riuscire a schierare un XI legale, dati i giocatori in rosa per
    ruolo e le loro disponibilita'. Gli slot ancora vuoti si assumono riempiti da un
    giocatore qualunque."""
    avail = {}
    for role, slots in SLOTS.items():
        probs = list(profile.get(role, []))[:slots]
        probs += [FILLER_AVAILABILITY] * (slots - len(probs))
        avail[role] = rng.random((draws, slots)) < np.array(probs)
    return float(can_field(avail).mean())


def insurance_value(profile: dict[str, list[float]], role: str, availability: float,
                    rng, team_score: float = 66.0) -> float:
    """Quanto vale, in punti stagione, la riduzione del rischio di non schierare.

    Il margine sopra il rimpiazzo non lo vede: se resti senza portiere la giornata vale
    zero, non il punteggio di un portiere leggermente peggiore. Sui ruoli sottili questo
    termine e' un ordine di grandezza sopra quello di margine."""
    # Il confronto e' contro il RIMPIAZZO, non contro il nulla: altrimenti il primo
    # giocatore di un ruolo vale l'intera stagione e il modello svuota il budget subito.
    with_replacement = {r: list(v) for r, v in profile.items()}
    with_replacement.setdefault(role, []).append(FILLER_AVAILABILITY)
    with_candidate = {r: list(v) for r, v in profile.items()}
    with_candidate.setdefault(role, []).append(availability)
    gain = feasibility(with_candidate, rng) - feasibility(with_replacement, rng)
    return max(0.0, gain) * MATCHDAYS * team_score


ORIGINAL_SPLIT = {"P": 0.07, "D": 0.18, "C": 0.25, "A": 0.50}

# Segnali che, misurati su 11 stagioni, aggiungono informazione OLTRE il prezzo di
# mercato (vedi tools/correlazioni.py). I due segni negativi sono il cuore della cosa:
# a parita' di prezzo, chi aveva fantamedia alta e faceva gol gioca meno. Il mercato
# paga la qualita' a partita e sottopaga l'affidabilita'.
SIGNALS = ["pv_prec", "punti_prec", "cambio_squadra", "esperienza", "fm_prec", "gol90_prec"]


def fitted_price(frame: pd.DataFrame, history: list[pd.DataFrame], kappa: float) -> pd.Series:
    """Prezzo di mercato corretto da un modello addestrato SOLO sulle stagioni passate.

    Si stima rango(punti) ~ rango(prezzo) + segnali, si guarda di quanto il modello
    dissente dal mercato, e si sposta il prezzo di quella quantita' moltiplicata per
    kappa. kappa=0 e' il mercato puro. La struttura e' obbligata dai dati: deviare dal
    mercato senza ancorarcisi peggiora, misurato.
    """
    if not history:
        return frame["mercato"]
    train = pd.concat(history, ignore_index=True).dropna(subset=SIGNALS + ["realizzato", "mercato"])
    if len(train) < 300:
        return frame["mercato"]

    def design(d):
        cols = [d["mercato"].rank(pct=True)] + [d[c].rank(pct=True) for c in SIGNALS]
        return np.column_stack([np.ones(len(d))] + [c.to_numpy() for c in cols])

    beta, *_ = np.linalg.lstsq(design(train), train["realizzato"].rank(pct=True).to_numpy(), rcond=None)
    test = frame.copy()
    for c in SIGNALS:
        test[c] = test[c].fillna(test[c].median())
    predicted = design(test) @ beta
    disagreement = pd.Series(predicted, index=test.index).rank(pct=True) - test["mercato"].rank(pct=True)
    return (test["mercato"] * (1 + kappa * disagreement)).round().clip(lower=MIN_PRICE)


def original_price(frame: pd.DataFrame, quality: str = "punti_attesi") -> pd.Series:
    """Il listino dell'advisor originale di fishertiger.

    Ancora il prezzo al valore di mercato riscalato per ruolo sulla ripartizione
    cablata (P 7 / D 18 / C 25 / A 50), poi il tetto d'offerta e' quel prezzo per un
    moltiplicatore di qualita' limitato a [0.75, 1.25]: il valore proiettato puo'
    spostare l'offerta al massimo di un quarto rispetto al mercato.
    """
    price = pd.Series(MIN_PRICE, index=frame.index, dtype=float)
    for role, share in ORIGINAL_SPLIT.items():
        demand = SLOTS[role] * PARTICIPANTS
        group = frame[frame.R == role].nlargest(demand, "Qt.I")
        target = share * CREDITS * PARTICIPANTS
        total = group["Qt.I"].sum()
        scale = target / total if total > 0 else 1.0
        mask = frame.R == role
        price[mask] = (frame.loc[mask, "Qt.I"] * scale).clip(lower=MIN_PRICE)
        # Moltiplicatore di qualita': margine sul cutoff della domanda di lega,
        # normalizzato e schiacciato dentro [0.75, 1.25].
        ranked = frame[mask].sort_values(quality, ascending=False)
        cutoff = ranked[quality].iloc[min(demand, len(ranked)) - 1] if len(ranked) else 0.0
        value = frame.loc[mask, quality].fillna(0.0)
        edge = (value - cutoff) / np.maximum(1.0, np.maximum(value, cutoff))
        price[mask] = price[mask] * (1 + edge * 0.4).clip(0.75, 1.25)
    return price.round().clip(lower=MIN_PRICE)


def run_auction(frame: pd.DataFrame, model_team: int, rng) -> list[list[int]]:
    """Asta sequenziale: si chiamano i giocatori in ordine di prezzo di mercato
    decrescente, ciascuno offre fino alla propria disponibilita', vince chi offre di piu'
    pagando il secondo prezzo piu' uno."""
    credits = [CREDITS] * PARTICIPANTS
    need = [dict(SLOTS) for _ in range(PARTICIPANTS)]
    # Tasso di cambio fra punti stagione e crediti: quanto costa un punto in questa lega.
    total_surplus = float(frame.nlargest(sum(SLOTS.values()) * PARTICIPANTS, "valore").valore.clip(lower=0).sum())
    credits_per_point = (CREDITS * PARTICIPANTS - sum(SLOTS.values()) * PARTICIPANTS) / max(1.0, total_surplus)
    rosters: list[list[int]] = [[] for _ in range(PARTICIPANTS)]
    order = frame.sort_values("mercato", ascending=False)

    for _, row in order.iterrows():
        role = row.R
        buyers = [t for t in range(PARTICIPANTS) if need[t][role] > 0]
        if not buyers:
            continue
        bids = []
        for team in buyers:
            open_slots = sum(need[team].values())
            legal_max = credits[team] - RESERVE * (open_slots - 1)
            if legal_max < MIN_PRICE:
                continue
            if team == model_team:
                base = row.modello
                if USE_INSURANCE:
                    # Al listino si somma il valore assicurativo, che dipende da come
                    # sta messa la rosa in quel momento.
                    owned = frame[frame.Id.isin(rosters[team])]
                    profile = {r: list(owned[owned.R == r].pv_atteso / MATCHDAYS) for r in SLOTS}
                    extra = insurance_value(profile, role, float(row.pv_atteso) / MATCHDAYS, rng)
                    base = base + extra * credits_per_point
            else:
                base = row.mercato
            # Rumore moltiplicativo su TUTTI, modello compreso. Se solo gli avversari
            # sono rumorosi, il massimo di nove estrazioni supera quasi sempre un'offerta
            # deterministica alla media: chi non ha rumore raccoglie solo scarti, e il
            # torneo misura quell'handicap invece del modello. Con l'arm di controllo
            # (modello = mercato) il vantaggio deve risultare zero.
            noise = float(rng.uniform(0.8, 1.25))
            willing = min(legal_max, max(MIN_PRICE, round(base * noise)))
            bids.append((willing, float(rng.random()), team))
        if not bids:
            continue
        bids.sort(reverse=True)
        best, runner = bids[0], bids[1] if len(bids) > 1 else None
        price = min(best[0], (runner[0] + 1) if runner else MIN_PRICE)
        price = max(MIN_PRICE, price)
        winner = best[2]
        credits[winner] -= price
        need[winner][role] -= 1
        rosters[winner].append(row.Id)
        if all(sum(n.values()) == 0 for n in need):
            break
    return rosters


def defense_bonus(keeper, defenders):
    if keeper is None or len(defenders) < 4:
        return 0
    average = (keeper + sum(sorted(defenders, reverse=True)[:3])) / 4
    bonus = 0
    for threshold, value in DEFENSE_TIERS:
        if average >= threshold:
            bonus = value
    return bonus


def season_points(roster: pd.DataFrame, rng, iterations: int = 40) -> float:
    role = roster.R.to_numpy()
    prob = roster.p_gioca.to_numpy()
    fm = roster.Fm.to_numpy()
    mv = roster.Mv.to_numpy()
    totals = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(MATCHDAYS):
            plays = rng.random(len(prob)) < prob
            votes = mv + rng.normal(0, VOTE_SD, len(mv))
            best = None
            for d, c, a in FORMATIONS:
                need = {"P": 1, "D": d, "C": c, "A": a}
                picked, ok = {}, True
                for r, k in need.items():
                    idx = np.where(plays & (role == r))[0]
                    if len(idx) < k:
                        ok = False
                        break
                    picked[r] = idx[np.argsort(-fm[idx])][:k]
                if not ok:
                    continue
                points = sum(fm[i].sum() for i in picked.values())
                points += defense_bonus(votes[picked["P"]][0], list(votes[picked["D"]]))
                if best is None or points > best:
                    best = points
            total += best if best is not None else 0.0
        totals.append(total)
    return float(np.mean(totals))


CACHE: dict[str, pd.DataFrame] = {}
CACHE_OK: set[str] = set()


def load_cached(season: str) -> pd.DataFrame:
    if season not in CACHE:
        frame = load(season)
        frame["mercato"] = market_price(frame)
        CACHE[season] = frame
        CACHE_OK.add(season)
    return CACHE[season]


def main() -> None:
    import sys
    alphas = [float(a) for a in sys.argv[1:]] or [1.0]
    rows = []
    for alpha in alphas:
      for season in TEST_SEASONS:
        frame = load(season)
        frame["mercato"] = market_price(frame)
        global USE_INSURANCE
        # -2 mercato puro | -1 mercato + assicurazione | -3 modello senza assicurazione
        USE_INSURANCE = alpha < 0 and alpha not in (-2.0, -3.0, -4.0, -5.0)
        if alpha >= 10:
            for s2 in ALL_SEASONS[3:ALL_SEASONS.index(season)]:
                load_cached(s2)
        if alpha >= 10:
            # kappa = alpha - 10: quanto ci si stacca dal mercato seguendo il modello
            # addestrato sulle sole stagioni precedenti.
            past = [load_cached(s2) for s2 in ALL_SEASONS[:ALL_SEASONS.index(season)] if s2 in CACHE_OK]
            frame["modello"] = fitted_price(frame, past, alpha - 10.0)
        elif alpha >= 2:
            # Miscela fra prezzo di mercato e prezzo del modello: lambda = alpha - 2.
            # lambda 0 = solo mercato, lambda 1 = solo modello. Serve a misurare QUANTO
            # conviene deviare dal mercato, invece di deciderlo a priori.
            lam = alpha - 2.0
            frame["modello"] = ((1 - lam) * frame["mercato"]
                                + lam * model_price(frame, 1.0)).round().clip(lower=MIN_PRICE)
        elif alpha == -5:
            # Originale, ma il moltiplicatore di qualita' usa il valore sopra rimpiazzo
            # pesato per la posizione nell'XI invece dei punti totali. Isola il
            # contributo dei pesi posizionali dal resto.
            frame["modello"] = original_price(frame, quality="valore")
        elif alpha == -4:
            frame["modello"] = original_price(frame)
        elif alpha == -3:
            frame["modello"] = model_price(frame, 1.0)
        elif alpha < 0:
            # Arm di controllo: stessa informazione degli avversari (il prezzo di
            # mercato), cosi' l'unica differenza resta la macchina del modello
            # (pesi posizionali e termine assicurativo). Isola il contributo della
            # macchina da quello della proiezione.
            frame["modello"] = frame["mercato"]
            frame["valore"] = frame["mercato"]
        else:
            frame["modello"] = model_price(frame, alpha)
        for seat_rep in range(PARTICIPANTS * REPETITIONS):
            seat = seat_rep % PARTICIPANTS
            # Numeri casuali comuni: lo stesso seme per ogni coppia (stagione, posto),
            # indipendente dall'arm. Cosi' tutti gli arm affrontano le stesse aste e le
            # stesse estrazioni di valutazione, e la differenza fra due arm non e'
            # sporcata dal caso. Con una varianza fra stagioni di 500-600 punti senza
            # questo accorgimento nessuna differenza sarebbe leggibile.
            rng = np.random.default_rng(abs(hash((season, seat_rep))) % (2**32))
            rosters = run_auction(frame, seat, rng)
            sizes = [len(r) for r in rosters]
            if min(sizes) != sum(SLOTS.values()):
                continue
            points = [season_points(frame[frame.Id.isin(r)], rng) for r in rosters]
            spent = [CREDITS - 0 for _ in rosters]
            rank = int(np.argsort(np.argsort(-np.array(points)))[seat]) + 1
            rows.append({
                "alpha": alpha,
                "stagione": season[2:7],
                "posto": seat_rep,
                "punti_modello": points[seat],
                "punti_avversari_medi": float(np.mean([p for i, p in enumerate(points) if i != seat])),
                "punti_miglior_avversario": float(max(p for i, p in enumerate(points) if i != seat)),
                "posizione": rank,
            })
    table = pd.DataFrame(rows)
    if table.empty:
        print("nessuna asta completata")
        return
    table["vantaggio"] = table.punti_modello - table.punti_avversari_medi

    print("BACKTEST: modello contro nove che seguono il mercato\n")
    if len(alphas) > 1:
        sweep = table.groupby("alpha").agg(
            punti=("punti_modello", "mean"),
            avversari=("punti_avversari_medi", "mean"),
            vantaggio=("vantaggio", "mean"),
            posizione=("posizione", "mean"),
            top3=("posizione", lambda x: (x <= 3).mean() * 100),
            vittorie=("posizione", lambda x: (x == 1).mean() * 100),
        )
        print("RICERCA DELLA CONCENTRAZIONE (alpha), media su 8 stagioni fuori campione")
        print(sweep.round(2).to_string())
        print("\n  alpha=1 proporzionale al surplus, alpha basso = listino piu' piatto")
        best = sweep.vantaggio.idxmax()
        print(f"  migliore: alpha={best}  vantaggio {sweep.vantaggio.max():+.1f} punti\n")
        table.to_csv("data/processed/backtest.csv", index=False)
        return
    per_season = table.groupby("stagione").agg(
        modello=("punti_modello", "mean"),
        avversari=("punti_avversari_medi", "mean"),
        vantaggio=("vantaggio", "mean"),
        posizione_media=("posizione", "mean"),
    )
    print(per_season.round(1).to_string())
    print()
    print(f"  vantaggio medio: {table.vantaggio.mean():+.1f} punti stagione "
          f"({table.vantaggio.mean() / table.punti_avversari_medi.mean() * 100:+.1f}%)")
    print(f"  posizione media del modello: {table.posizione.mean():.2f} su {PARTICIPANTS}"
          f"   (una squadra a caso farebbe {(PARTICIPANTS + 1) / 2:.2f})")
    print(f"  quota di aste chiuse nei primi 3: "
          f"{(table.posizione <= 3).mean() * 100:.1f}%   (a caso {3 / PARTICIPANTS * 100:.0f}%)")
    print(f"  quota di vittorie: {(table.posizione == 1).mean() * 100:.1f}%"
          f"   (a caso {100 / PARTICIPANTS:.0f}%)")
    print(f"  aste simulate: {len(table)}")
    table.to_csv("data/processed/backtest.csv", index=False)
    print("\nsalvato in data/processed/backtest.csv")


if __name__ == "__main__":
    main()
