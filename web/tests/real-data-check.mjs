// Controllo su dati veri: carica il dataset generato per la lega a 10 squadre e
// verifica che i tetti d'offerta restino sensati in vari momenti dell'asta.
// Non e' un test unitario, e' una prova di realta'. Si lancia a mano:
//   node tests/real-data-check.mjs
import { readFileSync } from "node:fs";
import { evaluateAuction } from "../src/simulation.worker.js";

const DATA = "../../data/processed/lega-paolo-2026-27/2026-27/auction_data.json";
const payload = JSON.parse(readFileSync(new URL(DATA, import.meta.url), "utf8"));
const players = payload.players;

const RULES = {
  participants: 10,
  startingCredits: 500,
  rosterSlots: { P: 3, D: 8, C: 8, A: 6 },
  virtualGoals: { threshold: 66, increment: 6 },
  defenseModifier: {
    enabled: true,
    requiredDefenders: 4,
    tiers: [
      { minimumAverage: 6.0, bonus: 1 },
      { minimumAverage: 6.5, bonus: 3 },
      { minimumAverage: 7.0, bonus: 6 },
    ],
  },
  auction: {
    minPrice: 1,
    increment: 1,
    reserve: 1,
    nomination: "call",
    roleBudgetPercentages: { P: 7, D: 19, C: 35, A: 39 },
    roleBudgetFlexibilityPercent: 5,
  },
};

const emptyTeam = (name) => ({ name, credits: 500, roster: [] });
const teams = Array.from({ length: 10 }, (_, i) => emptyTeam(`Squadra ${i + 1}`));

const contribution = (p) =>
  (p.p_gioca_per_giornata || []).reduce(
    (s, q, d) =>
      s + q * ((p.voto_puro_mean_per_giornata?.[d] || 0) + (p.bonus_atteso_per_giornata?.[d] || 0)),
    0,
  );

const byValue = [...players].sort((a, b) => contribution(b) - contribution(a));
const byFvm = [...players].sort((a, b) => (b.fvm_original || 0) - (a.fvm_original || 0));

console.log(`dataset: ${players.length} giocatori, lega 10 squadre x 500 crediti\n`);
console.log("ASTA APPENA INIZIATA, rose vuote, 500 crediti a testa");
console.log(
  "giocatore".padEnd(18) +
    "R".padEnd(3) +
    "FVM".padStart(6) +
    "valore".padStart(8) +
    "mercato".padStart(9) +
    "maxBid".padStart(8) +
    "indiff".padStart(8) +
    "scambio".padStart(9) +
    "  giudizio",
);

const show = (candidate, teamState, pool) => {
  const advice = evaluateAuction({
    player: candidate,
    owner: 0,
    teams: teamState,
    mine: teamState[0],
    remaining: pool,
    assigned: {},
    rules: RULES,
  });
  const s = advice.summary;
  console.log(
    String(candidate.nome).slice(0, 17).padEnd(18) +
      String(candidate.ruolo).padEnd(3) +
      String(Math.round(candidate.fvm_original || 0)).padStart(6) +
      String(Math.round(contribution(candidate))).padStart(8) +
      String(s.estimatedMarketPrice).padStart(9) +
      String(advice.maxBid).padStart(8) +
      String(s.indifferencePrice).padStart(8) +
      String(s.exchangeCap).padStart(9) +
      "  " +
      advice.recommendation,
  );
  return advice;
};

const pool = players;
const sample = [
  byFvm[0],
  byFvm[1],
  byValue[0],
  byValue[3],
  byFvm[40],
  byFvm[120],
  byFvm[300],
  byFvm[480],
];
const seen = new Set();
for (const p of sample) {
  if (!p || seen.has(p.id)) continue;
  seen.add(p.id);
  show(p, teams, pool);
}

// Spesa totale se comprassi ogni ruolo al proprio tetto: deve restare sotto il budget.
console.log("\nCONTROLLO DI COERENZA DI BUDGET");
let spend = 0;
const mine = emptyTeam("Mine");
const others = Array.from({ length: 9 }, (_, i) => emptyTeam(`Opp ${i + 1}`));
const remaining = [...players];
for (const role of ["P", "D", "C", "A"]) {
  const best = remaining
    .filter((p) => p.ruolo === role)
    .sort((a, b) => contribution(b) - contribution(a))[0];
  const advice = evaluateAuction({
    player: best,
    owner: 0,
    teams: [mine, ...others],
    mine,
    remaining,
    assigned: {},
    rules: RULES,
  });
  console.log(
    `  miglior ${role}: ${String(best.nome).slice(0, 16).padEnd(17)} tetto ${String(advice.maxBid).padStart(4)}  (mercato ${advice.summary.estimatedMarketPrice})`,
  );
  spend += advice.maxBid;
}
console.log(`  somma dei tetti sui 4 migliori = ${spend} su 500 crediti`);
console.log(
  spend < 500
    ? "  OK: comprare i 4 migliori ai rispettivi tetti non sfonda il budget"
    : "  ATTENZIONE: i tetti sommati sfondano il budget",
);
