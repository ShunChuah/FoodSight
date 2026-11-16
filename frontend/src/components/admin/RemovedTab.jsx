import { useEffect, useMemo, useState } from "react";
import { Clock, Undo2 } from "lucide-react";
import { decideRemoved, getRemovedRestaurants, undoRemoved } from "../../api/adminApi.js";
import { REMOVED_DECISIONS, capitalise, formatDateTime, formatDay, plural } from "../../services/adminFormat.js";
import AdminMap from "./AdminMap.jsx";
import {
  ActionButton, Badge, Card, EmptyState, ErrorBox, ExternalLinkText, Field, ListButton, Loading, Notice, SplitView, TextInput,
} from "./AdminUi.jsx";

// Restaurants in the database that are no longer in OpenStreetMap (data/review/removed_from_osm.json).
// The decision (closed, delete, keep) goes into src/reference/removed_restaurant_decisions.json.

const TONES = { closed: "amber", delete: "red", keep: "green" };

function RemovedDetail({ item, note, onNote, busy, error, notice, onDecide, onUndo }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const decision = item.decision;
  const map = useMemo(() => ({
    points: item.latitude != null ? [{ longitude: item.longitude, latitude: item.latitude, color: "#ff6129", label: item.name }] : [],
  }), [item.latitude, item.longitude, item.name]);

  const choose = (value) => {
    if (value === "delete" && !confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setConfirmDelete(false);
    onDecide(value);
  };

  return (
    <div className="mx-auto flex max-w-[56rem] flex-col gap-4 p-8">
      <div>
        <h2 className="text-[1.375rem] font-bold">{item.name}</h2>
        <p className="mt-1 text-[0.875rem] text-gray-600 dark:text-muted-dark">
          No longer in OpenStreetMap: a mapper closed and deleted it, or redrew it with a new ID. Nothing changes in the database until you decide.
        </p>
      </div>
      <Notice>{notice}</Notice>
      <ErrorBox error={error} />
      <Card>
        {decision ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={TONES[decision.decision]}>{REMOVED_DECISIONS[decision.decision]?.label || decision.decision}</Badge>
              <span className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">
                by {decision.decided_by || "hand"}{decision.decided_at && ` on ${formatDateTime(decision.decided_at)}`}
              </span>
            </div>
            {decision.note && <p className="text-[0.8125rem]">Note: {decision.note}</p>}
            <p className="inline-flex items-center gap-1.5 text-[0.8125rem] text-amber-700 dark:text-amber-300">
              <Clock className="size-[0.875rem]" /> Waiting for tonight's update. Until then you can change or undo it.
            </p>
            <div><ActionButton tone="undo" disabled={busy} onClick={onUndo}><Undo2 /> Undo</ActionButton></div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-[0.875rem] font-semibold">What should happen to it?</p>
            <TextInput value={note} maxLength={300} onChange={(event) => onNote(event.target.value)}
              placeholder="Note (optional): why, e.g. shut, Google says permanently closed" />
            <ul className="flex flex-col gap-2">
              {Object.entries(REMOVED_DECISIONS).map(([value, { label, text }]) => (
                <li key={value} className="flex items-center gap-3">
                  {/* Delete is red: outlined at first, solid for "Yes, delete" */}
                  <ActionButton className="w-[9rem] shrink-0" disabled={busy} onClick={() => choose(value)}
                    tone={value !== "delete" ? "secondary" : confirmDelete ? "danger" : "dangerOutline"}>
                    {value === "delete" && confirmDelete ? "Yes, delete" : label}
                  </ActionButton>
                  <span className="text-[0.8125rem] text-gray-600 dark:text-muted-dark">{text}</span>
                </li>
              ))}
            </ul>
            {confirmDelete && (
              <p className="text-[0.8125rem] text-red-600 dark:text-red-400">
                Click "Yes, delete" to confirm, or <button type="button" className="cursor-pointer underline" onClick={() => setConfirmDelete(false)}>cancel</button>.
              </p>
            )}
          </div>
        )}
      </Card>
      <Card>
        <dl className="grid grid-cols-2 gap-4">
          <Field label="Address">{item.address}</Field>
          <Field label="Status now">{item.business_status && capitalise(item.business_status.toLowerCase())}</Field>
          <Field label="Last seen in OpenStreetMap">{item.last_seen_in_osm ? formatDay(item.last_seen_in_osm.slice(0, 10)) : null}</Field>
          <Field label="OpenStreetMap ID">{item.osm_type}/{item.osm_id}</Field>
          <Field label="Open in">
            <span className="flex gap-4">
              <ExternalLinkText href={item.osm_map}>OpenStreetMap (history)</ExternalLinkText>
              <ExternalLinkText href={item.google_map}>Google Maps</ExternalLinkText>
            </span>
          </Field>
        </dl>
      </Card>
      {map.points.length > 0 && <AdminMap {...map} fitLabel="Show the pin" className="h-[18rem]" />}
    </div>
  );
}

