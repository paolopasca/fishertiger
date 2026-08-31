const finite = (value, fallback = 0) =>
  Number.isFinite(Number(value)) ? Number(value) : fallback;

const quantile = (sorted, fraction) => {
  if (!sorted.length) return 0;
  const position = (sorted.length - 1) * fraction;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  const weight = position - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
};

const percentile = (sorted, value) =>
  sorted.length
    ? sorted.filter((item) => item <= value).length / sorted.length
    : 0;

export const sourceFvm = (player) =>
  finite(player?.fvm_original, finite(player?.fvm_scaled) / 0.75);

export const projectedContribution = (player, matchdayIndices = null) => {
  const chances = Array.isArray(player?.p_gioca_per_giornata)
    ? player.p_gioca_per_giornata
    : [];
  const votes = Array.isArray(player?.voto_puro_mean_per_giornata)
    ? player.voto_puro_mean_per_giornata
    : [];
  const bonuses = Array.isArray(player?.bonus_atteso_per_giornata)
    ? player.bonus_atteso_per_giornata
    : [];
  if (chances.length) {
    const days = Array.isArray(matchdayIndices) && matchdayIndices.length
      ? matchdayIndices
      : chances.map((_, day) => day);
    return days.reduce(
      (sum, day) =>
        sum + finite(chances[day]) * (finite(votes[day]) + finite(bonuses[day])),
      0,
    );
  }
  const projection = player?.proiezione || {};
  return (
    (Array.isArray(matchdayIndices) && matchdayIndices.length ? matchdayIndices.length : 38) *
    finite(projection.p_gioca) *
    (finite(projection.voto_puro) + finite(projection.bonus))
  );
};

/** Media, sulle giornate, della probabilita' di prendere voto. */
const averageAvailability = (player) => {
  const chances = Array.isArray(player?.p_gioca_per_giornata)
    ? player.p_gioca_per_giornata
    : [];
  return chances.length
    ? chances.reduce((sum, value) => sum + finite(value), 0) / chances.length
    : finite(player?.proiezione?.p_gioca);
};

/** Fantavoto medio a partita, cioe' quanto porta quando gioca. */
export const perMatchValue = (player) => {
  const votes = Array.isArray(player?.voto_puro_mean_per_giornata)
    ? player.voto_puro_mean_per_giornata
    : [];
  const bonuses = Array.isArray(player?.bonus_atteso_per_giornata)
    ? player.bonus_atteso_per_giornata
    : [];
  if (!votes.length) {
    return finite(player?.proiezione?.voto_puro) + finite(player?.proiezione?.bonus);
  }
  return (
    votes.reduce((sum, value, day) => sum + finite(value) + finite(bonuses[day]), 0) /
    votes.length
  );
};

/** Quanti giocatori per ruolo scendono in campo in tutta la lega ogni giornata,
 *  ricavato dalla media dei moduli ammessi. */
export const fieldedPerRole = (rules) => {
  const formations = Array.isArray(rules?.formations) ? rules.formations : [];
  const participants = Math.max(1, Number(rules?.participants) || 1);
  if (!formations.length) return { P: participants, D: 4 * participants, C: 4 * participants, A: 2 * participants };
  const totals = formations.reduce(
    (acc, formation) => {
      const [defenders, midfielders, attackers] = Array.isArray(formation)
        ? formation
        : String(formation).split("-").map(Number);
      return {
        D: acc.D + finite(defenders),
        C: acc.C + finite(midfielders),
        A: acc.A + finite(attackers),
      };
    },
    { D: 0, C: 0, A: 0 },
  );
  return {
    P: participants,
    D: Math.round((totals.D / formations.length) * participants),
    C: Math.round((totals.C / formations.length) * participants),
    A: Math.round((totals.A / formations.length) * participants),
  };
};

/** Livello di rimpiazzo per ruolo: il fantavoto a partita del giocatore marginale fra
 *  quelli che vengono DAVVERO schierati nella lega.
 *
 *  Serve perche' sommare i punti attesi equivale a dire che nelle giornate in cui il
 *  giocatore non c'e' la squadra prende zero. Falso: schieri il sostituto. Il valore
 *  vero di un giocatore e' quanto rende in piu' di chi giocherebbe al posto suo, e
 *  questo cambia la classifica: chi ha un fantavoto altissimo ma salta partite vale
 *  molto piu' di quanto dica il totale stagionale. */
