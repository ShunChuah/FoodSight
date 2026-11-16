import { useState } from "react";
import { Eye, EyeOff, House, Info, Layers, List, LocateFixed, Map as MapIcon, Maximize2, Minimize2, Minus, Plus, Satellite, X } from "lucide-react";

function ControlButton({ label, pressed, onClick, children, busy = false }) {
  return <button type="button" className="map-control" title={label} aria-label={label} aria-pressed={pressed} aria-busy={busy || undefined} onClick={onClick}>
    {children}
  </button>;
}

export function MapControls({ state, groups, legend, locating, onZoom, onLocate, dispatch }) {
  const [panel, setPanel] = useState(null);
  const toggle = (name) => setPanel(panel === name ? null : name);
  const satellite = state.basemap === "satellite";
  return <>
    <div className="map-controls is-left">
      <div className="map-control-group">
        <ControlButton label="Zoom in" onClick={() => onZoom(1)}><Plus aria-hidden="true" /></ControlButton>
        <ControlButton label="Zoom out" onClick={() => onZoom(-1)}><Minus aria-hidden="true" /></ControlButton>
      </div>
      <ControlButton label="Back to the answer's view" onClick={() => dispatch({ type: "reset_view" })}><House aria-hidden="true" /></ControlButton>
      <ControlButton label="Show my location" onClick={onLocate} busy={locating}><LocateFixed aria-hidden="true" /></ControlButton>
    </div>
    <div className="map-controls is-right">
      <ControlButton label={state.expanded ? "Collapse map" : "Expand map"} pressed={state.expanded} onClick={() => dispatch({ type: "expand_map" })}>
        {state.expanded ? <Minimize2 aria-hidden="true" /> : <Maximize2 aria-hidden="true" />}
      </ControlButton>
      <ControlButton label={satellite ? "Show map" : "Show satellite"} pressed={satellite} onClick={() => dispatch({ type: "toggle_basemap" })}>
        {satellite ? <MapIcon aria-hidden="true" /> : <Satellite aria-hidden="true" />}
      </ControlButton>
      {groups.length > 0 && <ControlButton label="Map layers" pressed={panel === "layers"} onClick={() => toggle("layers")}><Layers aria-hidden="true" /></ControlButton>}
      {legend.length > 0 && <ControlButton label="Legend" pressed={panel === "legend"} onClick={() => toggle("legend")}><List aria-hidden="true" /></ControlButton>}
      {panel === "layers" && <div className="map-popover" role="group" aria-label="Map layers">
        <p className="map-popover-title">Map layers</p>
        {groups.map((group) => {
          const visible = state.visible[group.id] !== false;
          return <button key={group.id} type="button" className="map-layer-toggle" aria-pressed={visible}
            onClick={() => dispatch({ type: "toggle_overlay", overlay: group.id })}>
            {visible ? <Eye aria-hidden="true" /> : <EyeOff aria-hidden="true" />}{group.label}
          </button>;
        })}
      </div>}
      {panel === "legend" && <div className="map-popover" role="group" aria-label="Legend">
        <p className="map-popover-title">Legend</p>
        {legend.map((entry) => <p key={entry.id} className="map-legend-row"><i style={{ background: entry.color }} />{entry.label}</p>)}
      </div>}
    </div>
  </>;
}

export function InfoCard({ info, onClose }) {
  return <div className={`map-info-card${info.y < 170 ? " is-below" : ""}`} style={{ left: info.x, top: info.y }} role="dialog" aria-label={info.title}>
    <div className="map-info-head">
      <strong>{info.title}</strong>
      <button type="button" className="map-close" onClick={onClose} aria-label="Close"><X aria-hidden="true" /></button>
    </div>
    {info.facts.map(([label, value]) => <p key={label}><span>{label}</span>{value}</p>)}
  </div>;
}

// Esri's terms allow the credits behind a clearly marked button, with "Esri" linking to esri.com.
export function MapCredits({ credits }) {
  const [open, setOpen] = useState(false);
  return <div className="map-credits">
    {open ? <p className="map-credits-pill">
      <button type="button" onClick={() => setOpen(false)} aria-label="Hide map credits"><X aria-hidden="true" /></button>
      {credits && <span>© {credits}</span>}
      <span>Powered by <a href="https://www.esri.com" target="_blank" rel="noopener noreferrer">Esri</a></span>
    </p> : <button type="button" className="map-control is-small" onClick={() => setOpen(true)} aria-label="Map credits" title="Map credits"><Info aria-hidden="true" /></button>}
  </div>;
}
