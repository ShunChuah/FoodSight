const normalise = (text) => String(text ?? "").trim().replace(/\s+/g, " ").toLowerCase();

// The option the user tapped, read from the next message (or the one still sending); null when they typed instead.
export function chosenReply(options, answer) {
  if (!options?.length || !answer) return null;
  return options.find((option) => normalise(option) === normalise(answer)) ?? null;
}

// Replies kept in an answer card: only once the user picked one, read-only with the choice marked.
export function repliesFor(messages, index, pendingQuery = "") {
  const message = messages[index];
  const options = message?.quickReplies ?? [];
  if (!options.length) return { options: [], selected: null };
  const next = messages[index + 1];
  const answer = next?.type === "user" ? next.text : index === messages.length - 1 ? pendingQuery : "";
  const selected = chosenReply(options, answer);
  return selected ? { options, selected } : { options: [], selected: null };
}

// The latest answer's replies while they are still open, shown above the chat input.
export function openReplies(messages, pendingQuery = "") {
  const last = messages[messages.length - 1];
  if (last?.type !== "assistant" || last.failure || !last.quickReplies?.length || pendingQuery.trim()) return [];
  return last.quickReplies;
}
