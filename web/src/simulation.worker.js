import { normalizeRules } from "./league-rules.js";
import {
  createRoleValuation,
  projectedContribution,
  replacementLevels,
  sourceFvm,
  valueAboveReplacement,
} from "./player-valuation.js";
import { expectedDefenseModifier } from "./defense-modifier.js";
import { auctionPriceAtOrBelow } from "./auction-state.js";
import { activeNominationRole } from "./auction-nomination.js";
import { positionWeight, weightedGroupValue } from "./xi-weights.js";
const EMPTY = -1e15;

const finite = (value, fallback = 0) =>
  Number.isFinite(Number(value)) ? Number(value) : fallback;
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const rounded = (value) => Math.round(finite(value));
const playerKey = (player) =>
  player?.id == null
    ? `${player?.nome || ""}|${player?.ruolo || ""}|${player?.squadra || ""}`
    : String(player.id);

const contribution = (player, rules) => projectedContribution(player, rules.horizons?.currentLeague?.matchdayIndices);

const defenseProfile = (player) => ({
  probability: Array.isArray(player?.p_gioca_per_giornata) && player.p_gioca_per_giornata.length
    ? player.p_gioca_per_giornata.reduce((sum, value) => sum + finite(value), 0) / player.p_gioca_per_giornata.length
    : finite(player?.proiezione?.p_gioca),
  vote: Array.isArray(player?.voto_puro_mean_per_giornata) && player.voto_puro_mean_per_giornata.length
    ? player.voto_puro_mean_per_giornata.reduce((sum, value) => sum + finite(value), 0) / player.voto_puro_mean_per_giornata.length
    : finite(player?.proiezione?.voto_puro),
});

const defenseValue = (roster, rules) => {
  if (!rules.defenseModifier.enabled) return 0;
  const goalkeepers = roster.filter((item) => item.ruolo === "P").sort((a, b) => defenseProfile(b).vote - defenseProfile(a).vote);
  const defenders = roster.filter((item) => item.ruolo === "D").sort((a, b) => defenseProfile(b).vote - defenseProfile(a).vote);
  const goalkeeper = goalkeepers[0];
  if (!goalkeeper || defenders.length < rules.defenseModifier.requiredDefenders) return 0;
  return expectedDefenseModifier({
    ...rules.defenseModifier,
    goalkeeper: defenseProfile(goalkeeper),
    defenders: defenders.map(defenseProfile),
  });
};

const roleNeeds = (team, rules) =>
  Object.fromEntries(
    Object.keys(rules.rosterSlots).map((role) => [
      role,
      Math.max(
        0,
        rules.rosterSlots[role] -
        (team?.roster || []).filter((player) => player.ruolo === role).length,
      ),
    ]),
  );

const totalNeeds = (needs) => Object.keys(needs).reduce((sum, role) => sum + needs[role], 0);

const median = (values) => {
  if (!values.length) return 1;
  const sorted = values.slice().sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
};

const assignmentRecords = (data, teams) => {
  if (Array.isArray(data.history) && data.history.length) {
    return data.history.filter(
      (item) => item?.player && finite(item.price) > 0,
    );
  }
  const players = new Map();
  teams.forEach((team) =>
    (team?.roster || []).forEach((player) =>
      players.set(playerKey(player), player),
    ),
  );
  return Object.entries(data.assigned || {}).flatMap(([id, assignment]) => {
    const player = players.get(String(id));
    return player && finite(assignment?.price) > 0
      ? [{ player, owner: assignment.owner, price: finite(assignment.price) }]
      : [];
  });
};

const marketModel = (data, teams, rules, baseValueFor) => {
  const records = assignmentRecords(data, teams);
  const spentByTeam = teams.map(() => 0);
  records.forEach((record) => {
    if (
      Number.isInteger(Number(record.owner)) &&
      spentByTeam[Number(record.owner)] != null
    ) {
      spentByTeam[Number(record.owner)] += finite(record.price);
    }
  });
  const inferredStarts = teams
    .map((team, index) => finite(team?.credits) + spentByTeam[index])
    .filter(Boolean);
  const budgetScale = inferredStarts.length ? median(inferredStarts) / Number(rules.startingCredits || 1) : 1;
  const ratios = records.flatMap((record) => {
    const reference = baseValueFor(record.player) * budgetScale;
    return reference > 0
      ? [clamp(finite(record.price) / reference, 0.25, 4)]
      : [];
  });
  const observed = median(ratios);
  const inflation = 1 + ((observed - 1) * ratios.length) / (ratios.length + 8);
  const roleInflation = Object.fromEntries(
    Object.keys(rules.rosterSlots).map((role) => {
      const roleRatios = records.flatMap((record) => {
        const reference = baseValueFor(record.player) * budgetScale;
        return record.player?.ruolo === role && reference > 0
          ? [clamp(finite(record.price) / reference, 0.25, 4)]
          : [];
      });
      const roleObserved = median(roleRatios);
      const shrunk =
        inflation +
        ((roleObserved - inflation) * roleRatios.length) /
        (roleRatios.length + 5);
      return [role, shrunk];
    }),
  );
  return { records, inflation, roleInflation, budgetScale };
};

const scarcityModel = (pool, teams, rules) =>
  Object.fromEntries(
    Object.keys(rules.rosterSlots).map((role) => {
      const supply = pool.filter((player) => player.ruolo === role).length;
      const demand = teams.reduce(
        (sum, team) => sum + roleNeeds(team, rules)[role],
        0,
      );
      const ratio = demand / Math.max(1, supply);
      return [
        role,
        {
          supply,
          demand,
          ratio,
          factor: clamp(0.9 + ratio * 0.35, 0.92, 1.35),
        },
      ];
    }),
  );

