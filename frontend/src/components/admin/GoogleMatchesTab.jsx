import { useEffect, useMemo, useState } from "react";
import { Check, Clock, Undo2, X } from "lucide-react";
import {
  decideGoogleMatch, decideShared, getGoogleMatch, getGoogleMatches, undoGoogleMatch, undoShared,
} from "../../api/adminApi.js";
import { GOOGLE_COLOR, OSM_COLOR, REASON_LABELS, capitalise, formatDateTime, plural } from "../../services/adminFormat.js";
import { Dropdown } from "../business/BusinessFields";
import AdminMap from "./AdminMap.jsx";
import {
  ActionButton, Badge, EmptyState, ErrorBox, ListButton, ListScroll, Loading, Notice, SearchBox, Section, SplitView, Tabs, TextInput,
} from "./AdminUi.jsx";
import { Comparison, DecisionBadge, PinChoice } from "./MatchParts.jsx";
import SharedPlaceDetail from "./SharedPlaceDetail.jsx";

// Restaurants held back because a Google place may or may not be the same shop
// (data/review/google_match_review.json). "Same place" writes the shown Google place ID into
// src/reference/google_match_overrides.json, "Not the same" writes null. The restaurants of
// one shared Google place are one entry, decided together (SharedPlaceDetail).

const SHOW = { waiting: "To decide", decided: "Decided", all: "All" };

// A restaurant shows under its own reason, and also under "Pins too far apart" when its
// pins are more than 50 m apart (far_apart from the backend: a partly alike name, for example)
function hasReason(item, reason) {
  return item.reason === reason || (reason === "too_far" && item.far_apart);
}

// The list's entries: one per restaurant, but one per shared Google place for its restaurants
function toEntries(items) {
  const entries = [];
  const groups = new Map();
  for (const item of items) {
    if (item.reason === "shared_google_place" && item.place_id) {
      let group = groups.get(item.place_id);
      if (!group) {
        group = { key: `shared:${item.place_id}`, group: true, reason: item.reason, place_id: item.place_id,
          google_name: item.google_name, members: [] };
        groups.set(item.place_id, group);
        entries.push(group);
      }
      group.members.push(item);
    } else {
      entries.push({ ...item, key: item.osm_id });
    }
  }
  return entries;
}

const decidedEntry = (entry) => (entry.group ? entry.members.every((m) => m.decision) : Boolean(entry.decision));
const entryHasReason = (entry, reason) => (entry.group ? entry.members.some((m) => hasReason(m, reason)) : hasReason(entry, reason));
const entryWords = (entry) => (entry.group
  ? [...entry.members.map((m) => m.osm_name), entry.google_name] : [entry.osm_name, entry.google_name]).join(" ").toLowerCase();

// Written here from the figures, so the wording does not wait for the next Google extraction
function reasonSentence(item) {
  if (item.reason === "too_far" && item.distance_m != null && item.limit_m != null) {
    return `${capitalise(item.name_strength)} name, but the pins are ${item.distance_m} m apart (matched automatically only within ${item.limit_m} m).`;
  }
  return item.reason_text;
}

