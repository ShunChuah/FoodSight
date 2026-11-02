export async function readAnswerStream(response, onAnswer) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  const handle = (line) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "answer") onAnswer?.(event.text);
    else if (event.type === "done") result = event;
    else if (event.type === "error") throw streamError(event.status, event.detail);
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    lines.forEach(handle);
  }
  handle(buffer + decoder.decode());
  if (!result) throw streamError(500, "The answer stream ended before the answer was saved.");
  return result;
}

export function streamError(status, detail) {
  const error = new Error(typeof detail === "string" ? detail : `Chat request failed (${status})`);
  error.response = { status, data: { detail } };
  return error;
}