const opponentModel = (role, teams, ownerIndex, rules) => {
  const opponents = teams.filter((_, index) => index !== ownerIndex);
  const needing = opponents.filter((team) => roleNeeds(team, rules)[role] > 0);
  const legalMaxima = needing.map((team) => {
    const needs = roleNeeds(team, rules);
    return Math.max(
      0,
      Math.floor(finite(team.credits)) - rules.auction.reserve * (totalNeeds(needs) - 1),
    );
  });
  return {
    needing: needing.length,
    affordable: legalMaxima.filter((value) => value > 0).length,
    maxBudget: legalMaxima.length ? Math.max(...legalMaxima) : 0,
    averageBudget: legalMaxima.length
      ? legalMaxima.reduce((sum, value) => sum + value, 0) / legalMaxima.length
      : 0,
  };
};

const roleBudgetPlan = (records, ownerIndex, needs, rules) => {
  const roles = Object.keys(rules.rosterSlots);
  const targets = Object.fromEntries(
    roles.map((role) => [
      role,
      (finite(rules.startingCredits) *
        finite(rules.auction.roleBudgetPercentages[role])) /
      100,
    ]),
  );
  const spent = Object.fromEntries(roles.map((role) => [role, 0]));
  records.forEach((record) => {
    if (
      Number(record.owner) === ownerIndex &&
      spent[record.player?.ruolo] != null
    )
      spent[record.player.ruolo] += finite(record.price);
  });
  const released = roles.reduce(
    (sum, role) =>
      sum + (!needs[role] ? Math.max(0, targets[role] - spent[role]) : 0),
    0,
  );
  const openWeight = roles.reduce(
    (sum, role) =>
      sum +
      (needs[role]
        ? finite(rules.auction.roleBudgetPercentages[role])
        : 0),
    0,
  );
  return Object.fromEntries(
    roles.map((role) => {
      const redistributed =
        needs[role] && openWeight
          ? (released * finite(rules.auction.roleBudgetPercentages[role])) /
          openWeight
          : 0;
      const remaining = Math.max(0, targets[role] - spent[role]) + redistributed;
      const softRemaining =
        remaining *
        (1 + finite(rules.auction.roleBudgetFlexibilityPercent) / 100);
      return [
        role,
        {
          target: targets[role],
          spent: spent[role],
          remaining,
          bidCap: Math.max(
            0,
            Math.floor(
              softRemaining -
              Math.max(0, needs[role] - 1) * rules.auction.reserve,
            ),
          ),
        },
      ];
    }),
  );
};

const estimatedCost = (
  player,
  market,
  scarcity,
  baseValueFor,
  competition = null,
) => {
  const role = player?.ruolo;
  const base = Math.max(1, baseValueFor(player) * market.budgetScale);
  const roleMarket = finite(market.roleInflation[role], market.inflation);
  const pressure = competition
    ? 1 + Math.min(0.12, competition.affordable * 0.012)
    : 1;
  return Math.max(
    1,
    rounded(base * roleMarket * finite(scarcity[role]?.factor, 1) * pressure),
  );
};

// Returns the best exact-count value for every budget. Descending loops ensure
// each available player can be selected only once.
//
// I candidati si scorrono in ordine di valore decrescente: cosi' chi entra come
// `selected`-esimo acquisto e' davvero il `selected`-esimo migliore fra quelli comprati,
// e gli spetta il peso posizionale di quella posizione. `ownedValues` sono i giocatori
// del ruolo gia' in rosa, che occupano le posizioni davanti a lui.
const roleFrontier = (players, count, budget, costFor, valueFor, role, ownedValues = []) => {
  const dp = Array.from({ length: count + 1 }, () => {
    const row = new Float64Array(budget + 1);
    row.fill(EMPTY);
    return row;
  });
  dp[0].fill(0);
  const ordered = [...players].sort((a, b) => valueFor(b) - valueFor(a));
  for (const player of ordered) {
    const cost = costFor(player);
    if (cost > budget) continue;
    const raw = valueFor(player);
    const ownedAbove = ownedValues.reduce(
      (total, value) => total + (value > raw ? 1 : 0),
      0,
    );
    for (let selected = count; selected >= 1; selected--) {
      // I pesi posizionali restano calcolati (config/pesi_xi.json, tools/pesi_xi.py) ma
      // NON entrano piu' nel valore: in backtest su 240 aste costano 77.8 +- 26.1 punti
      // stagione (t=-2.98). Il mercato prezza gia' il fatto che la panchina rende meno.
      const value = raw;
      const current = dp[selected];
      const previous = dp[selected - 1];
      for (let credits = budget; credits >= cost; credits--) {
        if (previous[credits - cost] > EMPTY / 2) {
          current[credits] = Math.max(
            current[credits],
            previous[credits - cost] + value,
          );
        }
      }
    }
  }
  const result = dp[count];
  for (let credits = 1; credits <= budget; credits++) {
    result[credits] = Math.max(result[credits], result[credits - 1]);
  }
  return result;
};

const completionFrontier = (pool, needs, budget, costFor, valueFor, owned = {}) => {
  let combined = new Float64Array(budget + 1);
  combined.fill(0);
  for (const role of Object.keys(needs)) {
    if (!needs[role]) continue;
    const rolePlayers = pool.filter((player) => player.ruolo === role);
    const roleValues = roleFrontier(
      rolePlayers,
      needs[role],
      budget,
      costFor,
      valueFor,
      role,
      owned[role] || [],
    );
    const next = new Float64Array(budget + 1);
    next.fill(EMPTY);
    for (let credits = 0; credits <= budget; credits++) {
      for (let roleBudget = 0; roleBudget <= credits; roleBudget++) {
        if (
          combined[credits - roleBudget] > EMPTY / 2 &&
          roleValues[roleBudget] > EMPTY / 2
        ) {
          next[credits] = Math.max(
            next[credits],
            combined[credits - roleBudget] + roleValues[roleBudget],
          );
        }
      }
    }
    combined = next;
  }
  for (let credits = 1; credits <= budget; credits++) {
    combined[credits] = Math.max(combined[credits], combined[credits - 1]);
  }
  return combined;
};

