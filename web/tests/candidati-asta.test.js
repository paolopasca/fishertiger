import test from "node:test";
import assert from "node:assert/strict";
import { auctionCandidates } from "../src/auction-candidates.js";

const p = (id, nome, ruolo, fvm) => ({ id, nome, ruolo, fvm_original: fvm });
const pool = [
  p(1, "Malen", "A", 414), p(2, "Martinez L.", "A", 367), p(3, "Thuram", "A", 263),
  p(4, "Colombo", "A", 20), p(5, "Dimarco", "D", 253), p(6, "Wesley", "D", 82),
];

test("a campo vuoto propone i piu' quotati del ruolo in corso", () => {
  const out = auctionCandidates({ players: pool, assigned: {}, activeRole: "A", query: "" });
  assert.deepEqual(out.map((x) => x.nome), ["Malen", "Martinez L.", "Thuram", "Colombo"]);
});

test("non propone chi e' gia' stato assegnato", () => {
  const out = auctionCandidates({ players: pool, assigned: { "1": { owner: 2, price: 180 } },
    activeRole: "A", query: "" });
  assert.equal(out.some((x) => x.nome === "Malen"), false);
});

test("rispetta la fase di ruolo anche a campo vuoto", () => {
  const out = auctionCandidates({ players: pool, assigned: {}, activeRole: "D", query: "" });
  assert.deepEqual(out.map((x) => x.nome), ["Dimarco", "Wesley"]);
});

test("con due lettere cerca per nome, come prima", () => {
  const out = auctionCandidates({ players: pool, assigned: {}, activeRole: "A", query: "th" });
  assert.deepEqual(out.map((x) => x.nome), ["Thuram"]);
});

test("una lettera sola non e' una ricerca: resta la lista dei piu' quotati", () => {
  const out = auctionCandidates({ players: pool, assigned: {}, activeRole: "A", query: "m" });
  assert.equal(out[0].nome, "Malen");
  assert.equal(out.length, 4);
});

test("senza fase di ruolo attiva pesca da tutti i ruoli", () => {
  const out = auctionCandidates({ players: pool, assigned: {}, activeRole: null, query: "" });
  assert.equal(out[0].nome, "Malen");
  assert.equal(out[1].nome, "Martinez L.");
  assert.equal(out[2].nome, "Thuram");
  assert.equal(out[3].nome, "Dimarco");
});
