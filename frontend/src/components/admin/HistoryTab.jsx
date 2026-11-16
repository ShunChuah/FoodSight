import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { getHistory, getReport } from "../../api/adminApi.js";
import { formatDateTime, formatDay, formatNumber, formatShare, plural } from "../../services/adminFormat.js";
import ChangeShareChart from "./ChangeShareChart.jsx";
import { Badge, Card, EmptyState, ErrorBox, ExternalLinkText, FilterChip, Loading } from "./AdminUi.jsx";

// Read only: every extraction's change report (data/reports), the scheduling decision made
// from it (data/state/schedule.json), and the dropped duplicate pins.

const SOURCES = { osm: "OpenStreetMap", google: "Google" };
const LIST_LIMIT = 30;

function kindOf(item, source) {
  if (item.baseline) return { label: "First extraction", tone: "gray" };
  if (!item.report) return { label: "No report", tone: "amber" };
  if (source === "google") {
    return item.kind?.startsWith("refresh") ? { label: "Refresh", tone: "brand" } : { label: "Lookups for new restaurants", tone: "blue" };
  }
  return { label: "Extraction", tone: "brand" };
}

function countText(counts) {
  if (!counts) return null;
  const parts = ["new", "changed", "removed"].filter((key) => counts[key]).map((key) => `${counts[key]} ${key}`);
  return parts.length ? parts.join(", ") : null;
}

function decisionText(item, source) {
  const decision = item.decision;
  if (!decision) {
    if (source === "google" && item.report && !item.baseline) {
      return "Google's next date did not move: only a full refresh moves it.";
    }
    return null;
  }
  const who = { ai: "the AI", default: "the default", runner: "the runner (no change figures)" }[decision.decided_by] || decision.decided_by;
  const interval = decision.interval_before != null && decision.interval_before !== decision.interval_after
    ? `every ${decision.interval_before} → ${decision.interval_after} days`
    : `every ${decision.interval_after} days`;
  return `Next extraction ${interval}, set by ${who}${decision.reason ? `: "${decision.reason}"` : ""}`;
}

function Records({ title, items, render }) {
  const [all, setAll] = useState(false);
  if (!items.length) return null;
  return (
    <div>
      <p className="mb-1 text-[0.75rem] font-semibold text-gray-500 dark:text-muted-dark">{title} ({items.length})</p>
      <ul className="flex flex-col gap-0.5 text-[0.8125rem]">
        {(all ? items : items.slice(0, LIST_LIMIT)).map((item) => <li key={item.key}>{render(item)}</li>)}
      </ul>
      {items.length > LIST_LIMIT && (
        <button type="button" onClick={() => setAll((on) => !on)} className="mt-1 cursor-pointer text-[0.75rem] font-semibold text-brand hover:underline">
          {all ? "Show fewer" : `Show all ${items.length}`}
        </button>
      )}
    </div>
  );
}

function Name({ item }) {
  const name = item.name || <span className="text-gray-400">(no name)</span>;
  return item.map
    ? <a href={item.map} target="_blank" rel="noreferrer" className="text-brand hover:underline">{name}</a>
    : <span>{name}</span>;
}

function Fields({ fields }) {
  return Object.entries(fields || {}).map(([field, change]) => (
    <span key={field} className="ml-2 text-gray-600 dark:text-muted-dark">
      {field}: {Array.isArray(change) ? <>{change[0] || "(empty)"} → {change[1] || "(empty)"}</> : change}
    </span>
  ));
}

