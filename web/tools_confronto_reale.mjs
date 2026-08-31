// Confronto prodotto contro prodotto: l'advisor VERO della repo (evaluateAuction del
// worker) contro gli avversari realistici descritti da Paolo.
//
// Finora ogni confronto passava per una mia riscrittura del loro metodo in Python. Qui
// gira il loro codice, con lo stesso stato che vedrebbe durante un'asta vera: rose,
// crediti, storico assegnazioni (che alimenta il modello di inflazione), pool residuo.
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { evaluateAuction } from "./src/simulation.worker.js";

const SLOTS = { P: 3, D: 8, C: 8, A: 6 };
const ORDER = ["P", "D", "C", "A"];
const TEAMS = 10, CREDITS = 500, MIN = 1, RESERVE = 1, MATCHDAYS = 38;
const FORMATIONS = [[3,4,3],[3,5,2],[4,3,3],[4,4,2],[4,5,1],[5,3,2],[5,4,1]];
const TIERS = [[6.0,1],[6.5,3],[7.0,6]];
const RULES = {
  participants: TEAMS, startingCredits: CREDITS,
  rosterSlots: SLOTS, virtualGoals: { threshold: 66, increment: 6 },
  defenseModifier: { enabled: true, requiredDefenders: 4,
    tiers: TIERS.map(([m,b]) => ({ minimumAverage: m, bonus: b })) },
  auction: { minPrice: MIN, increment: 1, reserve: RESERVE, nomination: "call_by_role",
    roleBudgetPercentages: { P: 7, D: 19, C: 35, A: 39 }, roleBudgetFlexibilityPercent: 5 },
};

