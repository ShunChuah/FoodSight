const normalise = (text) => String(text ?? "").trim().replace(/\s+/g, " ").toLowerCase();

// The option the user tapped, read from the next message (or the one still sending); null when they typed instead.
export function chosenReply(options, answer) {
  if (!options?.length || !answer) return null;
  return options.find((option) => normalise(option) === normalise(answer)) ?? null;
}

// Replies for one assistant message: open on the latest one, kept read-only on earlier ones the user answered.
export function repliesFor(messages, index, pendingQuery = "") {
  const message = messages[index];
  const options = message?.quickReplies ?? [];
  if (!options.length) return { options: [], selected: null };
  const next = messages[index + 1];
  const answer = next?.type === "user" ? next.text : index === messages.length - 1 ? pendingQuery : "";
  const selected = chosenReply(options, answer);
  if (selected) return { options, selected };
  return index === messages.length - 1 ? { options, selected: null } : { options: [], selected: null };
}
