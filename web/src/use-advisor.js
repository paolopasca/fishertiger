import { useEffect, useMemo, useRef, useState } from "react";
import { playerIdKey } from "./auction-state.js";
import { createRequestGate } from "./latest-request.js";

const withPlayers = (history, players) =>
  (history || []).flatMap((transaction) => {
    const bought = (players || []).find(
      (candidate) => playerIdKey(candidate.id) === playerIdKey(transaction.playerId),
    );
    return bought ? [{ ...transaction, player: bought }] : [];
  });


export const useAdvisor = ({
  player,
  board,
  players,
  rules,
  overview = false,
  shortlist = false,
}) => {
  const [advice, setAdvice] = useState(null);
  const [squadPlan, setSquadPlan] = useState(null);
  const [callList, setCallList] = useState(null);
  const [failure, setFailure] = useState("");
  const worker = useRef(null);
  const adviceGate = useRef(null);
  const overviewGate = useRef(null);
  const shortlistGate = useRef(null);
  if (!adviceGate.current) adviceGate.current = createRequestGate();
  if (!overviewGate.current) overviewGate.current = createRequestGate();
  if (!shortlistGate.current) shortlistGate.current = createRequestGate();

  const rulesSignature = JSON.stringify(rules);
  const boardSignature = board
    ? JSON.stringify([
      board.assigned,
      board.teams.map((team) => [team.name, team.credits]),
      board.userTeamIndex,
    ])
    : "";
  const playerId = player ? playerIdKey(player.id) : "";

  const payload = useMemo(
    () =>
      board
        ? {
          owner: board.userTeamIndex,
          mine: board.teams[board.userTeamIndex],
          teams: board.teams,
          remaining: (players || []).filter(
            (candidate) => !board.assigned[playerIdKey(candidate.id)],
          ),
          assigned: board.assigned,
          history: withPlayers(board.history, players),
          rules,
        }
        : null,
    [boardSignature, rulesSignature, players],
  );

  useEffect(
    () => () => {
      worker.current?.terminate();
      worker.current = null;
    },
    [],
  );

  const send = (message) => {
    if (!worker.current) {
      try {
        worker.current = new Worker(
          new URL("./simulation.worker.js", import.meta.url),
          { type: "module" },
        );
      } catch {
        setFailure("Consigli non disponibili: worker non avviato.");
        return false;
      }
      setFailure("");
      worker.current.onmessage = (event) => {
        const answer = event.data;
        if (answer?.kind === "overview") {
          if (overviewGate.current.isCurrent(answer.requestId))
            setSquadPlan(answer);
        } else if (answer?.kind === "shortlist") {
          if (shortlistGate.current.isCurrent(answer.requestId))
            setCallList(answer);
        } else if (adviceGate.current.isCurrent(answer?.requestId)) {
          setAdvice(answer);
        }
      };
      worker.current.onerror = () =>
        setFailure("Il calcolo del consiglio non è riuscito.");
    }
    worker.current.postMessage(message);
    return true;
  };

  useEffect(() => {
    if (!payload || !player) {
      adviceGate.current.claim();
      setAdvice(null);
      return;
    }
    setAdvice(null);
    send({ ...payload, player, requestId: adviceGate.current.claim() });
  }, [playerId, payload]);

  useEffect(() => {
    if (!overview || !payload) return;
    send({
      ...payload,
      mode: "overview",
      requestId: overviewGate.current.claim(),
    });
  }, [overview, payload]);

  /* La lista si chiede solo a campo vuoto. Il worker e' uno solo: se girasse anche
     mentre l'utente sta valutando un nome, il consiglio che sta aspettando finirebbe
     in coda dietro una decina di knapsack. */
  useEffect(() => {
    if (!shortlist || !payload || player) return;
    send({
      ...payload,
      mode: "shortlist",
      requestId: shortlistGate.current.claim(),
    });
  }, [shortlist, payload, playerId]);

  return { advice, squadPlan, callList, failure };
};
