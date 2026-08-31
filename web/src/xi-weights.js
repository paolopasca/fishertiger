// Pesi posizionali per l'obiettivo XI.
//
// Ogni giornata se ne schierano 11 su 25, quindi sommare i punti attesi di tutta la rosa
// sovrastima la profondita': l'ottavo difensore entra solo quando ne mancano tanti.
// Il valore vero di una rosa,
//     V(R) = somma_t E[ max_{XI legale} somma_i X_it ],
// non e' additivo. Ma ordinando i giocatori di un ruolo per valore decrescente, il
// j-esimo scelto e' sempre il j-esimo migliore, e V(R) si approssima con
//     somma_r somma_j  w_r(j) * v_(j)
// che e' additivo nella posizione e passa dentro il knapsack senza cambiarne la forma.
//
// w_r(j) = P(schierato | disponibile) per il j-esimo del ruolo. Condizionata perche' la
// disponibilita' individuale sta gia' dentro v_(j), moltiplicarla di nuovo la
// conterebbe due volte.
//
// Misurati con tools/pesi_xi.py sul dataset della lega (10 squadre, 3-8-8-6, sette
// moduli ammessi), mediando sulle dieci rose e resi non crescenti.
export const XI_WEIGHTS = {
  P: [1.0, 0.138, 0.0569],
  D: [1.0, 1.0, 1.0, 0.7652, 0.3193, 0.1421, 0.0767, 0.0631],
  C: [1.0, 1.0, 1.0, 0.9338, 0.6773, 0.5149, 0.2455, 0.1577],
  A: [1.0, 0.9983, 0.6996, 0.4183, 0.2772, 0.1649],
};

// Coda per ruoli piu' profondi di quelli misurati: l'ultimo peso noto, che e' gia'
// piccolo. Mai zero, altrimenti un giocatore diventerebbe gratis e il DP lo prenderebbe
// sempre.
export const positionWeight = (role, index) => {
  const table = XI_WEIGHTS[role];
  if (!table || !table.length) return 1;
  return index < table.length ? table[index] : table[table.length - 1];
};

/** Valore di un gruppo di ruolo sotto l'obiettivo XI: i valori vanno ordinati
 *  decrescenti e pesati per la posizione che occupano. */
export const weightedGroupValue = (values, role) =>
  [...values]
    .sort((a, b) => b - a)
    .reduce((sum, value, index) => sum + positionWeight(role, index) * value, 0);