const invalidResult = (ownerIndex, team, legalMax, reason, needs) => ({
  kind: "candidate",
  recommendation: "INELIGIBLE",
  idealMin: 0,
  idealMax: 0,
  maxBid: 0,
  legalMax,
  confidence: 1,
  utility: "Acquisto non consentito",
  simulations: 0,
  reasons: [reason],
  risks: [],
  alternatives: [],
  rolePlan: {},
  summary: {
    owner: ownerIndex,
    ownerName: team?.name || `Squadra ${ownerIndex + 1}`,
    credits: finite(team?.credits),
    rosterSize: team?.roster?.length || 0,
    slotsOpen: totalNeeds(needs),
    deterministic: true,
  },
});

export const evaluateOverview = (data = {}) => {
  const rules = normalizeRules(data.rules);
  const roles = Object.keys(rules.rosterSlots);
  const teams = Array.isArray(data.teams) ? data.teams : [];
  const requestedOwner = Number(data.owner);
  const mineIndex = teams.indexOf(data.mine);
  const ownerIndex =
    Number.isInteger(requestedOwner) &&
      requestedOwner >= 0 &&
      requestedOwner < teams.length
      ? requestedOwner
      : mineIndex >= 0
        ? mineIndex
        : 0;
  const team = teams[ownerIndex] || data.mine || { credits: 0, roster: [] };
  const pool = Array.isArray(data.remaining) ? data.remaining : [];
  const needs = roleNeeds(team, rules);
  const slotsOpen = totalNeeds(needs);
  const credits = Math.max(0, Math.floor(finite(team.credits)));
  const reservedCredits = Math.min(credits, slotsOpen * rules.auction.reserve);
  const spendableCredits = Math.max(0, credits - reservedCredits);
  const records = assignmentRecords(data, teams);
  const valuation = createRoleValuation(
    [...pool, ...records.map((record) => record.player)],
    rules,
  );
  const market = marketModel(data, teams, rules, valuation.normalizedFvm);
  const scarcity = scarcityModel(pool, teams, rules);
  const costFor = (item) =>
    estimatedCost(item, market, scarcity, valuation.normalizedFvm);
  const budgetPlan = roleBudgetPlan(records, ownerIndex, needs, rules);
  const valueFor = (player) => contribution(player, rules);

  const plans = Object.fromEntries(
    roles.map((role) => {
      const available = pool.filter((item) => item.ruolo === role);
      const planned = available
        .map((item) => ({ value: valueFor(item), cost: costFor(item) }))
        .sort((a, b) => b.value - a.value || a.cost - b.cost)
        .slice(0, needs[role]);
      return [
        role,
        {
          open: needs[role],
          owned: rules.rosterSlots[role] - needs[role],
          available: available.length,
          leagueDemand: scarcity[role].demand,
          scarcity: Number(scarcity[role].ratio.toFixed(3)),
          estimatedSpend: planned.reduce((sum, item) => sum + item.cost, 0),
          budgetTarget: rounded(budgetPlan[role].target),
          budgetSpent: rounded(budgetPlan[role].spent),
          budgetRemaining: rounded(budgetPlan[role].remaining),
        },
      ];
    }),
  );

  // Con chiamata per ruolo il reparto in fase e' l'unico su cui si puo' offrire adesso:
  // metterlo in cima non e' cosmetica, e' l'unica riga che descrive una mossa possibile.
  const activeRole = activeNominationRole(teams, rules);

  const priorities = roles.map((role, index) => {
    const plan = plans[role];
    const callable = !activeRole || role === activeRole;
    if (!plan.open) {
      return {
        role,
        urgency: "COMPLETO",
        reason: "Reparto completo: nessuno slot da coprire.",
        score: -1,
        index,
        callable,
      };
    }
    const shortage = plan.available < plan.open;
    const fillShare = plan.open / rules.rosterSlots[role];
    const score = plan.scarcity * 2 + fillShare + (shortage ? 3 : 0);
    const urgency =
      shortage || plan.scarcity >= 1
        ? "ALTA"
        : plan.scarcity >= 0.5 || fillShare >= 0.5
          ? "MEDIA"
          : "BASSA";
    // Due fatti, non un consiglio generico: quanta offerta resta contro la domanda che
    // la lega deve ancora coprire, e quanti crediti restano per slot. Il primo dice se
    // si puo' aspettare, il secondo quanto si puo' spendere senza restare scoperti.
    const perSlot = Math.floor(plan.budgetRemaining / Math.max(1, plan.open));
    const reason = shortage
      ? `Solo ${plan.available} liberi per i tuoi ${plan.open} slot: il ruolo non basta piu' a completare la rosa.`
      : `${plan.available} liberi per ${plan.leagueDemand} slot ancora aperti in lega. `
        + `Hai ${plan.budgetRemaining} crediti su ${plan.open} posti, ${perSlot} a testa.`;
    return { role, urgency, reason, score, index, callable };
  })
    .sort(
      (a, b) =>
        Number(b.callable) - Number(a.callable) ||
        b.score - a.score ||
        a.index - b.index,
    )
    .map(({ role, urgency, reason, callable }) => ({ role, urgency, reason, callable }));

  return {
    kind: "overview",
    priorities,
    rolePlan: plans,
    summary: {
      owner: ownerIndex,
      ownerName: team.name || `Squadra ${ownerIndex + 1}`,
      credits,
      reservedCredits,
      spendableCredits,
      marketInflation: Number(market.inflation.toFixed(3)),
      slotsOpen,
      activeRole,
      deterministic: true,
    },
  };
};

