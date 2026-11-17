import { ArrowRight, CircleCheck, Clock, TriangleAlert } from "lucide-react";
import { capitalise, formatDateTime, formatDay, formatTimeRange, plural, shortReason } from "../../services/adminFormat.js";
import { Badge, Card, ErrorBox, Loading } from "./AdminUi.jsx";
import { PIPELINE_PAGES } from "./pipelinePages.js";

// What needs the admin, what is waiting for tonight's update, and how the automatic
// update is doing (data/state, data/review). Kept short on purpose (2026-11-18): the
// details are on Update history and Logs.

function OpenLink({ onClick, children = "Open" }) {
  return (
    <button type="button" onClick={onClick} className="inline-flex shrink-0 cursor-pointer items-center gap-1 text-[0.8125rem] font-semibold text-brand hover:underline">
      {children} <ArrowRight className="size-[0.875rem]" />
    </button>
  );
}

function OkIcon({ ok, className = "" }) {
  return ok
    ? <CircleCheck className={`size-[1.125rem] shrink-0 text-emerald-600 dark:text-emerald-400 ${className}`} />
    : <TriangleAlert className={`size-[1.125rem] shrink-0 text-amber-600 dark:text-amber-400 ${className}`} />;
}

// A tile like the submissions overview's, with the icon of the page's sidebar item
function DecisionTile({ page, value, note, waitingText, onOpen }) {
  const { Icon, label } = PIPELINE_PAGES.find((p) => p.id === page);
  return (
    <div className="admin-card admin-stat is-top">
      <span className="admin-stat-icon is-brand" aria-hidden="true"><Icon /></span>
      <div className="min-w-0 flex-1">
        <p className="admin-stat-label">{label}</p>
        <p className="admin-stat-value">{value}</p>
        <p className="admin-stat-note">{note}</p>
        {waitingText && (
          <p className="mt-2 inline-flex items-center gap-1.5 text-[0.8125rem] text-amber-700 dark:text-amber-300">
            <Clock className="size-[0.875rem] shrink-0" /> {waitingText}
          </p>
        )}
      </div>
      <span className="self-start"><OpenLink onClick={onOpen} /></span>
    </div>
  );
}

// A tile like the submissions overview's "Restaurants on FoodSight", without its icon: the
// label in capitals, then the main value in big type
function UpdateTile({ label, children }) {
  return (
    <div className="admin-card admin-stat is-top is-update">
      <div className="min-w-0 flex-1">
        <p className="admin-stat-label">{label}</p>
        {children}
      </div>
    </div>
  );
}

// The next date, the interval, and the scheduler's reason without its consequence
// (the whole reason on hover, and on Update history)
function ScheduleTile({ label, entry }) {
  return (
    <UpdateTile label={label}>
      {entry ? (
        <>
          <p className="admin-stat-value is-date">{formatDay(entry.next_due)}</p>
          <p className="admin-stat-note">Every {plural(entry.interval_days, "day")}</p>
          {entry.reason && (
            <p className="mt-3.5 text-[0.8125rem] leading-[1.7]" title={entry.reason}>
              {entry.decided_by === "ai" && <span className="font-semibold">AI: </span>}
              {shortReason(entry.reason)}
            </p>
          )}
        </>
      ) : <p className="admin-stat-note">No schedule yet.</p>}
    </UpdateTile>
  );
}

function LastRunTile({ last, runningSince, unfinished, onOpenLog }) {
  const warnings = last?.warnings || [];
  // A run that stopped says so in its result; the bookmark line is for a run cut off from outside
  const saysStopped = unfinished && last?.result?.startsWith(`stopped at stage ${unfinished.stage}`);
  return (
    <UpdateTile label="Last run">
      {last ? (
        <>
          <p className="admin-stat-value is-text">
            <OkIcon ok={last.result === "all stages done"} className="mt-[0.1875rem]" /> {capitalise(last.result)}
          </p>
          <p className="admin-stat-note">{formatTimeRange(last.started, last.finished)}</p>
          {runningSince && <div className="mt-3.5"><Badge tone="blue">Running since {formatDateTime(runningSince)}</Badge></div>}
          <p className="mt-3.5 flex flex-wrap items-center gap-x-2 text-[0.8125rem]">
            {warnings.length > 0 && (
              <>
                <span className="font-semibold text-amber-700 dark:text-amber-300">{plural(warnings.length, "warning")}</span>
                <span aria-hidden="true" className="text-gray-400 dark:text-muted-dark">·</span>
              </>
            )}
            <OpenLink onClick={onOpenLog}>Open its log</OpenLink>
          </p>
        </>
      ) : <p className="admin-stat-note">No run yet.</p>}
      {unfinished && !saysStopped && (
        <p className="mt-3.5 text-[0.8125rem] leading-[1.7] text-amber-700 dark:text-amber-300">
          Stopped at stage {unfinished.stage} ({unfinished.error}); the next run continues from it.
        </p>
      )}
    </UpdateTile>
  );
}

