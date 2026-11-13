import { Pause, Play, RotateCcw, SkipBack, SkipForward, Volume2, VolumeX, X } from "lucide-react";

// The caption and controls shown while the Cinematic AI tour plays over the map.
// voice is null when the browser has no voice, so the mute button is left out.
export function CinematicBar({ scene, index, total, playing, voice, onVoice, onToggle, onReplay, onStep, onClose }) {
  const finished = index === total - 1 && !playing;
  return <div className="cinematic-bar" role="region" aria-label="Cinematic AI">
    <div className="cinematic-progress" aria-hidden="true">
      {Array.from({ length: total }, (_, step) => <i key={step} className={step < index ? "is-done" : step === index ? (playing ? (voice ? "is-speaking" : "is-playing") : "is-current") : ""} />)}
    </div>
    <div className="cinematic-body">
      <div className="cinematic-text" aria-live="polite">
        <strong>{scene.title}</strong>
        <p>{scene.caption}</p>
      </div>
      <div className="cinematic-actions">
        <span className="cinematic-count">{index + 1} / {total}</span>
        <button type="button" className="map-control" onClick={() => onStep(-1)} disabled={index === 0} aria-label="Previous step" title="Previous step"><SkipBack aria-hidden="true" /></button>
        {voice !== null && <button type="button" className="map-control" onClick={onVoice} aria-pressed={!voice}
          aria-label={voice ? "Mute the explanation" : "Turn on the explanation"} title={voice ? "Mute the explanation" : "Turn on the explanation"}>
          {voice ? <Volume2 aria-hidden="true" /> : <VolumeX aria-hidden="true" />}
        </button>}
        {finished
          ? <button type="button" className="map-control is-primary" onClick={onReplay} aria-label="Replay" title="Replay"><RotateCcw aria-hidden="true" /></button>
          : <button type="button" className="map-control is-primary" onClick={onToggle} aria-label={playing ? "Pause" : "Play"} title={playing ? "Pause" : "Play"}>
            {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
          </button>}
        <button type="button" className="map-control" onClick={() => onStep(1)} disabled={index === total - 1} aria-label="Next step" title="Next step"><SkipForward aria-hidden="true" /></button>
        <button type="button" className="map-control" onClick={onClose} aria-label="End the tour" title="End the tour"><X aria-hidden="true" /></button>
      </div>
    </div>
  </div>;
}