export const evaluateAuction = (data = {}) => {
  const rules = normalizeRules(data.rules);
  const roles = Object.keys(rules.rosterSlots);
  const teams = Array.isArray(data.teams) ? data.teams : [];
  const requestedOwner = Number(data.owner);
  const mineIndex = teams.indexOf(data.mine);
  const ownerIndex =
    Number.isInteger(requestedOwner) &&
      requestedOwner >= 0 &&
      requestedOwner < teams.length
      ? requestedOwner
      : mineIndex >= 0
        ? mineIndex
        : 0;
  const team = teams[ownerIndex] || data.mine || { credits: 0, roster: [] };
  const player = data.player;
  const needs = roleNeeds(team, rules);
  const openSlots = totalNeeds(needs);
  const credits = Math.max(0, Math.floor(finite(team.credits)));
  const legalMax =
    auctionPriceAtOrBelow(
      Math.max(
        0,
        credits - Math.max(0, openSlots - 1) * rules.auction.reserve,
      ),
      rules,
    ) ?? 0;

  if (!player || !roles.includes(player.ruolo)) {
    return invalidResult(
      ownerIndex,
      team,
      legalMax,
      "Giocatore o ruolo non valido.",
      needs,
    );
  }
  if (needs[player.ruolo] < 1) {
    return invalidResult(
      ownerIndex,
      team,
      0,
      `Nessuno slot ${player.ruolo} disponibile.`,
      needs,
    );
  }
  if (legalMax < rules.auction.minPrice) {
    return invalidResult(
      ownerIndex,
      team,
      0,
      "Crediti insufficienti dopo la riserva di un credito per slot.",
      needs,
    );
  }

  const candidateKey = playerKey(player);
  // The auctioned player must not also be available as his own replacement.
  const pool = (Array.isArray(data.remaining) ? data.remaining : []).filter(
    (item) => playerKey(item) !== candidateKey,
  );
  const records = assignmentRecords(data, teams);
  const valuation = createRoleValuation(
    [player, ...pool, ...records.map((record) => record.player)],
    rules,
  );
  const market = marketModel(data, teams, rules, valuation.normalizedFvm);
  const scarcity = scarcityModel(pool, teams, rules);
  const competition = Object.fromEntries(
    roles.map((role) => [role, opponentModel(role, teams, ownerIndex, rules)]),
  );
  const leagueCreditsLeft = teams.reduce(
    (sum, item) => sum + Math.max(0, Math.floor(finite(item?.credits))),
    0,
  );
  const leagueSlotsLeft = teams.reduce(
    (sum, item) => sum + totalNeeds(roleNeeds(item, rules)),
    0,
  );
  const discretionaryCredits = Math.max(
    0,
    leagueCreditsLeft - leagueSlotsLeft * rules.auction.reserve,
  );
  // I crediti sopra la riserva comprano soltanto il valore SOPRA il rimpiazzo: sotto quel
  // livello ogni giocatore costa il minimo e vale uguale. Il surplus totale ancora in
  // palio e' quindi il denominatore corretto, e per costruzione la somma dei prezzi cosi'
  // ottenuti eguaglia i crediti ancora spendibili nella lega.
  // Il valore di un giocatore e' quanto rende IN PIU' di chi giocherebbe al posto suo,
  // non il totale dei suoi punti: nelle giornate in cui non c'e', la squadra non prende
  // zero, schiera il sostituto. Senza questa correzione un giocatore da fantavoto altis-
  // simo che salta partite finisce dietro a un titolare mediocre, e il modello sbaglia
  // esattamente sui big.
  // Contributo additivo, non piu' il valore sopra rimpiazzo: quest'ultimo perde contro
  // il mercato di 257 +- 126 punti stagione (t=-2.03). Il ragionamento regge (quando un
  // giocatore salta la giornata schieri il sostituto, non prendi zero) ma il prezzo di
  // mercato lo incorpora gia', e applicarlo una seconda volta sposta le scelte verso
  // profili sbagliati: a parita' di prezzo chi ha fantamedia alta gioca MENO
  // (coefficiente -0.209, t=-6.0 su 1564 osservazioni).
  const valueFor = (item) => contribution(item, rules);
  const perTeamShare = Math.max(1, Number(rules.participants) || 1);
  // Posizione di ogni giocatore dentro il proprio ruolo nel pool residuo: serve sia al
  // prezzo del modello sia al denominatore, e va calcolata una volta sola.
  const roleRanks = Object.fromEntries(
    roles.map((role) => [
      role,
      new Map(
        pool
          .filter((item) => item.ruolo === role)
          .sort((a, b) => valueFor(b) - valueFor(a))
          .map((item, index) => [playerKey(item), index]),
      ),
    ]),
  );
  const roleSurplus = Object.fromEntries(
    roles.map((role) => {
      const demand = scarcity[role]?.demand || 0;
      const ranked = pool
        .filter((item) => item.ruolo === role)
        .map(valueFor)
        .sort((a, b) => b - a);
      if (!demand || !ranked.length) return [role, { level: 0, total: 0 }];
      const level = ranked[Math.min(demand, ranked.length) - 1];
      // Ogni giocatore sorteggiato occupa nella sua rosa la posizione floor(i/squadre),
      // quindi il suo surplus va pesato con quel peso posizionale: cosi' il denominatore
      // e' omogeneo al numeratore e la somma dei prezzi torna al budget della lega.
      return [
        role,
        {
          level,
          total: ranked
            .slice(0, demand)
            .reduce(
              (sum, value, index) =>
                sum +
                positionWeight(role, Math.floor(index / perTeamShare)) *
                Math.max(0, value - level),
              0,
            ),
        },
      ];
    }),
  );
  const draftableSurplus = roles.reduce(
    (sum, role) => sum + roleSurplus[role].total,
    0,
  );
  const creditsPerValue =
    draftableSurplus > 0 ? discretionaryCredits / draftableSurplus : 0;
  // Prezzo equo del modello: quota del budget discrezionale proporzionale al surplus.
  const modelPrice = (item) => {
    const role = item?.ruolo;
    const level = finite(roleSurplus[role]?.level);
    const rank = (roleRanks[role] || new Map()).get(playerKey(item)) ?? 0;
    const weight = positionWeight(role, Math.floor(rank / perTeamShare));
    return Math.max(
      rules.auction.minPrice,
      rounded(rules.auction.minPrice + weight * Math.max(0, valueFor(item) - level) * creditsPerValue),
    );
  };

  const marketBase = (item) =>
    estimatedCost(item, market, scarcity, valuation.normalizedFvm);
  const marketNormalisation = (() => {
    let expected = 0;
    for (const role of roles) {
      const demand = scarcity[role]?.demand || 0;
      if (!demand) continue;
      expected += pool
        .filter((item) => item.ruolo === role)
        .map(marketBase)
        .sort((a, b) => b - a)
        .slice(0, demand)
        .reduce((sum, value) => sum + value, 0);
    }
    return expected > 0 ? Math.max(0.2, Math.min(5, leagueCreditsLeft / expected)) : 1;
  })();
  const costFor = (item) =>
    Math.max(rules.auction.minPrice, rounded(marketBase(item) * marketNormalisation));
  const candidateCost = estimatedCost(
    player,
    market,
    scarcity,
    valuation.normalizedFvm,
    competition[player.ruolo],
  );
  const budgetPlan = roleBudgetPlan(records, ownerIndex, needs, rules);
  const roleBidCap = budgetPlan[player.ruolo].bidCap;

  const roleAlternatives = pool
    .filter((item) => item.ruolo === player.ruolo)
    .map((item) => ({
      player: item,
      value: valueFor(item),
      estimatedCost: costFor(item),
    }))
    .sort((a, b) => b.value - a.value || a.estimatedCost - b.estimatedCost);
  const scarcityInfo = scarcity[player.ruolo];
  const replacementIndex = roleAlternatives.length
    ? Math.min(roleAlternatives.length - 1, Math.max(0, scarcityInfo.demand - 1))
    : null;
  const replacement =
    replacementIndex == null ? null : roleAlternatives[replacementIndex];
  const candidateValue = valueFor(player);
  // Valore marginale sotto l'obiettivo XI: non la differenza secca col rimpiazzo, ma di
  // quanto cresce il gruppo di ruolo pesato per posizione se lo slot vuoto lo riempie il
  // candidato invece del miglior disponibile. Un ottavo difensore muove pochissimo il
  // gruppo anche se preso da solo vale tanto.
  const ownedValues = Object.fromEntries(
    roles.map((role) => [
      role,
      (team.roster || [])
        .filter((item) => item.ruolo === role)
        .map((item) => valueFor(item)),
    ]),
  );
  const roleOwned = ownedValues[player.ruolo] || [];
  // Il termine di confronto e' il livello di rimpiazzo, non il miglior disponibile: in
  // asta il migliore te lo porta via un avversario, il cutoff della domanda di lega e'
  // cio' che ti resta davvero.
  const fillerValues = Array.from(
    { length: needs[player.ruolo] },
    () => finite(replacement?.value),
  );
  const individualMarginalValue =
    weightedGroupValue(
      [...roleOwned, candidateValue, ...fillerValues.slice(0, Math.max(0, needs[player.ruolo] - 1))],
      player.ruolo,
    ) - weightedGroupValue([...roleOwned, ...fillerValues], player.ruolo);
  // Posizione che il candidato occuperebbe nella rosa FINALE del suo ruolo, non solo
  // rispetto a chi c'e' gia': a inizio asta la rosa e' vuota e conterebbero tutti come
  // primi del ruolo. Agli slot ancora aperti si assegnano i migliori disponibili, quindi
  // davanti a lui finiscono anche quelli che comprera' dopo.
  const betterInPool = roleAlternatives.reduce(
    (total, item) => total + (item.value > candidateValue ? 1 : 0),
    0,
  );
  // Dei giocatori migliori di lui rimasti nel pool non ne prendo io la totalita': si
  // spartiscono fra tutte le squadre, quindi davanti a me ne finisce circa un
  // partecipante su `participants`. E' la stessa regola usata nel denominatore del
  // prezzo equo, cosi' numeratore e denominatore restano omogenei.
  const participants = Math.max(1, Number(rules.participants) || 1);
  const candidatePosition =
    roleOwned.reduce((total, value) => total + (value > candidateValue ? 1 : 0), 0) +
    Math.min(
      Math.max(0, needs[player.ruolo] - 1),
      Math.floor(betterInPool / participants),
    );
  const candidateWeight = positionWeight(player.ruolo, candidatePosition);
  const currentDefenseValue = defenseValue(team.roster || [], rules);
  const candidateDefenseValue = defenseValue([...(team.roster || []), player], rules);
  const alternativeDefenseValue = replacement
    ? defenseValue([...(team.roster || []), replacement.player], rules)
    : currentDefenseValue;
  const defenseMarginalValue = candidateDefenseValue - alternativeDefenseValue;
  const marginalValue = individualMarginalValue + defenseMarginalValue;
  const opponents = competition[player.ruolo];
  const qualityEdge = replacement
    ? marginalValue / Math.max(1, candidateValue, replacement.value)
    : 0.625;
  const qualityMultiplier = clamp(1 + qualityEdge * 0.4, 0.75, 1.25);
  const rawValueCap = rounded(candidateCost * qualityMultiplier);
  const valueCap =
    rawValueCap < rules.auction.minPrice
      ? 0
      : rules.auction.minPrice +
      Math.floor(
        (rawValueCap - rules.auction.minPrice) / rules.auction.increment,
      ) *
      rules.auction.increment;

  const baseline = completionFrontier(pool, needs, credits, costFor, valueFor, ownedValues);
  const withNeeds = { ...needs, [player.ruolo]: needs[player.ruolo] - 1 };
  // Con il candidato in rosa il suo valore entra fra i posseduti del ruolo: gli slot
  // che restano da riempire partono dalla posizione successiva.
  const ownedWithCandidate = {
    ...ownedValues,
    [player.ruolo]: [...(ownedValues[player.ruolo] || []), candidateValue],
  };
  const withCandidate = completionFrontier(pool, withNeeds, credits, costFor, valueFor, ownedWithCandidate);
  const baselineValue = baseline[credits];
  const baselineFeasible = baselineValue > EMPTY / 2;
  // Due grandezze distinte, entrambe monotone nel prezzo perche' le frontiere sono non
  // decrescenti nel budget.
  //   feasibilityMax   prezzo massimo che lascia ancora completabile la rosa;
  //   indifferencePrice prezzo oltre il quale la rosa migliore completabile SENZA il
  //                     candidato vale piu' di quella che lo include.
  // Il secondo non e' un tetto: il suo termine di confronto e' la rosa teoricamente
  // ottima ai prezzi stimati, irraggiungibile in un'asta vera, quindi vale zero per
  // chiunque non entri nei 25 ideali. Serve come segnale "e' nel mio piano", e alza la
  // disponibilita' a pagare sopra il prezzo equo quando il giocatore e' davvero centrale.
  // Le frontiere sono pesate per posizione: il termine del candidato deve esserlo
  // altrettanto, altrimenti si confronta un valore grezzo con una somma pesata e ogni
  // riserva sembra indispensabile.
  const candidateTotalValue = candidateValue + defenseMarginalValue;
  let feasibilityMax = 0;
  let indifferencePrice = 0;
  let stillIndifferent = true;
  for (
    let bid = rules.auction.minPrice;
    bid <= legalMax;
    bid += rules.auction.increment
  ) {
    const completion = withCandidate[credits - bid];
    if (completion <= EMPTY / 2) break;
    feasibilityMax = bid;
    if (
      stillIndifferent &&
      baselineFeasible &&
      candidateTotalValue + completion < baselineValue
    ) {
      stillIndifferent = false;
    }
    if (stillIndifferent) indifferencePrice = bid;
  }
  // Tasso di cambio della lega fra valore e crediti, dall'identita' contabile: i crediti
  // ancora spendibili si distribuiranno sul valore ancora da assegnare. Serve perche' il
  // solo prezzo di indifferenza sale fino al massimo legale quando restano crediti senza
  // altri slot su cui spenderli: li' non c'e' costo opportunita', ma il prezzo resta
  // ingiusto rispetto a quanto un credito compra altrove.
  const candidateSurplus = Math.max(
    0,
    candidateTotalValue - candidateWeight * finite(roleSurplus[player.ruolo]?.level),
  );
  // Prezzo del modello: quota del budget discrezionale proporzionale al surplus pesato.
  // Per costruzione la somma dei prezzi sui giocatori ancora da assegnare eguaglia i
  // crediti ancora spendibili nella lega, quindi si adatta da solo a come sta andando
  // l'asta. Sostituisce il costo derivato dal FVM: valori e prezzi devono vivere nella
  // stessa scala, altrimenti il knapsack confronta grandezze incoerenti.
  const exchangeCap = Math.max(
    rules.auction.minPrice,
    rounded(rules.auction.minPrice + candidateSurplus * creditsPerValue),
  );

  // Disponibilita' a pagare: il prezzo equo del modello, alzato dal prezzo di indifferenza
  // quando il giocatore e' centrale nel piano rosa. Poi i vincoli duri.
  // Il tetto resta ancorato al mercato entro il moltiplicatore di qualita': staccarsene
  // peggiora in modo monotono (lambda 0 -> -101 punti, lambda 0.15 -> -482). Prezzo di
  // indifferenza e prezzo equo restano come SOFFITTI, cioe' possono solo abbassare.
  // Rete di sicurezza sul completamento rosa. Quando i giocatori rimasti nel ruolo non
  // bastano piu' a coprire gli slot scoperti, il tetto sale al massimo legale: a quel
  // punto non esiste un'alternativa e restare sotto il prezzo di mercato significa
  // finire l'asta con slot vuoti e crediti in mano.
  //
  // Misurato su 8 stagioni con avversari realistici: senza questa regola l'advisor non
  // completa la rosa nell'87% delle aste (finisce con 17-23 giocatori su 25 e fino a 76
  // crediti non spesi). Con la regola chiude primo su dieci, con probabilita' di top-3
  // del 73.8% contro il 30% del caso.
  // La soglia deve tenere conto della concorrenza. Se q squadre cercano ancora quel
  // ruolo e restano S giocatori, la quota che ci si puo' attendere e' S/q: bisogna
  // assicurarsi quando S/q scende sotto il proprio fabbisogno, cioe' S < fabbisogno x q.
  // Aspettare che S scenda sotto il fabbisogno significa accorgersene quando completare
  // e' gia' impossibile.
  const roleSupplyLeft = pool.reduce(
    (total, item) => total + (item.ruolo === player.ruolo ? 1 : 0),
    0,
  );
  const rivalsOnRole = competition[player.ruolo]?.needing || 0;
  const mustSecure = roleSupplyLeft < needs[player.ruolo] * (rivalsOnRole + 1);

  // Tetto = prezzo di mercato per il moltiplicatore di qualita', come nell'originale.
  // Il prezzo di indifferenza NON vincola: il suo termine di confronto e' la rosa ottima
  // ai prezzi stimati, irraggiungibile con nove avversari che competono, quindi e'
  // distorto verso il basso e direbbe di non comprare nessuno. Resta nel riepilogo come
  // diagnostica, insieme al prezzo equo del modello.
  const willingness = mustSecure ? legalMax : (valueCap > 0 ? valueCap : 0);
  // Quando bisogna assicurarsi lo slot, gli altri limiti vanno ignorati di proposito.
  // feasibilityMax e roleBidCap vanno a zero PROPRIO quando i candidati scarseggiano o
  // il budget di reparto e' esaurito, cioe' nel momento in cui non comprare e' fatale:
  // restituire zero li' equivale a consigliare di finire l'asta con lo slot vuoto.
  // L'unico vincolo che resta valido e' quanto si puo' legalmente pagare.
  const maxBid = mustSecure
    ? (auctionPriceAtOrBelow(legalMax, rules) ?? 0)
    : feasibilityMax < rules.auction.minPrice
      ? 0
      : auctionPriceAtOrBelow(
        Math.min(willingness, feasibilityMax, legalMax, roleBidCap),
        rules,
      ) ?? 0;

  const idealMax =
    auctionPriceAtOrBelow(
      Math.min(maxBid, Math.max(0, rounded(candidateCost * 1.05))),
      rules,
    ) ?? 0;
  const idealMin =
    idealMax > 0
      ? auctionPriceAtOrBelow(
        Math.max(
          rules.auction.minPrice,
          Math.min(
            rounded(candidateCost * 0.75),
            rounded(idealMax * 0.8),
          ),
        ),
        rules,
      )
      : 0;
  const recommendation =
    maxBid < 1
      ? "PASS"
      : maxBid >= candidateCost * 1.2
        ? "STRONG_BUY"
        : maxBid >= candidateCost * 0.9
          ? "BID"
          : "VALUE_ONLY";

  const dataCoverage = Number(
    Array.isArray(player.p_gioca_per_giornata) &&
    player.p_gioca_per_giornata.length > 0,
  );
  const historyCoverage = Math.min(1, market.records.length / 20);
  const poolCoverage = Math.min(
    1,
    scarcityInfo.supply / Math.max(1, scarcityInfo.demand),
  );
  const confidence = clamp(
    0.3 + dataCoverage * 0.18 + historyCoverage * 0.32 + poolCoverage * 0.1,
    0,
    market.records.length ? 0.9 : 0.58,
  );
  const reasons = [
    replacement
      ? `${rounded(candidateValue)} punti proiettati; margine di ${rounded(marginalValue)} sul cutoff del ruolo (${replacementIndex + 1}° tra i disponibili).`
      : `${rounded(candidateValue)} punti proiettati; nessuna alternativa disponibile nel ruolo.`,
    `Margine corretto: ${rounded(individualMarginalValue)} punti individuali + ${rounded(defenseMarginalValue)} punti modificatore difesa.`,
    `Limite ancorato al mercato a ${candidateCost} crediti, corretto per qualità relativa e fattibilità del completamento.`,
    `Completamento ottimizzato rispettando ${openSlots} slot aperti e la riserva minima di ${Math.max(0, openSlots - 1) * rules.auction.reserve} crediti dopo l'acquisto.`,
    `Mercato osservato a ${market.inflation.toFixed(2)}x (${market.records.length} assegnazioni); ruolo ${player.ruolo} a ${market.roleInflation[player.ruolo].toFixed(2)}x.`,
    `${opponents.needing} avversari hanno ancora bisogno del ruolo; ${opponents.affordable} possono offrire almeno un credito oltre le proprie riserve.`,
  ];
  const risks = [];
  valuation.outliersFor(player).forEach((outlier) => risks.push(outlier.label));
  if (!baselineFeasible)
    risks.push(
      "Il mercato residuo non consente un completamento stimato senza questo giocatore.",
    );
  if (withCandidate[credits - maxBid] <= EMPTY / 2)
    risks.push(
      "Il mercato residuo non consente un completamento stimato della rosa, anche acquistando il candidato.",
    );
  if (market.records.length < 5)
    risks.push(
      "Storico prezzi ancora limitato: la stima dell'inflazione dipende soprattutto dai valori base.",
    );
  if (scarcityInfo.supply < scarcityInfo.demand)
    risks.push(
      `Offerta insufficiente nel ruolo: ${scarcityInfo.supply} giocatori per ${scarcityInfo.demand} slot complessivi.`,
    );
  if (candidateCost > maxBid && maxBid > 0)
    risks.push(
      `Prezzo di mercato stimato (${candidateCost}) superiore alla soglia di valore (${maxBid}).`,
    );
  if (opponents.maxBudget > legalMax)
    risks.push(
      "Almeno un avversario ha una capacita di rilancio superiore al limite legale della squadra.",
    );

  const rolePlan = Object.fromEntries(
    roles.map((role) => {
      const available = pool.filter((item) => item.ruolo === role);
      const planned = available
        .map((item) => ({ value: valueFor(item), cost: costFor(item) }))
        .sort((a, b) => b.value - a.value || a.cost - b.cost)
        .slice(0, needs[role]);
      return [
        role,
        {
          owned: rules.rosterSlots[role] - needs[role],
          open: needs[role],
          available: available.length,
          leagueDemand: scarcity[role].demand,
          scarcity: Number(scarcity[role].ratio.toFixed(3)),
          estimatedSpend: planned.reduce((sum, item) => sum + item.cost, 0),
          budgetTarget: rounded(budgetPlan[role].target),
          budgetSpent: rounded(budgetPlan[role].spent),
          budgetRemaining: rounded(budgetPlan[role].remaining),
          projectedValue: rounded(
            planned.reduce((sum, item) => sum + item.value, 0),
          ),
        },
      ];
    }),
  );

  return {
    kind: "candidate",
    recommendation,
    idealMin,
    idealMax,
    maxBid,
    legalMax,
    confidence: Number(confidence.toFixed(2)),
    utility: `${rounded(marginalValue)} pts marginali`,
    simulations: 0,
    reasons,
    risks,
    alternatives: roleAlternatives.slice(0, 3).map((item) => ({
      id: item.player.id,
      name: item.player.nome,
      role: item.player.ruolo,
      projectedValue: rounded(item.value),
      estimatedCost: item.estimatedCost,
      valueGap: rounded(candidateValue - item.value),
    })),
    rolePlan,
    summary: {
      owner: ownerIndex,
      ownerName: team.name || `Squadra ${ownerIndex + 1}`,
      credits,
      rosterSize: team.roster?.length || 0,
      slotsOpen: openSlots,
      reservedCredits:
        Math.max(0, openSlots - 1) * rules.auction.reserve,
      candidateValue: rounded(candidateValue),
      individualMarginalValue: rounded(individualMarginalValue),
      defenseMarginalValue: rounded(defenseMarginalValue),
      defenseValueBefore: rounded(currentDefenseValue),
      defenseValueWithCandidate: rounded(candidateDefenseValue),
      replacementValue: rounded(replacement?.value),
      replacementRank: replacementIndex == null ? null : replacementIndex + 1,
      marginalValue: rounded(marginalValue),
      indifferencePrice,
      feasibilityMax,
      mustSecure,
      roleSupplyLeft,
      exchangeCap,
      creditsPerValue: Number(creditsPerValue.toFixed(4)),
      // Tetto ancorato al mercato: non vincola piu' l'offerta, resta per diagnosi.
      marketValueCap: valueCap,
      roleBudgetTarget: rounded(budgetPlan[player.ruolo].target),
      roleBudgetRemaining: rounded(budgetPlan[player.ruolo].remaining),
      roleBudgetCap: roleBidCap,
      sourceFvm: Number(sourceFvm(player).toFixed(2)),
      normalizedFvm: Number(valuation.normalizedFvm(player).toFixed(2)),
      outliers: valuation.outliersFor(player),
      baselineCompletionValue: baselineFeasible ? rounded(baselineValue) : null,
      completionValueAtMaxBid:
        withCandidate[credits - maxBid] > EMPTY / 2
          ? rounded(candidateValue + withCandidate[credits - maxBid])
          : null,
      estimatedMarketPrice:
        auctionPriceAtOrBelow(
          Math.max(candidateCost, rules.auction.minPrice),
          rules,
        ) ?? rules.auction.minPrice,
      marketInflation: Number(market.inflation.toFixed(3)),
      roleInflation: Number(market.roleInflation[player.ruolo].toFixed(3)),
      roleScarcity: Number(scarcityInfo.ratio.toFixed(3)),
      opponentDemand: opponents.needing,
      opponentAffordable: opponents.affordable,
      deterministic: true,
      horizon: rules.horizons.currentLeague.label,
    },
  };
};