function DecisionPanel({ item, others, note, onNote, pin, onPin, busy, onDecide, onUndo, onSelect }) {
  const decision = item.decision;
  return (
    <Section title={decision ? null : "Is this the same restaurant?"}>
      {decision ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <DecisionBadge decision={decision} />
            <span className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">
              by {decision.decided_by || "hand"}{decision.decided_at && ` on ${formatDateTime(decision.decided_at)}`}
            </span>
          </div>
          {decision.note && <p className="text-[0.8125rem]">Note: {decision.note}</p>}
          <p className="inline-flex items-center gap-1.5 text-[0.8125rem] text-amber-700 dark:text-amber-300">
            <Clock className="size-[0.875rem]" /> Waiting for tonight's update. Until then you can change or undo it.
          </p>
          <div className="flex gap-2">
            {decision.kind !== "same" && <ActionButton tone="primary" disabled={busy} onClick={() => onDecide(true)}><Check /> Change to same place</ActionButton>}
            {decision.kind !== "not_same" && <ActionButton disabled={busy} onClick={() => onDecide(false)}><X /> Change to not the same</ActionButton>}
            <ActionButton tone="undo" disabled={busy} onClick={onUndo}><Undo2 /> Undo</ActionButton>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex gap-2">
            <TextInput className="min-w-0 flex-1" value={note} maxLength={300} onChange={(event) => onNote(event.target.value)}
              placeholder="Note (optional): why you decided, e.g. same shop, checked on Google Maps" />
            <ActionButton className="shrink-0" tone="primary" disabled={busy} onClick={() => onDecide(true)}
              title="The restaurant gets this Google place's details, rating and reviews">
              <Check /> Same place
            </ActionButton>
            <ActionButton className="shrink-0" disabled={busy} onClick={() => onDecide(false)}
              title="The restaurant goes on with OpenStreetMap data only">
              <X /> Not the same
            </ActionButton>
          </div>
          {item.pin_choice && <PinChoice pin={pin} onPin={onPin} />}
        </div>
      )}
      {others.length > 0 && (
        <div className="mt-4 border-t border-[#f0f0f1] pt-3 text-[0.8125rem] dark:border-line-dark">
          <p className="font-semibold">The removed restaurant that had this Google place:</p>
          <ul className="mt-1 flex flex-col gap-1">
            {others.map((other) => (
              <li key={other.osm_id} className="flex items-center gap-2">
                {other.inList
                  ? <button type="button" onClick={() => onSelect(other.osm_id)} className="cursor-pointer text-brand hover:underline">{other.osm_name || other.osm_id}</button>
                  : <span>{other.osm_name || other.osm_id}</span>}
                <span className="text-gray-400">({other.osm_id})</span>
                <DecisionBadge decision={other.decision} />
              </li>
            ))}
          </ul>
          <p className="mt-2 text-gray-500 dark:text-muted-dark">Same place moves that restaurant's database row, with its reviews, to this new OpenStreetMap ID.</p>
        </div>
      )}
    </Section>
  );
}

function MatchDetail({ item, others, note, onNote, pin, onPin, busy, error, notice, onDecide, onUndo, onSelect }) {
  const osm = item.osm || {};
  const location = item.google?.details?.location;
  const map = useMemo(() => {
    const osmPin = { longitude: Number(osm.longitude), latitude: Number(osm.latitude) };
    const points = [{ ...osmPin, color: OSM_COLOR, label: "OSM" }];
    const lines = [];
    if (location) {
      const googlePin = { longitude: location.longitude, latitude: location.latitude };
      points.push({ ...googlePin, color: GOOGLE_COLOR, label: "Google" });
      lines.push({ from: [osmPin.longitude, osmPin.latitude], to: [googlePin.longitude, googlePin.latitude],
        label: item.distance_m != null ? `${item.distance_m} m` : null });
    }
    const circles = item.limit_m ? [{ ...osmPin, radius: item.limit_m }] : [];
    return { points, lines, circles };
  }, [osm.longitude, osm.latitude, location, item.limit_m, item.distance_m]);

  // The title's colours are the legend; the sentence gives the reason, the distance and the limit
  return (
    <div className="flex flex-col gap-4 p-6">
      <div>
        <h2 className="text-[1.375rem] font-bold">
          <span style={{ color: OSM_COLOR }}>{item.osm_name}</span>
          <span className="mx-2 text-gray-400">vs</span>
          <span style={{ color: GOOGLE_COLOR }}>{item.google_name}</span>
        </h2>
        <p className="mt-1 text-[0.875rem] text-gray-600 dark:text-muted-dark">{reasonSentence(item)}</p>
      </div>
      <Notice>{notice}</Notice>
      <ErrorBox error={error} />
      <DecisionPanel item={item} others={others} note={note} onNote={onNote} pin={pin} onPin={onPin} busy={busy}
        onDecide={onDecide} onUndo={onUndo} onSelect={onSelect} />
      <div>
        <AdminMap {...map} satellite fitLabel={location ? "Show both pins" : "Show the pin"} className="h-[20rem]" />
        {item.limit_m != null && (
          <p className="mt-1.5 text-[0.75rem] text-gray-500 dark:text-muted-dark">
            Dashed circle: a Google place inside it is matched automatically.
          </p>
        )}
      </div>
      <Comparison osmSides={[{ key: item.osm_id, title: "OpenStreetMap", osm }]} google={item.google} />
    </div>
  );
}