export const replacementLevels = (players, rules) => {
  const fielded = fieldedPerRole(rules);
  return Object.fromEntries(
    Object.keys(rules.rosterSlots).map((role) => {
      const starters = players
        .filter((player) => player.ruolo === role && averageAvailability(player) >= 0.5)
        .map(perMatchValue)
        .sort((a, b) => b - a);
      if (!starters.length) return [role, 0];
      const index = Math.min(fielded[role] || starters.length, starters.length) - 1;
      return [role, starters[Math.max(0, index)]];
    }),
  );
};

/** Valore stagionale sopra il livello di rimpiazzo. */
export const valueAboveReplacement = (player, level, matchdayIndices = null) => {
  const chances = Array.isArray(player?.p_gioca_per_giornata) ? player.p_gioca_per_giornata : [];
  const votes = Array.isArray(player?.voto_puro_mean_per_giornata) ? player.voto_puro_mean_per_giornata : [];
  const bonuses = Array.isArray(player?.bonus_atteso_per_giornata) ? player.bonus_atteso_per_giornata : [];
  if (!chances.length) {
    const days = Array.isArray(matchdayIndices) && matchdayIndices.length ? matchdayIndices.length : 38;
    const projection = player?.proiezione || {};
    return (
      days *
      finite(projection.p_gioca) *
      (finite(projection.voto_puro) + finite(projection.bonus) - level)
    );
  }
  const days = Array.isArray(matchdayIndices) && matchdayIndices.length
    ? matchdayIndices
    : chances.map((_, day) => day);
  return days.reduce(
    (sum, day) =>
      sum + finite(chances[day]) * (finite(votes[day]) + finite(bonuses[day]) - level),
    0,
  );
};

export const createRoleValuation = (players, rules) => {
  const roles = Object.keys(rules.rosterSlots);
  const participants = Math.max(1, Number(rules.participants) || 1);
  const unique = [...new Map(players.map((player) => [String(player.id), player])).values()];
  const models = Object.fromEntries(
    roles.map((role) => {
      const rolePlayers = unique.filter((player) => player.ruolo === role);
      const sourceValues = rolePlayers
        .map(sourceFvm)
        .filter((value) => value > 0)
        .sort((a, b) => a - b);
      const projectedValues = rolePlayers
        .map((player) => projectedContribution(player, rules.horizons?.currentLeague?.matchdayIndices))
        .sort((a, b) => a - b);
      const demand = participants * rules.rosterSlots[role];
      const pricedSupply = sourceValues.slice(-demand);
      const sourceTotal = pricedSupply.reduce((sum, value) => sum + value, 0);
      const targetPerTeam =
        finite(rules.startingCredits) *
        finite(rules.auction.roleBudgetPercentages[role]) /
        100;
      const leagueTarget = targetPerTeam * participants;
      const q1 = quantile(sourceValues, 0.25);
      const q3 = quantile(sourceValues, 0.75);
      const q95 = quantile(sourceValues, 0.95);
      return [
        role,
        {
          demand,
          targetPerTeam,
          scale: sourceTotal > 0 ? leagueTarget / sourceTotal : 1,
          sourceValues,
          projectedValues,
          q1,
          q3,
          upperFence: Math.max(q3 + 5 * (q3 - q1), q95 * 2),
        },
      ];
    }),
  );

  const normalizedFvm = (player) =>
    Math.max(1, sourceFvm(player) * finite(models[player.ruolo]?.scale, 1));
  const outliersFor = (player) => {
    const model = models[player.ruolo];
    if (!model) return [];
    const source = sourceFvm(player);
    const notices = [];
    if (source > model.upperFence && model.upperFence > 0) {
      notices.push({
        code: "source_fvm_high",
        label: "FVM fonte fuori scala nel ruolo",
      });
    }
    const projectionRank = percentile(
      model.projectedValues,
      projectedContribution(player, rules.horizons?.currentLeague?.matchdayIndices),
    );
    if (source <= model.q1 && projectionRank >= 0.8) {
      notices.push({
        code: "source_fvm_low_for_projection",
        label: "FVM fonte molto basso rispetto alla proiezione",
      });
    }
    if (source >= model.q3 && projectionRank <= 0.3) {
      notices.push({
        code: "source_fvm_high_for_projection",
        label: "FVM fonte alto rispetto alla proiezione",
      });
    }
    return notices;
  };

  return { models, normalizedFvm, outliersFor };
};
