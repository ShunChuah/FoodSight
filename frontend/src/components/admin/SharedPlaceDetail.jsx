import { useMemo } from "react";
import { Check, Clock, Undo2, X } from "lucide-react";
import { GOOGLE_COLOR, OSM_COLOR, formatDateTime } from "../../services/adminFormat.js";
import AdminMap from "./AdminMap.jsx";
import { ActionButton, Badge, Card, ErrorBox, Notice, TextInput } from "./AdminUi.jsx";
import { Comparison, LetterChip, PinChoice } from "./MatchParts.jsx";

// One page for a Google place that two or more OpenStreetMap restaurants matched (reason
// shared_google_place): every restaurant and the Google place side by side. One click
// decides the whole group: the chosen restaurant gets the place and every other one goes on
// with OpenStreetMap data only (null); Neither gives every one null. No dashed circle: these
// are held because they share one place, not because of the distance. Each restaurant has a
// letter (A, B, ... in the group's order) on its button, inside its pin and in its table
// heading, so the orange buttons are told apart and each one points to its pin and column.

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const letterAt = (index) => LETTERS[index] || String(index + 1);

function DecidedBox({ members, busy, onDecide, onUndo }) {
  const letter = (m) => letterAt(members.indexOf(m));
  const chosen = members.find((m) => m.decision?.kind === "same");
  const rest = members.filter((m) => m !== chosen);
  const decision = (chosen || members[0]).decision;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {chosen
          ? <Badge tone="green"><Check className="size-[0.75rem]" /> {chosen.osm_name} is this place{decision.pin === "google" ? " · Google pin" : ""}</Badge>
          : <Badge tone="gray"><X className="size-[0.75rem]" /> Neither</Badge>}
        <span className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">
          by {decision.decided_by || "hand"}{decision.decided_at && ` on ${formatDateTime(decision.decided_at)}`}
        </span>
      </div>
      <p className="text-[0.8125rem]">
        {chosen
          ? `${rest.map((m) => m.osm_name).join(", ")} ${rest.length === 1 ? "goes" : "go"} on with OpenStreetMap data only.`
          : "Every restaurant goes on with OpenStreetMap data only."}
      </p>
      {decision.note && <p className="text-[0.8125rem]">Note: {decision.note}</p>}
      <p className="inline-flex items-center gap-1.5 text-[0.8125rem] text-amber-700 dark:text-amber-300">
        <Clock className="size-[0.875rem]" /> Waiting for tonight's update. Until then you can change or undo it.
      </p>
      <div className="flex flex-wrap gap-2">
        {rest.map((m) => (
          <ActionButton key={m.osm_id} tone="primary" disabled={busy} onClick={() => onDecide(m.osm_id)}>
            <LetterChip letter={letter(m)} onOrange /> Change to {m.osm_name}
          </ActionButton>
        ))}
        {chosen && <ActionButton disabled={busy} onClick={() => onDecide(null)}><X /> Change to neither</ActionButton>}
        <ActionButton tone="undo" disabled={busy} onClick={onUndo}><Undo2 /> Undo</ActionButton>
      </div>
    </div>
  );
}

export default function SharedPlaceDetail({ group, details, note, onNote, pin, onPin, busy, error, notice, onDecide, onUndo }) {
  const members = group.members;
  const google = details[0]?.google || {};
  const location = google.details?.location;
  const decided = members.every((m) => m.decision);

  // The pins are often only metres apart: the westernmost name goes on its pin's left, the
  // easternmost on its right (any others below), so names never overlap however close the
  // pins are; the distances go into the table headings instead of onto the lines
  const map = useMemo(() => {
    const points = [];
    const lines = [];
    const byLongitude = [...details].sort((a, b) => Number(a.osm?.longitude) - Number(b.osm?.longitude));
    details.forEach((item, index) => {
      const osmPin = { longitude: Number(item.osm?.longitude), latitude: Number(item.osm?.latitude) };
      const order = byLongitude.indexOf(item);
      const side = order === 0 ? "left" : order === byLongitude.length - 1 ? "right" : "below";
      // details are in the group's order, so index gives the same letter as the buttons
      points.push({ ...osmPin, color: OSM_COLOR, size: 19, glyph: letterAt(index), label: item.osm_name, labelSide: side });
      if (location) lines.push({ from: [osmPin.longitude, osmPin.latitude], to: [location.longitude, location.latitude] });
    });
    if (location) points.push({ longitude: location.longitude, latitude: location.latitude, color: GOOGLE_COLOR, label: "Google" });
    return { points, lines };
  }, [details, location]);

  return (
    <div className="mx-auto flex max-w-[64rem] flex-col gap-4 p-8">
      <div>
        <h2 className="text-[1.375rem] font-bold">
          {members.map((m, index) => (
            <span key={m.osm_id}>
              <span style={{ color: OSM_COLOR }}>{m.osm_name}</span>
              {index < members.length - 1 && <span className="mx-1.5 text-gray-400">·</span>}
            </span>
          ))}
          <span className="mx-2 text-gray-400">vs</span>
          <span style={{ color: GOOGLE_COLOR }}>{group.google_name}</span>
        </h2>
        <p className="mt-1 text-[0.875rem] text-gray-600 dark:text-muted-dark">
          {members.length === 2 ? "Two" : members.length} OpenStreetMap restaurants matched the same Google place. Only one of them can be it.
        </p>
      </div>
      <Notice>{notice}</Notice>
      <ErrorBox error={error} />
      <Card>
        {decided ? (
          <DecidedBox members={members} busy={busy} onDecide={onDecide} onUndo={onUndo} />
        ) : (
          <div className="flex flex-col gap-2">
            <p className="text-[0.875rem] font-semibold">Which restaurant is this Google place?</p>
            <TextInput value={note} maxLength={300} onChange={(event) => onNote(event.target.value)}
              placeholder="Note (optional): why you decided, e.g. checked the shop names on Google Maps" />
            <div className="flex flex-wrap gap-2">
              {/* The same colours as the one-restaurant page: choosing a restaurant is orange like
                  "Same place", Neither is white like "Not the same" */}
              {members.map((m, index) => (
                <ActionButton key={m.osm_id} tone="primary" disabled={busy} onClick={() => onDecide(m.osm_id)}
                  title={`${m.osm_name} gets this Google place's details, rating and reviews; the others go on with OpenStreetMap data only`}>
                  <LetterChip letter={letterAt(index)} onOrange /> {m.osm_name} is this place
                </ActionButton>
              ))}
              <ActionButton disabled={busy} onClick={() => onDecide(null)} title="Every restaurant goes on with OpenStreetMap data only">
                <X /> Neither
              </ActionButton>
            </div>
            {members.some((m) => m.pin_choice) && (
              <PinChoice pin={pin} onPin={onPin} hint="(used with the restaurant you choose, when its pins are more than 50 m apart)" />
            )}
          </div>
        )}
      </Card>
      <AdminMap {...map} satellite fitLabel="Show all pins" className="h-[20rem]" />
      <Comparison
        osmSides={details.map((item, index) => ({
          key: item.osm_id, title: item.osm_name, osm: item.osm, letter: letterAt(index),
          subtitle: `OpenStreetMap${item.distance_m != null ? ` · ${item.distance_m} m from Google's pin` : ""}`,
        }))}
        google={google}
      />
    </div>
  );
}