function EntryButton({ entry, selected, onClick }) {
  if (entry.group) {
    const chosen = entry.members.find((m) => m.decision?.kind === "same");
    return (
      <ListButton selected={selected} onClick={onClick}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="admin-row-title truncate">{entry.members.map((m) => m.osm_name).join(" · ")}</p>
            <p className="admin-row-sub truncate">Google: {entry.google_name}</p>
          </div>
          <span className="shrink-0 text-[0.8125rem] text-gray-500 dark:text-muted-dark">{plural(entry.members.length, "restaurant")}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          <Badge tone="brand">{REASON_LABELS.shared_google_place}</Badge>
          {entry.members.some((m) => m.far_apart) && <Badge tone="brand">{REASON_LABELS.too_far}</Badge>}
          {decidedEntry(entry) && (chosen
            ? <Badge tone="green"><Check className="size-[0.75rem]" /> {chosen.osm_name}</Badge>
            : <Badge tone="gray"><X className="size-[0.75rem]" /> Neither</Badge>)}
        </div>
      </ListButton>
    );
  }
  return (
    <ListButton selected={selected} onClick={onClick}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="admin-row-title truncate">{entry.osm_name}</p>
          <p className="admin-row-sub truncate">Google: {entry.google_name}</p>
        </div>
        <span className="shrink-0 text-[0.8125rem] text-gray-500 dark:text-muted-dark">{entry.distance_m} m</span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <Badge tone="brand">{REASON_LABELS[entry.reason] || entry.reason}</Badge>
        {entry.far_apart && entry.reason !== "too_far" && <Badge tone="brand">{REASON_LABELS.too_far}</Badge>}
        <DecisionBadge decision={entry.decision} />
      </div>
    </ListButton>
  );
}