/* Chi si puo' chiamare adesso, in ordine di quanto conviene pagarlo.
 *
 * L'ordine e' per margine, cioe' tetto d'offerta meno prezzo atteso. Ordinare per solo
 * tetto non distingue nulla: quando il budget di ruolo fa da tappo, meta' del reparto
 * finisce sullo stesso numero (misurato: sette portieri su otto a 34 con 35 crediti
 * destinati al ruolo). Il margine dice invece dove il budget ha spazio per vincere la
 * contesa senza sforare il piano, che e' la domanda del momento.
 *
 * Il margine non e' una scommessa contro il mercato: nasce da budget residuo, slot
 * scoperti e prezzi attesi, non da una pretesa di valutare meglio i giocatori.
 *
 * Si valuta un sovrainsieme dei candidati mostrati, scelto per prezzo di mercato che e'
 * gratis, e poi si riordina per tetto. Valutare tutto il pool costerebbe secondi;
 * sedici candidati costano una settantina di millisecondi a inizio asta e meno dopo,
 * perche' il pool si svuota.
 *
 * Ogni candidato passa per lo stesso `evaluateAuction` del percorso normale, con lo
 * stesso payload: il numero della lista e quello che compare cliccando il nome devono
 * coincidere, altrimenti lo strumento si contraddice davanti all'utente. */
