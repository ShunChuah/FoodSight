import { useEffect, useId, useSyncExternalStore } from "react";
import { answerSpeech, answerToSpeechText, UNSUPPORTED_SPEECH } from "../services/answerSpeech";

export default function useAnswerSpeech(answer) {
  const answerId = useId();
  const playback = useSyncExternalStore(
    answerSpeech.subscribe, answerSpeech.getSnapshot, answerSpeech.getSnapshot,
  );
  const supported = answerSpeech.isSupported();
  const hasText = Boolean(answerToSpeechText(answer));
  const ownsPlayback = playback.answerId === answerId;

  useEffect(() => {
    const stop = () => answerSpeech.stop(answerId);
    window.addEventListener("pagehide", stop);
    return () => {
      window.removeEventListener("pagehide", stop);
      stop();
    };
  }, [answerId, answer]);

  return {
    status: ownsPlayback ? playback.status : "idle",
    notice: !supported ? UNSUPPORTED_SPEECH : ownsPlayback ? playback.error : "",
    noticeId: `${answerId}-speech-notice`,
    disabled: !supported || !hasText,
    toggle: () => answerSpeech.toggle(answerId, answer),
  };
}
