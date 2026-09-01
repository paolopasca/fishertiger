/** Cosa resta per gli slot ancora scoperti dopo aver pagato un certo prezzo.
 *
 *  Perche' esiste. La fascia ideale e il tetto sono larghi, e dove ci si colloca dentro
 *  quella larghezza cambia moltissimo la rosa che resta. Misurato su uno stato tipico di
 *  fase attaccanti (195 crediti, 6 slot da riempire): pagando 152 per il primo restano
 *  8.6 crediti a testa per gli altri cinque, pagando 190 ne resta 1. Un fattore nove,
 *  tutto dentro l'intervallo che l'interfaccia colora di verde.
 *
 *  Il calcolo e' banale e i numeri sono gia' a schermo, ma nessuno lo fa mentre un
 *  avversario rilancia. Non cambia nessuna raccomandazione: rende visibile un vincolo.
 *
 *  Sta in un modulo .js e non dentro il componente perche' il test runner di Node non
 *  importa .jsx, ed e' la convenzione della repo: logica pura nei .js, presentazione nei
 *  .jsx.
 */
export const residualPerSlot = ({ advice, price, rules }) => {
  const credits = Number(advice?.summary?.credits);
  const open = Number(advice?.summary?.slotsOpen);
  const value = Number(price);
  const minPrice = Number(rules?.auction?.minPrice ?? 1);
  if (!Number.isFinite(credits) || !Number.isFinite(value) || !(open > 1)) return null;
  if (price === "" || price == null) return null;
  const remaining = Math.max(0, credits - value);
  const others = open - 1;
  return {
    remaining,
    others,
    each: remaining / others,
    // Sotto il prezzo minimo per slot la rosa non si completa nemmeno: e' il segnale
    // piu' netto che si sta pagando troppo.
    broke: remaining < others * minPrice,
  };
};