export default function GoogleMatchesTab({ onChanged }) {
  const [list, setList] = useState(null);
  const [listError, setListError] = useState(null);
  const [listVersion, setListVersion] = useState(0);
  const [reason, setReason] = useState("all");
  const [show, setShow] = useState("waiting");
  const [search, setSearch] = useState("");
  const [selectedKey, setSelectedKey] = useState(null);
  const [detail, setDetail] = useState(null);
  const [notes, setNotes] = useState({});   // entry key -> note
  const [pins, setPins] = useState({});     // entry key -> "osm" | "google": the pin to save
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    let alive = true;
    getGoogleMatches().then(
      (data) => { if (alive) { setList(data); setListError(null); } },
      (error) => { if (alive) setListError(error); },
    );
    return () => { alive = false; };
  }, [listVersion]);

  const items = useMemo(() => list?.items || [], [list]);
  const entries = useMemo(() => toEntries(items), [items]);
  const words = search.trim().toLowerCase();
  const filtered = entries.filter((entry) =>
    (reason === "all" || entryHasReason(entry, reason))
    && (show === "all" || (show === "waiting" ? !decidedEntry(entry) : decidedEntry(entry)))
    && (!words || entryWords(entry).includes(words)));
  const currentKey = selectedKey && entries.some((e) => e.key === selectedKey) ? selectedKey : filtered[0]?.key;
  const current = entries.find((e) => e.key === currentKey);
  // The restaurants whose details the right side needs: one, or every one of a shared place
  const detailIds = current ? (current.group ? current.members.map((m) => m.osm_id) : [current.osm_id]).join(",") : "";

  useEffect(() => {
    if (!currentKey || !detailIds) return undefined;
    let alive = true;
    Promise.all(detailIds.split(",").map((osmId) => getGoogleMatch(osmId))).then(
      (data) => { if (alive) setDetail({ key: currentKey, data }); },
      (error) => { if (alive) setDetail({ key: currentKey, loadError: error }); },
    );
    return () => { alive = false; };
  }, [currentKey, detailIds]);

  const shown = detail?.key === currentKey ? detail : null;
  const reasonsPresent = Object.keys(REASON_LABELS).filter((key) => items.some((item) => hasReason(item, key)));

  const select = (key) => {
    setSelectedKey(key);
    setActionError(null);
    setNotice(null);
  };

  // decisions: {osm_id: decision or null}
  const saved = (decisions) => {
    setList((old) => ({ ...old, items: old.items.map((item) => (item.osm_id in decisions ? { ...item, decision: decisions[item.osm_id] } : item)) }));
    onChanged();
  };

  // On to the next entry still to decide, so the decisions need no extra clicks. With none
  // left, the decided one stays shown (with its notice) even when the filter now hides it
  const nextAfter = (key) => {
    const after = filtered.slice(filtered.findIndex((e) => e.key === key) + 1);
    const next = after.find((e) => !decidedEntry(e)) || filtered.find((e) => !decidedEntry(e) && e.key !== key);
    setSelectedKey(next ? next.key : key);
  };

  const act = async (work) => {
    setBusy(true);
    setActionError(null);
    try {
      await work();
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(false);
    }
  };

  const decide = (same) => act(async () => {
    const pin = same && current.pin_choice ? pins[current.key] || "osm" : "osm";
    const { decision } = await decideGoogleMatch(current.osm_id, same, notes[current.key] || "", pin);
    saved({ [current.osm_id]: decision });
    if (!current.decision) nextAfter(current.key);
    const what = same ? `the same place${pin === "google" ? ", with Google's pin" : ""}` : "not the same";
    setNotice(`Saved: "${current.osm_name}" is ${what}. Takes effect tonight.`);
  });

  const undo = () => act(async () => {
    await undoGoogleMatch(current.osm_id);
    saved({ [current.osm_id]: null });
    setNotice(`Undone: "${current.osm_name}" is waiting for a decision again.`);
  });

  const decideGroup = (osmId) => act(async () => {
    const chosen = current.members.find((m) => m.osm_id === osmId);
    const pin = chosen?.pin_choice ? pins[current.key] || "osm" : "osm";
    const { decisions } = await decideShared(current.place_id, osmId, notes[current.key] || "", pin);
    saved(decisions);
    if (!decidedEntry(current)) nextAfter(current.key);
    const rest = current.members.filter((m) => m !== chosen).map((m) => `"${m.osm_name}"`).join(", ");
    setNotice(chosen
      ? `Saved: "${chosen.osm_name}" is this Google place; ${rest} ${current.members.length > 2 ? "go" : "goes"} on with OpenStreetMap data only. Takes effect tonight.`
      : "Saved: none of these restaurants is this Google place. Takes effect tonight.");
  });

  const undoGroup = () => act(async () => {
    const { decisions } = await undoShared(current.place_id);
    saved(decisions);
    setNotice("Undone: these restaurants are waiting for a decision again.");
  });

  if (listError) return <ErrorBox error={listError} onRetry={() => setListVersion((v) => v + 1)} />;
  if (!list) return <Loading />;
  if (!items.length) {
    return <EmptyState title="No Google matches to check" text="Restaurants whose Google match needs a person appear here after a Google extraction." />;
  }

  const others = current && !current.group ? (current.others || []).map((other) => {
    const inList = items.find((item) => item.osm_id === other.osm_id);
    return { ...other, inList: Boolean(inList), decision: inList?.decision };
  }) : [];
  const shared = {
    note: notes[currentKey] || "",
    onNote: (value) => setNotes((old) => ({ ...old, [currentKey]: value })),
    pin: pins[currentKey] || "osm",
    onPin: (value) => setPins((old) => ({ ...old, [currentKey]: value })),
    busy,
    error: actionError,
    notice,
  };

  // The counts count restaurants, like the Overview; a shared place is one entry for its restaurants
  const showTabs = Object.entries(SHOW).map(([key, label]) => ({
    id: key, label,
    count: items.filter((item) => key === "all" || (key === "waiting" ? !item.decision : Boolean(item.decision))).length,
  }));
  const reasonOptions = [
    { value: "all", label: "Every reason" },
    ...reasonsPresent.map((key) => ({ value: key, label: `${REASON_LABELS[key]} (${items.filter((item) => hasReason(item, key)).length})` })),
  ];

  return (
    <>
      <Tabs label="Decision" tabs={showTabs} active={show} onChange={setShow} />
      <SplitView
        list={(
          <>
            <div className="admin-split-tools">
              <SearchBox value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search OSM or Google names" />
              <Dropdown id="google-reason" ariaLabel="Reason" value={reason} options={reasonOptions} onChange={setReason} />
            </div>
            <ListScroll>
              {filtered.map((entry) => (
                <EntryButton key={entry.key} entry={entry} selected={entry.key === currentKey} onClick={() => select(entry.key)} />
              ))}
              {!filtered.length && <p className="admin-split-note p-4">Nothing matches these filters.</p>}
            </ListScroll>
            <p className="admin-split-foot">List written by the Google extraction on {formatDateTime(list.file_written)}</p>
          </>
        )}
      >
        {!current && <EmptyState title="Nothing selected" text="Choose a restaurant on the left." />}
        {current && !shown && <Loading />}
        {current && shown?.loadError && <div className="p-6"><ErrorBox error={shown.loadError} /></div>}
        {current && shown?.data && current.group && (
          <SharedPlaceDetail group={current} details={shown.data} {...shared} onDecide={decideGroup} onUndo={undoGroup} />
        )}
        {current && shown?.data && !current.group && (
          <MatchDetail item={{ ...shown.data[0], decision: current.decision }} others={others} {...shared}
            onDecide={decide} onUndo={undo} onSelect={select} />
        )}
      </SplitView>
    </>
  );
}
