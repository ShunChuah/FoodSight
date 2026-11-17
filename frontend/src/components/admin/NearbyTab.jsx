import { useEffect, useMemo, useState } from "react";
import { Ban, Clock, Undo2 } from "lucide-react";
import { excludePlace, getExclusions, getNearbyPlace, getNearbyPlaces, removeExclusion } from "../../api/adminApi.js";
import { capitalise, formatDateTime, plural } from "../../services/adminFormat.js";
import { Dropdown } from "../business/BusinessFields";
import AdminMap from "./AdminMap.jsx";
import {
  ActionButton, Badge, EmptyState, ErrorBox, ExternalLinkText, ListButton, ListScroll, Loading, Notice, SearchBox, Section, SplitView, Tabs,
  TextInput,
} from "./AdminUi.jsx";

// The OpenStreetMap places counted around restaurants (public.nearby_place) and the
// hand-checked exclusions (src/reference/nearby_exclusions.json): a place OSM tags wrongly
// (a clinic as a hospital, a tuition centre as a school) or maps twice is excluded with a reason.

const PAGE = 50;
const PLACE_COLOR = "#ff6129";
const RESTAURANT_COLOR = "#2563eb";
const SHOWN_RESTAURANTS = 8;

const keyOf = (place) => `${place.osm_type}/${place.osm_id}`;

function countText(place) {
  if (place.kind === "station") return `Nearest station for ${plural(place.restaurants ?? 0, "restaurant")}`;
  return `Counted by ${plural(place.restaurants ?? 0, "restaurant")}`;
}

function ExclusionPanel({ exclusion, busy, onExclude, onRemove, waiting }) {
  const [reason, setReason] = useState("");
  if (exclusion) {
    return (
      <Section>
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="red"><Ban className="size-[0.75rem]" /> Excluded</Badge>
            <span className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">
              by {exclusion.decided_by || "hand"}{exclusion.decided_at && ` on ${formatDateTime(exclusion.decided_at)}`}
            </span>
          </div>
          <p className="text-[0.875rem]">Reason: {exclusion.reason}</p>
          {waiting && (
            <p className="inline-flex items-center gap-1.5 text-[0.8125rem] text-amber-700 dark:text-amber-300">
              <Clock className="size-[0.875rem]" /> Still counted until tonight's update.
            </p>
          )}
          <div>
            <ActionButton tone="undo" disabled={busy} onClick={onRemove}><Undo2 /> Remove the exclusion (count it again)</ActionButton>
          </div>
        </div>
      </Section>
    );
  }
  return (
    <Section title="Should this place not be counted?">
      <form className="flex flex-col gap-3" onSubmit={(event) => { event.preventDefault(); onExclude(reason.trim()); }}>
        <TextInput value={reason} maxLength={300} onChange={(event) => setReason(event.target.value)}
          placeholder="Reason, e.g. a clinic, not a hospital" />
        <div>
          <ActionButton type="submit" tone="primary" disabled={busy || !reason.trim()}><Ban /> Exclude from the counts</ActionButton>
        </div>
        <p className="text-[0.75rem] text-gray-500 dark:text-muted-dark">
          The place stays in OpenStreetMap, but the pipeline no longer counts it around any restaurant.
        </p>
      </form>
    </Section>
  );
}

