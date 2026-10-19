const IDLE = Object.freeze({ answerId: null, status: "idle", error: "" });
const PLAYBACK_ERROR = "I couldn’t play this answer. Please try again.";
export const UNSUPPORTED_SPEECH = "Read aloud isn’t supported in this browser.";

export function answerToSpeechText(answer = "") {
  if (typeof answer !== "string") return "";
  return answer
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!?\[([^\]]+)\]\([^\n)]+\)/g, "$1")
    .replace(/\[R\d+\]/g, "")
    .replace(/^\s*(?:#{1,6}\s+|[-*+]\s+|>\s*)/gm, "")
    .replace(/[*_`~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

// Short utterances avoid voice-engine limits on long answers. Prefer sentence
// boundaries, then word boundaries, without dropping any words or numbers.
function speechChunks(text, maximum = 220) {
  const chunks = [];
  let remaining = text;
  while (remaining.length > maximum) {
    const candidate = remaining.slice(0, maximum + 1);
    const sentences = [...candidate.matchAll(/[.!?](?=\s)/g)];
    const sentenceEnd = sentences.at(-1)?.index;
    const wordEnd = candidate.lastIndexOf(" ");
    const end = sentenceEnd >= maximum / 3 ? sentenceEnd + 1
      : wordEnd > 0 ? wordEnd : maximum;
    chunks.push(remaining.slice(0, end).trim());
    remaining = remaining.slice(end).trim();
  }
  if (remaining) chunks.push(remaining);
  return chunks;
}

function browserSpeech() {
  if (typeof window === "undefined" || !window.speechSynthesis
      || typeof window.SpeechSynthesisUtterance !== "function") return null;
  return {
    synthesis: window.speechSynthesis,
    Utterance: window.SpeechSynthesisUtterance,
    language: document.documentElement.lang || "en-US",
  };
}

export function createAnswerSpeech(getEnvironment = browserSpeech) {
  let snapshot = IDLE;
  let active = null;
  const listeners = new Set();
  const publish = (next) => {
    snapshot = next;
    listeners.forEach((listener) => listener());
  };

  const stop = (answerId) => {
    if (answerId !== undefined && snapshot.answerId !== answerId) return;
    const previous = active;
    active = null; // Ignore cancellation events from the previous utterance.
    try {
      previous?.environment.synthesis.cancel();
    } catch {
      // Release ownership even if the browser has already torn down its engine.
    } finally {
      publish(IDLE);
    }
  };

  const fail = (session) => {
    if (active !== session) return;
    try {
      stop();
    } finally {
      publish({ answerId: session.answerId, status: "idle", error: PLAYBACK_ERROR });
    }
  };

  const speakNext = (session) => {
    if (active !== session) return;
    if (session.index === session.chunks.length) {
      active = null;
      publish(IDLE);
      return;
    }
    if (snapshot.status === "paused") return;
    try {
      const { synthesis, Utterance, language } = session.environment;
      const utterance = new Utterance(session.chunks[session.index]);
      if (language) utterance.lang = language;
      session.utterance = utterance; // Keep a strong reference until it finishes.
      const isCurrent = () => active === session && session.utterance === utterance;
      utterance.onend = () => {
        if (!isCurrent()) return;
        session.utterance = null;
        session.index += 1;
        speakNext(session);
      };
      utterance.onerror = (event) => {
        if (!isCurrent()) return;
        if (["canceled", "interrupted"].includes(event.error)) stop(session.answerId);
        else fail(session);
      };
      utterance.onpause = () => {
        if (isCurrent() && synthesis.paused) publish({ ...snapshot, status: "paused" });
      };
      utterance.onresume = () => {
        if (isCurrent() && !synthesis.paused) publish({ ...snapshot, status: "speaking" });
      };
      synthesis.speak(utterance);
    } catch {
      fail(session);
    }
  };

  return {
    getSnapshot: () => snapshot,
    isSupported: () => Boolean(getEnvironment()),
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    stop,
    toggle: (answerId, answer) => {
      if (active?.answerId === answerId) {
        const session = active;
        try {
          if (snapshot.status === "paused") {
            publish({ ...snapshot, status: "speaking" });
            session.environment.synthesis.resume();
            if (!session.utterance) speakNext(session);
          } else {
            publish({ ...snapshot, status: "paused" });
            session.environment.synthesis.pause();
          }
        } catch {
          fail(session);
        }
        return;
      }

      const text = answerToSpeechText(answer);
      if (!text) return;
      const environment = getEnvironment();
      if (!environment) {
        publish({ answerId, status: "idle", error: UNSUPPORTED_SPEECH });
        return;
      }
      stop();
      const session = { answerId, environment, chunks: speechChunks(text), index: 0, utterance: null };
      active = session;
      publish({ answerId, status: "speaking", error: "" });
      try {
        // cancel() does not necessarily clear the browser's global paused flag.
        environment.synthesis.resume();
        speakNext(session);
      } catch {
        fail(session);
      }
    },
  };
}

// Speech synthesis is shared by the document, so all response cards share one
// owner and one state. Starting a new answer resets the old card immediately.
export const answerSpeech = createAnswerSpeech();

if (import.meta.hot) import.meta.hot.dispose(() => answerSpeech.stop());