const mulberry = (seed) => { let a = seed >>> 0; return () => {
  a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; };

// Avversari: 5 pianificatori, 2 che caricano il centrocampo, 2 a sentimento.
const makeOpponents = (rnd) => {
  const list = [];
  for (let i = 0; i < 5; i++) { const p = 5 + rnd()*5, d = 15 + rnd()*10, c = 25 + rnd()*10;
    list.push({ tipo: "pianificatore", split: { P: p, D: d, C: c, A: 100-p-d-c },
                toll: 0.02 + rnd()*0.06, lo: 0.9, hi: 1.15 }); }
  for (let i = 0; i < 2; i++) { const p = 5 + rnd()*3, d = 13 + rnd()*7, c = 40 + rnd()*5;
    list.push({ tipo: "centrocampista", split: { P: p, D: d, C: c, A: 100-p-d-c },
                toll: 0.02 + rnd()*0.06, lo: 0.9, hi: 1.15 }); }
  while (list.length < TEAMS - 1) list.push({ tipo: "a sentimento", split: null, toll: 1, lo: 0.7, hi: 1.4 });
  return list;
};

const runAuction = (players, seed) => {
  const rnd = mulberry(seed);
  const opponents = makeOpponents(rnd);
  // Stessa macchina di calcolo del tetto per entrambi i metodi: cambia solo l'ancora di
  // valutazione. La squadra 1 vede i prezzi del modello al posto del FVM, quindi il
  // confronto isola l'ordinamento e non il meccanismo.
  const modelView = new Map(players.map((p) => [p.id,
    { ...p, fvm_original: p.valore_modello, fvm_scaled: p.valore_modello * 0.75 }]));
  const teams = Array.from({ length: TEAMS }, (_, i) => ({
    name: `S${i}`, credits: CREDITS, roster: [] }));
  const need = Array.from({ length: TEAMS }, () => ({ ...SLOTS }));
  const spent = Array.from({ length: TEAMS }, () => ({ P: 0, D: 0, C: 0, A: 0 }));
  const history = [], assigned = {};
  const taken = new Set();

  for (const role of ORDER) {
    const queue = players.filter((p) => p.ruolo === role)
      .sort((a, b) => b.costo_mercato - a.costo_mercato);
    for (const player of queue) {
      if (taken.has(player.id)) continue;
      const buyers = [...Array(TEAMS).keys()].filter((t) => need[t][role] > 0);
      if (!buyers.length) break;
      const remaining = players.filter((p) => !taken.has(p.id) && p.id !== player.id);
      const bids = [];
      for (const t of buyers) {
        const open = Object.values(need[t]).reduce((s, v) => s + v, 0);
        const legal = teams[t].credits - RESERVE * (open - 1);
        if (legal < MIN) continue;
        let want;
        if (t === 0 || (DUE && t === 1)) {
          // L'advisor VERO della repo decide il tetto.
          const view = t === 1
            ? { player: modelView.get(player.id),
                remaining: remaining.map((p) => modelView.get(p.id) || p),
                history: history.map((h) => ({ ...h, player: modelView.get(h.player.id) || h.player })) }
            : { player, remaining, history };
          const advice = evaluateAuction({
            player: view.player, owner: t, teams, mine: teams[t],
            remaining: view.remaining, assigned, history: view.history, rules: RULES });
          want = Math.min(legal, Math.max(0, advice.maxBid));
          if (SAFETY) {
            // Rete di sicurezza che al prodotto MANCA: se i candidati rimasti nel ruolo
            // non bastano piu' a coprire gli slot scoperti, si compra comunque entro il
            // massimo legale. Senza, l'advisor perde le contese sulla fascia bassa e
            // resta con slot vuoti e crediti in mano.
            const left = remaining.filter((p) => p.ruolo === role).length;
            if (left <= need[t][role]) want = legal;
          }
          if (want < MIN) continue;
        } else {
          const o = opponents[DUE ? t - 2 : t - 1];
          let base = player.costo_mercato * (o.lo + rnd() * (o.hi - o.lo));
          if (o.split) {
            const budget = (o.split[role] / 100) * CREDITS * (1 + o.toll);
            const left = budget - spent[t][role] - Math.max(0, need[t][role] - 1) * MIN;
            base = Math.min(base, Math.max(MIN, left));
          }
          want = Math.min(legal, Math.max(MIN, Math.round(base)));
        }
        bids.push([want, rnd(), t]);
      }
      if (!bids.length) continue;
      bids.sort((a, b) => b[0] - a[0] || b[1] - a[1]);
      const runner = bids.length > 1 ? bids[1][0] : 0;
      const price = Math.max(MIN, Math.min(bids[0][0], runner + 1));
      const w = bids[0][2];
      teams[w].credits -= price; teams[w].roster.push(player);
      need[w][role] -= 1; spent[w][role] += price; taken.add(player.id);
      history.push({ player, owner: w, price }); assigned[String(player.id)] = { owner: w, price };
    }
  }
  return { teams, need };
};

const defenseBonus = (keeper, defenders) => {
  if (keeper == null || defenders.length < 4) return 0;
  const avg = (keeper + [...defenders].sort((a, b) => b - a).slice(0, 3).reduce((s, v) => s + v, 0)) / 4;
  let bonus = 0; for (const [th, v] of TIERS) if (avg >= th) bonus = v; return bonus;
};

const seasonPoints = (roster, seed, iterations = 60) => {
  const rnd = mulberry(seed);
  const gauss = () => Math.sqrt(-2 * Math.log(Math.max(rnd(), 1e-12))) * Math.cos(2 * Math.PI * rnd());
  let total = 0;
  for (let it = 0; it < iterations; it++) {
    for (let day = 0; day < MATCHDAYS; day++) {
      const plays = roster.map((p) => rnd() < p.realizzato.pv / MATCHDAYS);
      const votes = roster.map((p) => p.realizzato.mv + 0.8 * gauss());
      let best = null;
      for (const [d, c, a] of FORMATIONS) {
        const want = { P: 1, D: d, C: c, A: a }; const chosen = {}; let ok = true;
        for (const r of ORDER) {
          const idx = roster.map((p, i) => [p, i]).filter(([p, i]) => plays[i] && p.ruolo === r)
            .sort((x, y) => y[0].realizzato.fm - x[0].realizzato.fm).slice(0, want[r]);
          if (idx.length < want[r]) { ok = false; break; }
          chosen[r] = idx;
        }
        if (!ok) continue;
        let pts = 0; for (const r of ORDER) for (const [p] of chosen[r]) pts += p.realizzato.fm;
        pts += defenseBonus(votes[chosen.P[0][1]], chosen.D.map(([, i]) => votes[i]));
        if (best === null || pts > best) best = pts;
      }
      total += best ?? 0;
    }
  }
  return total / iterations;
};

const files = readdirSync("../data/processed/js_backtest").filter((f) => f.endsWith(".json")).sort();
const reps = Number(process.argv[2] || 4);
const SAFETY = process.argv[3] === "rete";
// DUE = il posto 1 e' il nostro modello; altrimenti e' un avversario come gli altri.
const DUE = process.argv[4] === "due";
const rows = [];
const esportate = [];
for (const file of files) {
  const { stagione, players } = JSON.parse(readFileSync(`../data/processed/js_backtest/${file}`, "utf8"));
  for (let rep = 0; rep < reps; rep++) {
    const seed = (stagione.charCodeAt(0) * 7919 + rep * 104729) >>> 0;
    const { teams, need } = runAuction(players, seed);
    const full = need.map((n) => Object.values(n).reduce((s, v) => s + v, 0) === 0);
    if (!full[0] || (DUE && !full[1])) {
      console.log(`  ${stagione} rep${rep}: advisor NON completa la rosa. mancano ` +
        ORDER.map((r) => `${r}:${need[0][r]}`).join(" ") +
        `  crediti residui ${teams[0].credits}  presi ${teams[0].roster.length}/25`);
      continue;
    }
    const points = teams.map((t, i) => full[i] ? seasonPoints(t.roster, seed + i) : null);
    // Esporta le rose per la valutazione col Monte Carlo della repo. I parametri dei
    // giocatori sono quelli REALIZZATI: la simulazione deve riprodurre la stagione vera.
    esportate.push({
      stagione, seed,
      rosters: Object.fromEntries(teams.map((t, i) => [
        i === 0 ? "advisor" : (DUE && i === 1 ? "modello" : `avv${i}`),
        t.roster.map((p) => p.id)])),
      players: players.map((p) => ({
        id: p.id, nome: p.nome, ruolo: p.ruolo, squadra: p.squadra,
        p_gioca_per_giornata: Array(MATCHDAYS).fill(Math.min(0.99, p.realizzato.pv / MATCHDAYS)),
        voto_puro_mean_per_giornata: Array(MATCHDAYS).fill(p.realizzato.mv || 5.5),
        voto_puro_std_per_giornata: Array(MATCHDAYS).fill(0.8),
        bonus_atteso_per_giornata: Array(MATCHDAYS).fill((p.realizzato.fm || 5.5) - (p.realizzato.mv || 5.5)),
        // I tassi REALI: il loro Monte Carlo costruisce il punteggio da qui.
        event_rates: p.event_rates_reali,
      })),
    });
    const others = points.filter((p, i) => i !== 0 && (!DUE || i !== 1) && p !== null);
    rows.push({ stagione, rep, advisor: points[0], modello: DUE ? points[1] : null,
                avversari_medi: others.reduce((s, v) => s + v, 0) / others.length,
                pos_advisor: 1 + points.filter((p, i) => i !== 0 && p !== null && p > points[0]).length,
                pos_modello: 1 + points.filter((p, i) => i !== 1 && p !== null && p > points[1]).length,
                spesa: CREDITS - teams[0].credits });
  }
}
writeFileSync("../data/processed/rose_simulate.json", JSON.stringify({
  nomi: Object.keys(esportate[0]?.rosters ?? {}), casi: esportate.slice(0, 8) }));
const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
console.log("ADVISOR VERO DELLA REPO contro avversari realistici\n");
console.log("stagione   advisor  modello  avversari   pos.adv  pos.mod");
const bySeason = {};
for (const r of rows) (bySeason[r.stagione] ||= []).push(r);
for (const [s, rs] of Object.entries(bySeason))
  console.log(`${s}  ${mean(rs.map(r=>r.advisor)).toFixed(0).padStart(8)}  ${mean(rs.map(r=>r.modello)).toFixed(0).padStart(7)}  ${mean(rs.map(r=>r.avversari_medi)).toFixed(0).padStart(9)}  ${mean(rs.map(r=>r.pos_advisor)).toFixed(2).padStart(7)}  ${mean(rs.map(r=>r.pos_modello)).toFixed(2).padStart(7)}`);
console.log(`\nmedia: advisor ${mean(rows.map(r=>r.advisor)).toFixed(1)}  modello ${mean(rows.map(r=>r.modello)).toFixed(1)}  avversari ${mean(rows.map(r=>r.avversari_medi)).toFixed(1)}`);
console.log(`posizione media su ${TEAMS}: advisor ${mean(rows.map(r=>r.pos_advisor)).toFixed(2)}  modello ${mean(rows.map(r=>r.pos_modello)).toFixed(2)}`);
const paired = (f, label) => {
  const per = Object.values(bySeason).map(rs => mean(rs.map(f)));
  const m = mean(per);
  const sd = Math.sqrt(per.reduce((s,v)=>s+(v-m)**2,0)/(per.length-1));
  const se = sd/Math.sqrt(per.length);
  console.log(`  ${label.padEnd(34)} ${m>=0?"+":""}${m.toFixed(1)} +- ${se.toFixed(1)}  t = ${(m/se).toFixed(2)}  ${Math.abs(m/se)>2?"REALE":""}`);
};
console.log("\nCONFRONTI APPAIATI (stessa asta)");
paired(r => r.advisor - r.avversari_medi, "advisor repo - avversari");
if (DUE) {
  paired(r => r.modello - r.avversari_medi, "nostro modello - avversari");
  paired(r => r.modello - r.advisor, "nostro modello - advisor repo");
}
