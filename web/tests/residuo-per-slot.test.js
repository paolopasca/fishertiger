import test from "node:test";
import assert from "node:assert/strict";
import { residualPerSlot } from "../src/residual-slots.js";

const rules = { auction: { minPrice: 1 } };
const advice = (credits, slotsOpen) => ({ summary: { credits, slotsOpen } });

test("dice quanto resta per ogni slot ancora scoperto", () => {
  // 195 crediti, 6 slot: pagando 152 restano 43 per 5, cioe' 8.6 a testa.
  const residual = residualPerSlot({ advice: advice(195, 6), price: 152, rules });
  assert.equal(residual.remaining, 43);
  assert.equal(residual.others, 5);
  assert.ok(Math.abs(residual.each - 8.6) < 0.01);
  assert.equal(residual.broke, false);
});

test("il residuo crolla dentro la stessa fascia ideale", () => {
  // E' la ragione per cui il pannello esiste: la fascia ideale 152-190 sembra
  // uniforme ma il residuo per slot passa da 8.6 a 1.0, un fattore nove.
  const basso = residualPerSlot({ advice: advice(195, 6), price: 152, rules });
  const alto = residualPerSlot({ advice: advice(195, 6), price: 190, rules });
  assert.ok(basso.each > alto.each * 8, `${basso.each} contro ${alto.each}`);
});

test("segnala quando i crediti non bastano piu' a completare", () => {
  const residual = residualPerSlot({ advice: advice(195, 6), price: 192, rules });
  assert.equal(residual.broke, true);
});

test("non si esprime sull'ultimo slot, dove non c'e' un dopo", () => {
  assert.equal(residualPerSlot({ advice: advice(195, 1), price: 100, rules }), null);
});

test("resta muto se manca il prezzo o lo stato", () => {
  assert.equal(residualPerSlot({ advice: advice(195, 6), price: "", rules }), null);
  assert.equal(residualPerSlot({ advice: {}, price: 50, rules }), null);
});
