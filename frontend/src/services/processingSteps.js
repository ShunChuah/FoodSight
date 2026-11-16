// Stage names sent by the server, in the order they happen.
const ORDER = { understood: 1, searching: 1, comparing: 1, writing: 2 };

// The three steps for the processing card from the latest stage event ({ stage, detail }), or null before any.
export function processingSteps(event) {
  const reached = ORDER[event?.stage] ?? 0;
  const state = (index) => (index < reached ? "done" : index === reached ? "current" : "waiting");
  const detail = reached > 0 && event?.understood?.length ? event.understood.join(", ") : "";
  return [
    { key: "understand", label: reached > 0 ? "Understood your question" : "Understanding your question",
      detail, state: state(0) },
    { key: "search", label: event?.stage === "comparing" || event?.comparing
      ? "Comparing areas" : "Searching the knowledge graph", state: state(1) },
    { key: "write", label: "Writing the answer", state: state(2) },
  ];
}

// Keeps what was understood and whether areas are compared once later stages arrive.
export function nextStage(previous, event) {
  return {
    stage: event.stage,
    understood: event.stage === "understood" ? event.detail ?? [] : previous?.understood ?? [],
    comparing: event.stage === "comparing" || Boolean(previous?.comparing),
  };
}
