// Why an answer failed (the server's failure reason), in the words shown on the failure card.
const REASONS = {
  timeout: "The answer took too long.",
  model: "The AI service didn't respond.",
  search: "The restaurant search didn't respond.",
  unexpected: "Something went wrong on our side.",
};

export function failureText(reason) {
  return `${REASONS[reason] ?? REASONS.unexpected} Your question is saved.`;
}

// Hides a failed answer and its question while Try again replaces them.
export function withoutRetried(messages, retryingId) {
  if (retryingId == null) return messages;
  const index = messages.findIndex((message) => message.id === retryingId);
  if (index < 0) return messages;
  const start = index > 0 && messages[index - 1].type === "user" ? index - 1 : index;
  return [...messages.slice(0, start), ...messages.slice(index + 1)];
}

// The question a failed answer was for, to send again.
export function questionBefore(messages, index) {
  const previous = messages[index - 1];
  return previous?.type === "user" ? previous.text : "";
}
