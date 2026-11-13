const WAIT_DELAYS_MS = [300, 700, 1500];
const REPEAT_DELAY_MS = 3000;
const MAX_WAIT_MS = 150000;

export function pendingGraphs(chats) {
  return (chats ?? []).flatMap((chat) => (chat.messages ?? [])
    .filter((message) => message.type === "assistant" && message.graphStatus === "pending")
    .map((message) => ({ chatId: chat.id, messageId: message.id })));
}

export function withGraphEvidence(chats, chatId, messageId, { graphStatus = null, graphData = null }) {
  return chats.map((chat) => chat.id !== chatId ? chat : {
    ...chat,
    messages: chat.messages.map((message) => message.id !== messageId ? message : {
      ...message, graphStatus, graphData,
    }),
  });
}

const wait = (ms, signal) => new Promise((resolve) => {
  const timer = setTimeout(resolve, ms);
  signal?.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
});

export async function waitForGraph(fetchGraph, { signal, sleep = wait } = {}) {
  let waited = 0;
  for (let attempt = 0; waited < MAX_WAIT_MS; attempt += 1) {
    const delay = WAIT_DELAYS_MS[attempt] ?? REPEAT_DELAY_MS;
    await sleep(delay, signal);
    waited += delay;
    if (signal?.aborted) return null;
    try {
      const result = await fetchGraph();
      if (signal?.aborted) return null;
      if (result?.graphStatus !== "pending") return result;
    } catch {
      // A dropped request is retried at the next delay.
    }
  }
  return { graphStatus: "failed", graphData: null };
}