export default function RemovedTab({ onChanged }) {
  const [list, setList] = useState(null);
  const [listError, setListError] = useState(null);
  const [version, setVersion] = useState(0);
  const [selectedId, setSelectedId] = useState(null);
  const [notes, setNotes] = useState({});
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    let alive = true;
    getRemovedRestaurants().then(
      (data) => { if (alive) { setList(data); setListError(null); } },
      (error) => { if (alive) setListError(error); },
    );
    return () => { alive = false; };
  }, [version]);

  if (listError) return <div className="p-8"><ErrorBox error={listError} onRetry={() => setVersion((v) => v + 1)} /></div>;
  if (!list) return <Loading />;
  const items = list.items;
  if (!items.length) {
    return (
      <EmptyState title="Nothing to decide"
        text="Restaurants that disappear from OpenStreetMap while they are still in the database appear here after the next load." />
    );
  }
  const current = items.find((item) => item.osm_id === selectedId) || items.find((item) => !item.decision) || items[0];

  const run = async (action, message) => {
    setBusy(true);
    setActionError(null);
    try {
      const { decision } = await action();
      setList((old) => ({ ...old, items: old.items.map((item) => (item.osm_id === current.osm_id ? { ...item, decision } : item)) }));
      setNotice(message);
      onChanged();
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <SplitView
      list={(
        <>
          <p className="border-b border-gray-200 p-4 text-[0.8125rem] text-gray-500 dark:border-line-dark dark:text-muted-dark">
            {plural(items.length, "restaurant")} no longer in OpenStreetMap · list written on {formatDateTime(list.file_written)}
          </p>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {items.map((item) => (
              <ListButton key={item.osm_id} selected={item.osm_id === current.osm_id}
                onClick={() => { setSelectedId(item.osm_id); setActionError(null); setNotice(null); }}>
                <p className="truncate text-[0.875rem] font-semibold">{item.name}</p>
                <p className="truncate text-[0.75rem] text-gray-500 dark:text-muted-dark">{item.address || "No address"}</p>
                {item.decision && (
                  <Badge tone={TONES[item.decision.decision]} className="mt-1.5">{REMOVED_DECISIONS[item.decision.decision]?.label}</Badge>
                )}
              </ListButton>
            ))}
          </div>
        </>
      )}
    >
      <RemovedDetail
        key={current.osm_id}
        item={current}
        note={notes[current.osm_id] || ""}
        onNote={(value) => setNotes((old) => ({ ...old, [current.osm_id]: value }))}
        busy={busy}
        error={actionError}
        notice={notice}
        onDecide={(value) => run(() => decideRemoved(current.osm_id, value, notes[current.osm_id] || ""),
          `Saved: ${REMOVED_DECISIONS[value].label} for "${current.name}". Takes effect tonight.`)}
        onUndo={() => run(() => undoRemoved(current.osm_id), `Undone: "${current.name}" is waiting for a decision again.`)}
      />
    </SplitView>
  );
}
