// Il piano e la lista di chiamata devono rispettare la fase dell'asta.
//
// Con `call_by_role` si chiama un reparto alla volta: finche' dura la fase portieri
// nessuno puo' offrire su un attaccante. Prima di queste prove il pannello "Prossime
// mosse" ordinava per sola scarsita' e poteva mettere in cima un reparto su cui non si
// puo' fare niente, con sotto quattro volte la stessa frase.
import test from "node:test";
import assert from "node:assert/strict";
import {
  evaluateAuction,
  evaluateOverview,
  evaluateShortlist,
} from "../src/simulation.worker.js";

const LIMITS = { P: 3, D: 8, C: 8, A: 6 };
let nextId = 1;

const player = (role, value = 6, overrides = {}) => ({
  id: nextId++,
  nome: `${role}-${nextId}`,
  ruolo: role,
  squadra: "Test",
  fvm_scaled: 1,
  p_gioca_per_giornata: [1],
  voto_puro_mean_per_giornata: [value],
  bonus_atteso_per_giornata: [0],
  ...overrides,
});

const rosterWithOpenSlots = (open) =>
  Object.entries(LIMITS).flatMap(([role, limit]) =>
    Array.from({ length: limit - (open[role] || 0) }, () => player(role)),
  );

const team = (name, credits, open) => ({
  name,
  credits,
  roster: rosterWithOpenSlots(open),
});

const PER_RUOLO = { auction: { nomination: "call_by_role" } };

/** Pool graduato: senza differenze di valore ogni candidato vale l'altro e
 *  l'ordinamento della lista non direbbe niente. */
const pool = (role, quanti, primo = 12) =>
  Array.from({ length: quanti }, (_, index) =>
    player(role, primo - index * 0.4, { fvm_scaled: (quanti - index) * 2 }),
  );

test("il reparto in fase e' il primo del piano, anche quando altri sono piu' scarsi", () => {
  // Tutti hanno la rosa vuota, quindi la fase e' portieri. Gli attaccanti sono il ruolo
  // piu' scarso (6 posti a squadra contro un'offerta risicata) e senza il termine di
  // fase salirebbero in cima.
  const teams = [
    team("Mine", 500, { P: 3, D: 8, C: 8, A: 6 }),
    team("Rivale", 500, { P: 3, D: 8, C: 8, A: 6 }),
  ];
  const remaining = [
    ...pool("P", 12),
    ...pool("D", 30),
    ...pool("C", 30),
    ...pool("A", 13),
  ];

  const result = evaluateOverview({
    teams,
    mine: teams[0],
    remaining,
    assigned: {},
    rules: PER_RUOLO,
  });

  assert.equal(result.summary.activeRole, "P");
  assert.equal(result.priorities[0].role, "P");
  assert.equal(result.priorities[0].callable, true);
  assert.ok(
    result.priorities.slice(1).every((item) => item.callable === false),
    "solo il reparto in fase e' chiamabile",
  );
});

test("senza chiamata per ruolo nessun reparto e' marcato come fuori fase", () => {
  const teams = [team("Mine", 500, { P: 3, D: 8, C: 8, A: 6 })];
  const remaining = [...pool("P", 12), ...pool("A", 13)];

  const result = evaluateOverview({ teams, mine: teams[0], remaining, assigned: {} });

  assert.equal(result.summary.activeRole, null);
  assert.ok(result.priorities.every((item) => item.callable === true));
});

test("le motivazioni del piano non sono la stessa frase per ogni reparto", () => {
  const teams = [
    team("Mine", 500, { P: 3, D: 8, C: 8, A: 6 }),
    team("Rivale", 500, { P: 3, D: 8, C: 8, A: 6 }),
  ];
  const remaining = [
    ...pool("P", 12),
    ...pool("D", 30),
    ...pool("C", 30),
    ...pool("A", 13),
  ];

  const result = evaluateOverview({
    teams,
    mine: teams[0],
    remaining,
    assigned: {},
    rules: PER_RUOLO,
  });

  const motivazioni = result.priorities.map((item) => item.reason);
  assert.equal(
    new Set(motivazioni).size,
    motivazioni.length,
    `quattro reparti, quattro frasi diverse: ${motivazioni.join(" | ")}`,
  );
  // Ogni frase porta l'offerta residua del ruolo, che e' il numero che decide se si
  // puo' aspettare.
  assert.match(result.priorities[0].reason, /12 liberi/);
});

test("la lista di chiamata contiene solo il ruolo in fase", () => {
  const teams = [
    team("Mine", 500, { P: 3, D: 8, C: 8, A: 6 }),
    team("Rivale", 500, { P: 3, D: 8, C: 8, A: 6 }),
  ];
  const remaining = [...pool("P", 12), ...pool("A", 13)];

  const result = evaluateShortlist({
    teams,
    mine: teams[0],
    owner: 0,
    remaining,
    assigned: {},
    rules: PER_RUOLO,
  });

  assert.equal(result.activeRole, "P");
  assert.equal(result.callableLeft, 12);
  assert.ok(result.items.length > 0);
  const perId = new Map(remaining.map((item) => [item.id, item]));
  assert.ok(
    result.items.every((item) => perId.get(item.id).ruolo === "P"),
    "nessun attaccante durante la fase portieri",
  );
});

