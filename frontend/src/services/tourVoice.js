// The Cinematic AI narrator. Each line is spoken by OpenAI's voice (gpt-4o-mini-tts, made and saved by the
// backend); if that fails, the browser's own voice reads it instead. The tour moves on when a line ends, and a
// line that never reports its end still moves on after a safe wait.
const STORAGE_KEY = "foodsight.tourVoice";
const MS_PER_WORD = 520;
const EXTRA_MS = 3000;
const FETCH_ALLOWANCE_MS = 15000;
const SILENT_LINE_MS = 4200;

function browserSpeech() {
  if (typeof window === "undefined" || !window.speechSynthesis || typeof window.SpeechSynthesisUtterance !== "function") return null;
  return { synthesis: window.speechSynthesis, Utterance: window.SpeechSynthesisUtterance, language: document.documentElement.lang || "en-US" };
}

export function longestLineMs(text) {
  return text.trim().split(/\s+/).length * MS_PER_WORD + EXTRA_MS;
}

export function createTourVoice({
  getEnvironment = browserSpeech,
  fetchLine = null,
  makeAudio = (url) => new Audio(url),
  audioUrl = (blob) => URL.createObjectURL(blob),
  wait = setTimeout,
  clear = clearTimeout,
} = {}) {
  let current = null;
  let cloudOff = !fetchLine;
  const lines = new Map();

  const silenceBrowser = () => {
    try {
      getEnvironment()?.synthesis.cancel();
    } catch {
      // The browser has already dropped its speech engine.
    }
  };

  const stop = () => {
    const line = current;
    current = null;
    if (!line) return;
    clear(line.timer);
    if (line.audio) {
      line.audio.onended = null;
      line.audio.onerror = null;
      line.audio.pause();
    }
    if (line.utterance) silenceBrowser();
  };

  // The saved recording of a line, fetched once; null when the cloud voice can't be used. After one failure the
  // rest of the session uses the browser voice, so a missing key or a limit never slows every line down.
  const prepare = (text) => {
    if (cloudOff || !text) return Promise.resolve(null);
    if (!lines.has(text)) {
      lines.set(text, fetchLine(text).then(audioUrl).catch(() => {
        cloudOff = true;
        lines.delete(text);
        return null;
      }));
    }
    return lines.get(text);
  };

  const speakInBrowser = (line, text, finish) => {
    const environment = getEnvironment();
    if (!environment) {
      clear(line.timer);
      line.timer = wait(finish, SILENT_LINE_MS);
      return;
    }
    try {
      const utterance = new environment.Utterance(text);
      if (environment.language) utterance.lang = environment.language;
      line.utterance = utterance; // Some browsers drop an unreferenced line before it ends.
      utterance.onend = finish;
      utterance.onerror = finish;
      environment.synthesis.cancel();
      environment.synthesis.speak(utterance);
    } catch {
      finish();
    }
  };

  const playRecording = (line, text, url, finish) => {
    const fallBack = () => {
      if (current !== line) return;
      line.audio = null;
      speakInBrowser(line, text, finish);
    };
    try {
      const audio = makeAudio(url);
      line.audio = audio;
      audio.onended = finish;
      audio.onerror = fallBack;
      silenceBrowser(); // Read aloud and the tour never talk over each other.
      const playing = audio.play();
      if (playing?.catch) playing.catch(fallBack);
    } catch {
      fallBack();
    }
  };

  // onEnd runs once, when the line finishes or fails; a line stopped by the tour itself never calls it.
  const speak = (text, onEnd) => {
    stop();
    if (!text || (cloudOff && !getEnvironment())) return false;
    const line = { timer: null, audio: null, utterance: null };
    const finish = () => {
      if (current !== line) return;
      current = null;
      clear(line.timer);
      onEnd();
    };
    current = line;
    line.timer = wait(finish, longestLineMs(text) + (cloudOff ? 0 : FETCH_ALLOWANCE_MS));
    if (cloudOff) {
      speakInBrowser(line, text, finish);
    } else {
      prepare(text).then((url) => {
        if (current !== line) return;
        if (url) playRecording(line, text, url, finish);
        else speakInBrowser(line, text, finish);
      });
    }
    return true;
  };

  return {
    speak,
    stop,
    prepare,
    isSupported: () => !cloudOff || Boolean(getEnvironment()),
    usesCloud: () => !cloudOff,
  };
}

// The narrator starts on; muting it is remembered in this browser.
export function voicePreference() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== "off";
  } catch {
    return true;
  }
}

export function saveVoicePreference(on) {
  try {
    window.localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
  } catch {
    // Private windows may block storage; the choice then lasts only for this tour.
  }
}