// One line per check: its name, then how it is
function StatusRow({ ok, title, detail }) {
  return (
    <li className="flex items-start gap-3 border-b border-[#f0f0f1] py-2.5 text-[0.875rem] first:pt-0 last:border-b-0 last:pb-0 dark:border-line-dark">
      <OkIcon ok={ok} className="mt-[0.0625rem]" />
      <span className="w-[11rem] shrink-0 font-semibold">{title}</span>
      <span className="min-w-0 flex-1 text-gray-500 dark:text-muted-dark">{detail}</span>
    </li>
  );
}

export default function OverviewTab({ overview, error, onRetry, onOpenTab }) {
  if (error) return <ErrorBox error={error} onRetry={onRetry} />;
  if (!overview) return <Loading />;
  const { google_matches: google, removed_restaurants: removed, nearby_exclusions: exclusions } = overview;
  const last = overview.last_run;
  const ai = overview.ai_failed;
  const invalid = overview.validation_invalid;
  const graphInvalid = overview.graph_invalid;
  const graph = overview.graph_waiting;
  const invalidCount = invalid.restaurants + invalid.areas + invalid.nearby_places;
  const aiMissing = [
    ai.restaurants > 0 && `${plural(ai.restaurants, "restaurant")} without an AI profile`,
    ai.reviews > 0 && `${plural(ai.reviews, "review")} without a sentiment`,
  ].filter(Boolean);
  const invalidParts = [[invalid.restaurants, "restaurant"], [invalid.areas, "section"], [invalid.nearby_places, "nearby place"]]
    .filter(([count]) => count > 0).map(([count, word]) => plural(count, word));

  return (
    <div className="flex flex-col gap-8">
      <section>
        <h2 className="mb-4 text-[1.125rem] font-bold">Needs your decision</h2>
        <div className="admin-stats">
          <DecisionTile page="google" value={google.waiting_decision} onOpen={() => onOpenTab("google")}
            note={google.waiting_decision ? "waiting for your decision" : "nothing to check"}
            waitingText={google.waiting_update > 0 && `${google.waiting_update} decided, waiting for tonight's update`} />
          <DecisionTile page="removed" value={removed.waiting_decision} onOpen={() => onOpenTab("removed")}
            note={removed.waiting_decision ? "waiting for your decision" : "nothing removed from OpenStreetMap"}
            waitingText={removed.waiting_update > 0 && `${removed.waiting_update} decided, waiting for tonight's update`} />
          <DecisionTile page="nearby" value={exclusions.total} onOpen={() => onOpenTab("nearby")}
            note="places excluded from the counts"
            waitingText={exclusions.waiting_update > 0 && `${exclusions.waiting_update} still counted until tonight's update`} />
        </div>
      </section>

      <section>
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-[1.125rem] font-bold">Automatic updates</h2>
          <OpenLink onClick={() => onOpenTab("history")}>See the update history</OpenLink>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <LastRunTile last={last} runningSince={overview.running_since} unfinished={overview.unfinished}
            onOpenLog={() => onOpenTab("logs", { day: last.started.slice(0, 10) })} />
          <ScheduleTile label="Next OSM extraction" entry={overview.schedule.osm} />
          <ScheduleTile label="Next Google refresh" entry={overview.schedule.google} />
        </div>
      </section>

      <section>
        <h2 className="mb-4 text-[1.125rem] font-bold">Handled without you</h2>
        <Card>
          <ul>
            <StatusRow ok={!ai.restaurants && !ai.reviews} title="AI answers"
              detail={ai.restaurants || ai.reviews
                ? `${aiMissing.join(" and ")} yet. The AI is asked again every night.`
                : "Every restaurant has its AI profile, and every review has its sentiment (positive, mixed, neutral or negative)."} />
            <StatusRow ok={!overview.address_failed} title="Address lookups"
              detail={overview.address_failed
                ? `${plural(overview.address_failed, "restaurant")} without an address; looked up again at the next merging.`
                : "None failed."} />
            <StatusRow ok={!invalidCount} title="Validation"
              detail={invalidCount
                ? `${invalidParts.join(", ").replace(/, ([^,]*)$/, " and $1")} rejected; needs a review.`
                : "Nothing rejected."} />
            <StatusRow ok={!graphInvalid.nodes && !graphInvalid.relationships} title="Knowledge graph check"
              detail={graphInvalid.nodes || graphInvalid.relationships
                ? `${plural(graphInvalid.nodes, "node")} and ${plural(graphInvalid.relationships, "relationship")} rejected; needs a review.`
                : "Nothing rejected."} />
            <StatusRow ok={!graph.changes && !graph.rebuild_clusters} title="Knowledge graph copy"
              detail={graph.changes || graph.rebuild_clusters
                ? `${graph.changes ? plural(graph.changes, "change") : "New clusters"} waiting to be copied to Neo4j; start Neo4j Desktop and the next run copies them.`
                : "Neo4j matches the database."} />
          </ul>
        </Card>
      </section>
    </div>
  );
}