test("senza chiamata per ruolo la lista copre i ruoli ancora scoperti e salta quelli pieni", () => {
  const teams = [team("Mine", 500, { A: 2 })];
  const remaining = [...pool("P", 6), ...pool("A", 6)];

  const result = evaluateShortlist({
    teams,
    mine: teams[0],
    owner: 0,
    remaining,
    assigned: {},
  });

  assert.equal(result.activeRole, null);
  const perId = new Map(remaining.map((item) => [item.id, item]));
  assert.ok(
    result.items.every((item) => perId.get(item.id).ruolo === "A"),
    "i portieri sono al completo, non vanno chiamati",
  );
});

test("il tetto della lista coincide con quello del consiglio sul singolo giocatore", () => {
  // Se i due numeri divergessero, lo strumento si contraddirebbe: la lista dice 30 e
  // aprendo lo stesso nome ne comparirebbe un altro.
  const teams = [
    team("Mine", 500, { P: 3, D: 8, C: 8, A: 6 }),
    team("Rivale", 500, { P: 3, D: 8, C: 8, A: 6 }),
  ];
  const remaining = [...pool("P", 12), ...pool("D", 20)];
  const payload = {
    teams,
    mine: teams[0],
    owner: 0,
    remaining,
    assigned: {},
    rules: PER_RUOLO,
  };

  const lista = evaluateShortlist(payload);
  for (const voce of lista.items) {
    const candidato = remaining.find((item) => item.id === voce.id);
    const diretto = evaluateAuction({ ...payload, player: candidato });
    assert.equal(voce.maxBid, diretto.maxBid, `tetto diverso per ${candidato.nome}`);
    assert.equal(voce.idealMax, diretto.idealMax);
  }
});

test("la lista e' ordinata per prezzo di mercato atteso", () => {
  const teams = [
    team("Mine", 500, { P: 3, D: 8, C: 8, A: 6 }),
    team("Rivale", 500, { P: 3, D: 8, C: 8, A: 6 }),
  ];
  const remaining = [...pool("P", 14), ...pool("C", 20)];

  const result = evaluateShortlist({
    teams,
    mine: teams[0],
    owner: 0,
    remaining,
    assigned: {},
    rules: PER_RUOLO,
  });

  const prezzi = result.items.map((item) => item.marketPrice);
  const ordinati = [...prezzi].sort((a, b) => b - a);
  assert.deepEqual(prezzi, ordinati);
});

test("chi costa piu' del tetto resta in lista invece di sparire", () => {
  // La regressione da evitare: ordinando per margine, il migliore del reparto usciva
  // dalla lista proprio perche' costoso, e all'asta non lo si vedeva piu'. Il prezzo lo
  // fa la contesa, non la stima: chiamarlo e lasciarlo andare non costa niente.
  const teams = [
    team("Mine", 40, { P: 3, D: 8, C: 8, A: 6 }),
    team("Ricca", 500, { P: 3, D: 8, C: 8, A: 6 }),
  ];
  // Un portiere molto sopra gli altri, con un budget che non lo copre.
  const stella = player("P", 14, { fvm_scaled: 400, nome: "Stella" });
  const remaining = [stella, ...pool("P", 12), ...pool("D", 20)];

  const result = evaluateShortlist({
    teams,
    mine: teams[0],
    owner: 0,
    remaining,
    assigned: {},
    rules: PER_RUOLO,
  });

  const voce = result.items.find((item) => item.id === stella.id);
  assert.ok(voce, "il piu' caro del reparto deve restare chiamabile");
  assert.ok(
    voce.maxBid < voce.marketPrice,
    `il caso serve solo se il tetto sta sotto il prezzo atteso (tetto ${voce.maxBid}, mercato ${voce.marketPrice})`,
  );
  assert.equal(result.items[0].id, stella.id, "e sta in cima, perche' l'ordine e' il prezzo");
});

test("la lista dichiara quanti ne restano fuori", () => {
  const teams = [
    team("Mine", 500, { P: 3, D: 8, C: 8, A: 6 }),
    team("Rivale", 500, { P: 3, D: 8, C: 8, A: 6 }),
  ];
  const remaining = pool("P", 40);

  const result = evaluateShortlist({
    teams,
    mine: teams[0],
    owner: 0,
    remaining,
    assigned: {},
    rules: PER_RUOLO,
  });

  assert.equal(result.callableLeft, 40);
  assert.equal(result.items.length + result.notShown, 40);
  assert.ok(result.notShown > 0, "con quaranta candidati la lista e' troncata e deve dirlo");
});