const SHORTLIST_SHOWN = 8;
const SHORTLIST_EVALUATED = 16;

export const evaluateShortlist = (data = {}) => {
  const rules = normalizeRules(data.rules);
  const teams = Array.isArray(data.teams) ? data.teams : [];
  const mineIndex = teams.indexOf(data.mine);
  const requestedOwner = Number(data.owner);
  const ownerIndex =
    Number.isInteger(requestedOwner) &&
      requestedOwner >= 0 &&
      requestedOwner < teams.length
      ? requestedOwner
      : mineIndex >= 0
        ? mineIndex
        : 0;
  const team = teams[ownerIndex] || data.mine || { credits: 0, roster: [] };
  const pool = Array.isArray(data.remaining) ? data.remaining : [];
  const needs = roleNeeds(team, rules);
  const activeRole = activeNominationRole(teams, rules);

  // Chiamabili adesso: il ruolo in fase quando la lega chiama per ruolo, altrimenti ogni
  // ruolo con slot ancora scoperti. Un reparto gia' pieno non entra nella lista.
  const callable = pool.filter((player) =>
    activeRole ? player.ruolo === activeRole : needs[player.ruolo] > 0,
  );

  const items = [...callable]
    .sort((a, b) => sourceFvm(b) - sourceFvm(a))
    .slice(0, SHORTLIST_EVALUATED)
    .map((player) => {
      const advice = evaluateAuction({ ...data, player });
      return {
        id: player.id,
        maxBid: advice.maxBid,
        idealMax: advice.idealMax,
        recommendation: advice.recommendation,
        marketPrice: advice.summary?.estimatedMarketPrice ?? 0,
      };
    })
    .map((item) => ({ ...item, headroom: item.maxBid - item.marketPrice }))
    .sort((a, b) => b.headroom - a.headroom || b.maxBid - a.maxBid)
    .slice(0, SHORTLIST_SHOWN);

  return {
    kind: "shortlist",
    activeRole,
    callableLeft: callable.length,
    items,
  };
};

export const evaluateRequest = (data = {}) => ({
  ...(data?.mode === "overview"
    ? evaluateOverview(data)
    : data?.mode === "shortlist"
      ? evaluateShortlist(data)
      : evaluateAuction(data)),
  requestId: data?.requestId ?? null,
});

if (typeof self !== "undefined") {
  self.onmessage = ({ data }) => self.postMessage(evaluateRequest(data));
}