function ReportDetail({ name }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    getReport(name).then((data) => { if (alive) setReport(data); }, (err) => { if (alive) setError(err); });
    return () => { alive = false; };
  }, [name]);
  if (error) return <ErrorBox error={error} />;
  if (!report) return <p className="text-[0.8125rem] text-gray-500">Loading…</p>;
  const changedFiles = report.files.filter((file) => file.new.length || file.removed.length || file.changed.length);
  if (!changedFiles.length) return <p className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">No record changed.</p>;
  return (
    <div className="flex flex-col gap-4">
      {changedFiles.map((file) => (
        <div key={file.file} className="rounded-[0.625rem] bg-zinc-50 p-3 dark:bg-[#1e1e1e]">
          <p className="mb-2 text-[0.8125rem] font-bold capitalize">{file.what}</p>
          <div className="flex flex-col gap-3">
            <Records title="New" items={file.new} render={(item) => <Name item={item} />} />
            <Records title="Removed" items={file.removed} render={(item) => <Name item={item} />} />
            <Records title="Changed" items={file.changed} render={(item) => <><Name item={item} /><Fields fields={item.fields} /></>} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ExtractionItem({ item, source }) {
  const [open, setOpen] = useState(false);
  const kind = kindOf(item, source);
  const changedFiles = (item.files || []).filter((file) => countText(file.counts));
  const unchanged = (item.files || []).length - changedFiles.length;
  const decision = decisionText(item, source);
  const totalRecords = (item.files || []).reduce((sum, file) => sum + (file.records || 0), 0);

  return (
    <li className="relative border-l-2 border-gray-200 pb-6 pl-6 last:pb-0 dark:border-line-dark">
      <span className="absolute top-1 -left-[0.4375rem] size-[0.75rem] rounded-full border-2 border-white bg-brand dark:border-page-dark" />
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[0.9375rem] font-bold">{formatDateTime(item.extracted_at)}</p>
        <Badge tone={kind.tone}>{kind.label}</Badge>
      </div>
      <p className="mt-1 text-[0.875rem]">
        {item.baseline
          ? `The starting point for later comparisons: ${formatNumber(item.records ?? totalRecords)} records.`
          : item.change_share != null
            ? <>{item.days_since != null && `${item.days_since} days after the last · `}<strong>{formatShare(item.change_share)} changed</strong> ({formatNumber(item.changes)} of {formatNumber(item.records)} records)</>
            : "No change figures."}
      </p>
      {decision && <p className="mt-1 text-[0.8125rem] text-gray-600 dark:text-muted-dark">{decision}</p>}
      {(changedFiles.length > 0 || item.reviews?.never_seen_before) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {changedFiles.map((file) => <Badge key={file.file}>{file.what}: {countText(file.counts)}</Badge>)}
          {item.reviews?.never_seen_before > 0 && <Badge tone="blue">{plural(item.reviews.never_seen_before, "new review")}</Badge>}
          {unchanged > 0 && <span className="text-[0.75rem] text-gray-500 dark:text-muted-dark">{plural(unchanged, "file")} unchanged</span>}
        </div>
      )}
      {item.report && !item.baseline && item.changes > 0 && (
        <div className="mt-2">
          <button type="button" onClick={() => setOpen((on) => !on)} className="inline-flex cursor-pointer items-center gap-1 text-[0.8125rem] font-semibold text-brand hover:underline">
            {open ? <ChevronUp className="size-[0.875rem]" /> : <ChevronDown className="size-[0.875rem]" />} {open ? "Hide the changed records" : "Show the changed records"}
          </button>
          {open && <div className="mt-2"><ReportDetail name={item.report} /></div>}
        </div>
      )}
      {item.copy && <p className="mt-1.5 text-[0.75rem] text-gray-400">Copy kept in {item.copy}</p>}
    </li>
  );
}

function SourceView({ source, data, threshold }) {
  const schedule = data.schedule;
  // The scheduler counts only OSM extractions and full Google refreshes
  const points = data.extractions
    .filter((item) => item.change_share != null && !item.baseline && (source === "osm" || item.kind?.startsWith("refresh") || !item.report))
    .map((item) => ({ key: item.extracted_at, when: item.extracted_at, share: item.change_share, changes: item.changes,
      records: item.records, decision: item.decision }))
    .reverse();
  return (
    <div className="flex flex-col gap-4">
      {schedule && (
        <p className="text-[0.875rem]">
          Next {SOURCES[source]} {source === "google" ? "refresh" : "extraction"}: <strong>{formatDay(schedule.next_due)}</strong> · every {plural(schedule.interval_days, "day")}
        </p>
      )}
      <Card title={`Records changed per ${source === "google" ? "refresh" : "extraction"}`}>
        <p className="-mt-2 mb-3 text-[0.8125rem] text-gray-500 dark:text-muted-dark">
          At or above the dashed {formatShare(threshold).replace(".0%", "%")} line the AI makes the next extraction come sooner; below it, later.
          {source === "google" && " Only full refreshes count; lookups for new restaurants on OpenStreetMap days are listed below but do not move Google's date."}
        </p>
        {points.length
          ? <ChangeShareChart points={points} threshold={threshold} />
          : <p className="py-6 text-center text-[0.8125rem] text-gray-500 dark:text-muted-dark">
              Nothing compared yet: the first {source === "google" ? "refresh" : "extraction"} is the starting point{schedule ? `, and the next is due ${formatDay(schedule.next_due)}` : ""}.
            </p>}
      </Card>
      <Card title="Every extraction, newest first">
        <ul>
          {data.extractions.map((item) => <ExtractionItem key={item.extracted_at} item={item} source={source} />)}
        </ul>
      </Card>
    </div>
  );
}

function Duplicates({ duplicates }) {
  if (!duplicates.dropped.length) {
    return <EmptyState title="No dropped duplicates" text="No two OpenStreetMap pins with the same name matched one Google place." />;
  }
  return (
    <Card title={`Dropped duplicate pins (${duplicates.dropped.length})`}>
      <p className="-mt-2 mb-3 text-[0.8125rem] text-gray-500 dark:text-muted-dark">
        The same shop mapped twice in OpenStreetMap: both pins have the same name and matched the same Google place, so the pin nearer
        Google's is kept and the other is left out. To keep a dropped one anyway, give it its own entry in src/reference/google_match_overrides.json by hand.
        List written {formatDateTime(duplicates.file_written)}.
      </p>
      <table className="w-full text-left text-[0.8125rem]">
        <thead>
          <tr className="border-b border-gray-200 text-[0.75rem] text-gray-500 dark:border-line-dark dark:text-muted-dark">
            <th className="py-2 pr-3 font-semibold">Dropped pin</th>
            <th className="py-2 pr-3 font-semibold">Kept pin</th>
            <th className="py-2 font-semibold">Google place</th>
          </tr>
        </thead>
        <tbody>
          {duplicates.dropped.map((item) => (
            <tr key={item.osm_id} className="border-b border-gray-100 align-top last:border-b-0 dark:border-line-dark">
              <td className="py-2 pr-3">
                <ExternalLinkText href={item.osm_map}>{item.osm_name}</ExternalLinkText>
                <span className="block text-gray-500 tabular-nums dark:text-muted-dark">{item.distance_to_google_m} m from Google's pin</span>
              </td>
              <td className="py-2 pr-3">
                {item.kept_osm_name}
                <span className="block text-gray-500 tabular-nums dark:text-muted-dark">{item.kept_distance_to_google_m} m from Google's pin</span>
              </td>
              <td className="py-2"><ExternalLinkText href={item.google_map}>{item.google_name}</ExternalLinkText></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

export default function HistoryTab() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [version, setVersion] = useState(0);
  const [view, setView] = useState("osm");

  useEffect(() => {
    let alive = true;
    getHistory().then((result) => { if (alive) { setData(result); setError(null); } }, (err) => { if (alive) setError(err); });
    return () => { alive = false; };
  }, [version]);

  if (error) return <div className="p-8"><ErrorBox error={error} onRetry={() => setVersion((v) => v + 1)} /></div>;
  if (!data) return <Loading />;

  return (
    <div className="mx-auto flex max-w-[64rem] flex-col gap-4 p-8">
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(SOURCES).map(([key, label]) => (
          <FilterChip key={key} active={view === key} onClick={() => setView(key)}>{label}</FilterChip>
        ))}
        <FilterChip active={view === "duplicates"} onClick={() => setView("duplicates")}>
          Dropped duplicates ({data.duplicates.dropped.length})
        </FilterChip>
      </div>
      {view === "duplicates"
        ? <Duplicates duplicates={data.duplicates} />
        : <SourceView source={view} data={data.sources[view]} threshold={data.change_threshold} />}
    </div>
  );
}
