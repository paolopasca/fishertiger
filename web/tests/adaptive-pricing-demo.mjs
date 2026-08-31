// Dimostrazione: cosa succede ai prezzi quando la lega spende poco su un reparto.
// Non serve nessuna AI, e' una legge di conservazione: i crediti non spesi sui
// difensori non spariscono, verranno spesi su quello che resta.
//   node tests/adaptive-pricing-demo.mjs
import { readFileSync } from "node:fs";
import { evaluateAuction } from "../src/simulation.worker.js";

const payload = JSON.parse(
  readFileSync(
    new URL("../../data/processed/lega-paolo-2026-27/2026-27/auction_data.json", import.meta.url),
    "utf8",
  ),
);
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
    roleBudgetPercentages: { P: 7, D: 18, C: 25, A: 50 },
    roleBudgetFlexibilityPercent: 5,
  },
};

const val = (p) =>
  (p.p_gioca_per_giornata || []).reduce(
    (s, q, d) =>
      s + q * ((p.voto_puro_mean_per_giornata?.[d] || 0) + (p.bonus_atteso_per_giornata?.[d] || 0)),
    0,
  );

// Costruisce uno stato d'asta: le altre 9 squadre hanno gia' comprato `perTeam`
// difensori ciascuna al prezzo indicato. La mia squadra non ha comprato nulla.
const stateAfterDefenderRun = (pricePerDefender, perTeam) => {
  const defenders = [...players]
    .filter((p) => p.ruolo === "D")
    .sort((a, b) => val(b) - val(a));
  const teams = Array.from({ length: 10 }, (_, i) => ({
    name: i === 0 ? "Mine" : `Opp ${i}`,
    credits: 500,
    roster: [],
  }));
  const history = [];
  let cursor = 0;
  for (let owner = 1; owner < 10; owner++) {
    for (let k = 0; k < perTeam; k++) {
      const p = defenders[cursor++];
      teams[owner].roster.push(p);
      teams[owner].credits -= pricePerDefender;
      history.push({ player: p, owner, price: pricePerDefender });
    }
  }
  const taken = new Set(history.map((h) => String(h.player.id)));
  const remaining = players.filter((p) => !taken.has(String(p.id)));
  return { teams, history, remaining };
};

const capFor = (candidate, state) => {
  const advice = evaluateAuction({
    player: candidate,
    owner: 0,
    teams: state.teams,
    mine: state.teams[0],
    remaining: state.remaining,
    assigned: {},
    history: state.history,
    rules: RULES,
  });
  return advice;
};

const bestOf = (role, pool) =>
  [...pool].filter((p) => p.ruolo === role).sort((a, b) => val(b) - val(a))[0];

console.log("Scenario: le altre 9 squadre comprano 4 difensori a testa (36 difensori).");
console.log("Confronto due mondi: li pagano CARI (40 crediti) oppure a SALDO (12 crediti).\n");

const rows = [];
for (const [label, price] of [["cari  (40 cr)", 40], ["a saldo (12 cr)", 12]]) {
  const state = stateAfterDefenderRun(price, 4);
  const spent = 36 * price;
  const bestD = bestOf("D", state.remaining);
  const bestA = bestOf("A", state.remaining);
  const dAdv = capFor(bestD, state);
  const aAdv = capFor(bestA, state);
  rows.push({ label, spent, bestD, bestA, dAdv, aAdv });
  console.log(`difensori venduti ${label}  -> la lega ha speso ${spent} crediti sui difensori`);
  console.log(
    `   crediti residui in lega: ${state.teams.reduce((s, t) => s + t.credits, 0)}`,
  );
  console.log(
    `   miglior D rimasto  ${String(bestD.nome).slice(0, 14).padEnd(15)} tetto ${String(dAdv.maxBid).padStart(3)}  prezzo equo ${String(dAdv.summary.exchangeCap).padStart(3)}  mercato ${dAdv.summary.estimatedMarketPrice}`,
  );
  console.log(
    `   miglior A rimasto  ${String(bestA.nome).slice(0, 14).padEnd(15)} tetto ${String(aAdv.maxBid).padStart(3)}  prezzo equo ${String(aAdv.summary.exchangeCap).padStart(3)}  mercato ${aAdv.summary.estimatedMarketPrice}`,
  );
  console.log(
    `   crediti per punto di valore: ${dAdv.summary.creditsPerValue}   inflazione osservata: ${dAdv.summary.marketInflation}\n`,
  );
}

const [caro, saldo] = rows;
console.log("EFFETTO MISURATO passando da 'cari' a 'a saldo':");
console.log(
  `  crediti che restano in circolo:      +${caro.spent - saldo.spent}`,
);
console.log(
  `  tetto sul miglior attaccante:        ${caro.aAdv.maxBid} -> ${saldo.aAdv.maxBid}  (${saldo.aAdv.maxBid > caro.aAdv.maxBid ? "sale" : "scende"})`,
);
console.log(
  `  tetto sul miglior difensore rimasto: ${caro.dAdv.maxBid} -> ${saldo.dAdv.maxBid}`,
);
console.log(
  `  crediti per punto di valore:         ${caro.dAdv.summary.creditsPerValue} -> ${saldo.dAdv.summary.creditsPerValue}`,
);
