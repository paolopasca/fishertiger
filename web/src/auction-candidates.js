/** Chi proporre nel riquadro dell'asta.
 *
 *  Con il campo di ricerca vuoto la schermata non mostrava nulla: chiedeva due lettere.
 *  Ma quando tocca a te chiamare non hai un nome in testa, e passare al Listone e tornare
 *  indietro e' attrito che in asta non ti puoi permettere. Qui, a campo vuoto, si
 *  propongono i piu' quotati del ruolo in corso.
 *
 *  L'ordinamento e' per valore di mercato, lo stesso del Listone. Misurato: ordinare per
 *  margine del modello sul mercato da' quasi la stessa lista (fra i primi attaccanti
 *  cambia solo l'esclusione dei due che il modello considera sopravvalutati), mentre
 *  ordinare per RAPPORTO tetto/mercato premia meccanicamente i giocatori da pochi crediti
 *  e sposta la lista su gente che vale poco. Quindi il prezzo resta il criterio giusto, e
 *  il verdetto sui sopravvalutati lo da' il pannello quando li selezioni.
 */
const MAX = 8;
const MIN_QUERY = 2;

const sourceValue = (player) => {
  const original = Number(player?.fvm_original);
  if (Number.isFinite(original) && original > 0) return original;
  const scaled = Number(player?.fvm_scaled);
  return Number.isFinite(scaled) ? scaled / 0.75 : 0;
};

export const auctionCandidates = ({ players, assigned, activeRole, query }) => {
  const list = Array.isArray(players) ? players : [];
  const taken = assigned || {};
  const available = list.filter(
    (candidate) =>
      candidate &&
      !taken[String(candidate.id)] &&
      (!activeRole || candidate.ruolo === activeRole),
  );
  const needle = String(query ?? "").trim().toLowerCase();
  if (needle.length < MIN_QUERY) {
    // Nessuna ricerca in corso: si propongono i piu' quotati ancora liberi, cosi' chi
    // deve chiamare ha subito un nome senza cambiare schermata.
    return [...available]
      .sort((a, b) => sourceValue(b) - sourceValue(a))
      .slice(0, MAX);
  }
  return available
    .filter((candidate) => String(candidate.nome).toLowerCase().includes(needle))
    .slice(0, MAX);
};