function PlaceDetail({ place, entry, busy, error, notice, onExclude, onRemove }) {
  const [showAll, setShowAll] = useState(false);
  const restaurants = place.restaurants;
  const map = useMemo(() => ({
    points: [
      ...restaurants.map((r) => ({ longitude: r.longitude, latitude: r.latitude, color: RESTAURANT_COLOR, size: 8 })),
      { longitude: place.longitude, latitude: place.latitude, color: PLACE_COLOR, size: 16, label: place.name },
    ],
    circles: place.radius_m ? [{ longitude: place.longitude, latitude: place.latitude, radius: place.radius_m }] : [],
  }), [restaurants, place.longitude, place.latitude, place.name, place.radius_m]);
  const exclusion = place.exclusion || entry;

  return (
    <div className="flex flex-col gap-4 p-6">
      <div>
        <Badge tone="brand">{capitalise(place.kind)}{place.station_type && ` · ${place.station_type}`}</Badge>
        <h2 className="mt-3 text-[1.375rem] font-bold">{place.name}</h2>
        <div className="mt-1"><ExternalLinkText href={place.map}>Open in OpenStreetMap ({keyOf(place)})</ExternalLinkText></div>
      </div>
      <Notice>{notice}</Notice>
      <ErrorBox error={error} />
      <ExclusionPanel key={keyOf(place)} exclusion={exclusion} waiting busy={busy} onExclude={onExclude} onRemove={onRemove} />
      <AdminMap {...map} fitLabel="Show all" className="h-[20rem]" />
      <p className="-mt-2 text-[0.75rem] text-gray-500 dark:text-muted-dark">
        <span style={{ color: RESTAURANT_COLOR }}>●</span> {place.kind === "station" ? "restaurants with this as their nearest station" : "restaurants that count it"}
        {place.radius_m ? ` · dashed circle: the ${place.radius_m.toLocaleString("en-GB")} m radius` : ""}
      </p>
      <Section title={countText({ ...place, restaurants: restaurants.length })}>
        {!restaurants.length && <p className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">No restaurant counts it.</p>}
        {restaurants.length > 0 && (
          <ul className="grid grid-cols-2 gap-x-6 gap-y-1 text-[0.8125rem]">
            {(showAll ? restaurants : restaurants.slice(0, SHOWN_RESTAURANTS)).map((r) => (
              <li key={r.restaurant_id} className="flex justify-between gap-3">
                <span className="truncate">{r.name}</span>
                <span className="shrink-0 text-gray-500 dark:text-muted-dark">{r.distance_m} m</span>
              </li>
            ))}
          </ul>
        )}
        {restaurants.length > SHOWN_RESTAURANTS && (
          <button type="button" onClick={() => setShowAll((on) => !on)} className="mt-2 cursor-pointer text-[0.8125rem] font-semibold text-brand hover:underline">
            {showAll ? "Show fewer" : `Show all ${restaurants.length}`}
          </button>
        )}
      </Section>
    </div>
  );
}

function GoneDetail({ entry, busy, error, notice, onRemove }) {
  return (
    <div className="flex flex-col gap-4 p-6">
      <div>
        <Badge tone="brand">{capitalise(entry.kind)}</Badge>
        <h2 className="mt-3 text-[1.375rem] font-bold">{entry.name}</h2>
        <div className="mt-1"><ExternalLinkText href={entry.map}>Open in OpenStreetMap ({entry.key})</ExternalLinkText></div>
        <p className="mt-2 text-[0.875rem] text-gray-600 dark:text-muted-dark">
          Not in the nearby places table: the exclusion works (or OpenStreetMap no longer has the place).
        </p>
      </div>
      <Notice>{notice}</Notice>
      <ErrorBox error={error} />
      <ExclusionPanel exclusion={entry} busy={busy} onRemove={onRemove} onExclude={() => {}} />
    </div>
  );
}

export default function NearbyTab({ onChanged }) {
  const [mode, setMode] = useState("places");
  const [kind, setKind] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [places, setPlaces] = useState(null);
  const [placesError, setPlacesError] = useState(null);
  const [placesVersion, setPlacesVersion] = useState(0);
  const [exclusions, setExclusions] = useState(null);
  const [exclusionsVersion, setExclusionsVersion] = useState(0);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailVersion, setDetailVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);

  // Search after a short pause in typing
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    let alive = true;
    getNearbyPlaces({ kind, q: query, limit: PAGE, offset: 0 }).then(
      (data) => { if (alive) { setPlaces(data); setPlacesError(null); } },
      (error) => { if (alive) setPlacesError(error); },
    );
    return () => { alive = false; };
  }, [kind, query, placesVersion]);

  useEffect(() => {
    let alive = true;
    getExclusions().then((data) => { if (alive) setExclusions(data.items); }, () => {});
    return () => { alive = false; };
  }, [exclusionsVersion]);

  const listed = mode === "places" ? places?.items || [] : exclusions || [];
  const current = selected || (listed[0] && keyOf(listed[0]));
  const entry = (exclusions || []).find((item) => item.key === current);

  useEffect(() => {
    if (!current) return undefined;
    let alive = true;
    const [osmType, osmId] = current.split("/");
    getNearbyPlace(osmType, osmId).then(
      (data) => { if (alive) setDetail({ key: current, data }); },
      (error) => { if (alive) setDetail({ key: current, error }); },
    );
    return () => { alive = false; };
  }, [current, detailVersion]);

  const shown = detail?.key === current ? detail : null;

  const select = (key) => {
    setSelected(key);
    setActionError(null);
    setNotice(null);
  };

  const loadMore = async () => {
    try {
      const more = await getNearbyPlaces({ kind, q: query, limit: PAGE, offset: places.items.length });
      setPlaces((old) => ({ ...more, items: [...old.items, ...more.items] }));
    } catch (error) {
      setPlacesError(error);
    }
  };

  const run = async (action, message, after) => {
    const [osmType, osmId] = current.split("/");
    setBusy(true);
    setActionError(null);
    try {
      await action(osmType, osmId);
      setNotice(message);
      after?.();
      setExclusionsVersion((v) => v + 1);
      setPlacesVersion((v) => v + 1);
      setDetailVersion((v) => v + 1);
      onChanged();
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(false);
    }
  };

  const name = shown?.data?.name || entry?.name || current;
  const onExclude = (reason) => run((t, i) => excludePlace(t, i, reason), `Excluded: "${name}". Takes effect tonight.`);
  // In the Excluded list the place leaves the list, so move on to the first one left
  const onRemove = () => run(removeExclusion, `"${name}" is counted again from tonight's update.`,
    mode === "excluded" ? () => setSelected(null) : undefined);

  if (placesError && !places) return <ErrorBox error={placesError} onRetry={() => setPlacesVersion((v) => v + 1)} />;
  if (!places) return <Loading />;

  const modeTabs = [
    { id: "places", label: "All places" },
    { id: "excluded", label: "Excluded", count: exclusions ? exclusions.length : "…" },
  ];
  const kindOptions = [
    { value: "", label: "Every kind" },
    ...places.kinds.map((k) => ({ value: k.kind, label: `${capitalise(k.kind)} (${k.places})` })),
  ];

  return (
    <>
      <Tabs label="Places" tabs={modeTabs} active={mode} onChange={(id) => { setMode(id); setSelected(null); }} />
      <SplitView
        list={(
          <>
            {mode === "places" && (
              <div className="admin-split-tools">
                <SearchBox value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search names, e.g. clinic, tuition" />
                <Dropdown id="nearby-kind" ariaLabel="Kind" value={kind} options={kindOptions}
                  onChange={(value) => { setKind(value); setSelected(null); }} />
                <p className="admin-split-note">{plural(places.total, "place")}, the most counted first</p>
              </div>
            )}
            <ListScroll>
              {listed.map((item) => {
                const key = keyOf(item);
                const excluded = mode === "excluded" ? item : item.exclusion;
                return (
                  <ListButton key={key} selected={key === current} onClick={() => select(key)}>
                    <div className="flex items-start justify-between gap-2">
                      <p className="admin-row-title truncate">{item.name}</p>
                      {mode === "places" && <span className="shrink-0 text-[0.8125rem] text-gray-500 dark:text-muted-dark">{item.restaurants}</span>}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge>{capitalise(item.kind)}</Badge>
                      {excluded && <Badge tone="red">Excluded</Badge>}
                      {mode === "excluded" && item.waiting_update && <Badge tone="amber">Until tonight</Badge>}
                    </div>
                    {mode === "excluded" && <p className="admin-row-sub truncate">{item.reason}</p>}
                  </ListButton>
                );
              })}
              {!listed.length && <p className="admin-split-note p-4">Nothing found.</p>}
              {mode === "places" && places.items.length < places.total && (
                <div className="p-4">
                  <ActionButton className="w-full" onClick={loadMore}>Show more</ActionButton>
                </div>
              )}
            </ListScroll>
          </>
        )}
      >
        {!current && <EmptyState title="Nothing selected" text="Choose a place on the left." />}
        {current && !shown && <Loading />}
        {shown?.data && (
          <PlaceDetail key={current} place={shown.data} entry={entry} busy={busy} error={actionError} notice={notice}
            onExclude={onExclude} onRemove={onRemove} />
        )}
        {shown?.error && entry && <GoneDetail entry={entry} busy={busy} error={actionError} notice={notice} onRemove={onRemove} />}
        {shown?.error && !entry && <div className="p-6"><ErrorBox error={shown.error} /></div>}
      </SplitView>
    </>
  );
}
