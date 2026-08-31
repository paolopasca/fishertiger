import test from "node:test";
import assert from "node:assert/strict";
import { evaluateAuction } from "../src/simulation.worker.js";

const LIMITS = { P: 3, D: 8, C: 8, A: 6 };
let nextId = 1;

const player = (role, value, fvm = 1, overrides = {}) => ({
  id: nextId++,
  nome: `${role}-${nextId}`,
  ruolo: role,
  squadra: "Test",
  fvm_scaled: fvm,
  p_gioca_per_giornata: [1],
  voto_puro_mean_per_giornata: [value],
  bonus_atteso_per_giornata: [0],
  ...overrides,
});

const rosterWithOpenSlots = (open) =>
  Object.entries(LIMITS).flatMap(([role, limit]) =>
    Array.from({ length: limit - (open[role] || 0) }, () => player(role, 6)),
  );

const team = (name, credits, open) => ({
  name,
  credits,
  roster: rosterWithOpenSlots(open),
});

// Un pool realistico ha un gradiente valore-prezzo: senza, non esiste costo
// opportunita' e ogni tetto degenera sulla sola fattibilita' di budget.
const gradedPool = (role, count) =>
  Array.from({ length: count }, (_, index) => {
    const quality = 1 - index / count;
    return player(role, 4 + 8 * quality, 1 + 40 * quality * quality);
  });

const OPEN = { A: 2, C: 3, D: 3 };
const POOL = [
  ...gradedPool("A", 25),
  ...gradedPool("C", 25),
  ...gradedPool("D", 25),
];

const adviceFor = (value, { credits = 200, fvm = 20 } = {}) => {
  const candidate = player("A", value, fvm, { nome: "Candidato" });
  return evaluateAuction({
    player: candidate,
    owner: 0,
    teams: [team("Mine", credits, OPEN), team("Opponent", credits, OPEN)],
    mine: null,
    remaining: [candidate, ...POOL],
    assigned: {},
  });
};

test("il tetto cresce col valore del candidato", () => {
  const caps = [6, 10, 16, 25, 40].map((value) => adviceFor(value).maxBid);
  for (let i = 1; i < caps.length; i++) {
    assert.ok(
      caps[i] >= caps[i - 1],
      `il tetto deve essere non decrescente nel valore: ${caps.join(" -> ")}`,
    );
  }
  // La crescita e' volutamente limitata: il tetto resta ancorato al prezzo di mercato
  // entro il moltiplicatore di qualita'. Un tetto libero di staccarsi dal mercato e'
  // stato provato e perde, in backtest su 240 aste, 257 +- 126 punti stagione (t=-2.03),
  // perche' il prezzo di mercato e' un predittore migliore della nostra proiezione.
  assert.ok(
    caps.at(-1) > caps[0],
    `un candidato piu' forte deve valere di piu': ${caps.join(" -> ")}`,
  );
});

test("il tetto resta dentro il moltiplicatore di qualita' sul prezzo di mercato", () => {
  // Invariante ripristinato dopo il backtest: staccarsi dal mercato peggiora in modo
  // monotono (lambda 0 -> -101 punti, lambda 0.15 -> -482). Il clamp e' una protezione.
  const advice = adviceFor(40);
  assert.ok(
    advice.maxBid <= advice.summary.estimatedMarketPrice * 1.3,
    `tetto ${advice.maxBid} contro mercato ${advice.summary.estimatedMarketPrice}`,
  );
});

test("un candidato al livello di rimpiazzo non merita un sovrapprezzo", () => {
  const advice = adviceFor(6);
  assert.ok(
    advice.maxBid < advice.summary.estimatedMarketPrice,
    `senza surplus sul rimpiazzo il tetto ${advice.maxBid} deve stare sotto il mercato ${advice.summary.estimatedMarketPrice}`,
  );
});

test("il tetto non supera mai il massimo legale", () => {
  const advice = adviceFor(500, { credits: 40 });
  assert.ok(advice.maxBid <= advice.legalMax, "il tetto sfonda il massimo legale");
});

test("il riepilogo espone prezzo di indifferenza, prezzo equo e fattibilita'", () => {
  const summary = adviceFor(25).summary;
  for (const key of ["indifferencePrice", "exchangeCap", "feasibilityMax", "creditsPerValue"]) {
    assert.equal(typeof summary[key], "number", `manca ${key} nel riepilogo`);
  }
});

test("il tetto cala quando restano meno crediti per completare la rosa", () => {
  const rich = adviceFor(25, { credits: 300 }).maxBid;
  const poor = adviceFor(25, { credits: 60 }).maxBid;
  assert.ok(poor < rich, `povero ${poor} deve stare sotto ricco ${rich}`);
});

test("con completamento impossibile senza il candidato resta acquistabile", () => {
  const candidate = player("A", 10, 1, { nome: "Unico" });
  const advice = evaluateAuction({
    player: candidate,
    owner: 0,
    teams: [team("Mine", 50, { A: 1 }), team("Opponent", 50, { A: 1 })],
    mine: null,
    remaining: [candidate],
    assigned: {},
  });
  assert.ok(advice.maxBid > 0, "un candidato indispensabile deve restare acquistabile");
  assert.ok(advice.maxBid <= advice.legalMax, "e comunque entro il massimo legale");
});
