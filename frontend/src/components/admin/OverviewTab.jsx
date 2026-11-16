import { ArrowRight, CircleCheck, Clock, TriangleAlert } from "lucide-react";
import { capitalise, formatDateTime, formatDay, plural } from "../../services/adminFormat.js";
import { Badge, Card, ErrorBox, Loading } from "./AdminUi.jsx";

// What needs the admin, what is waiting for tonight's update, and how the automatic
// update is doing (data/state, data/review).

function DecisionCard({ title, waiting, decided, decidedText, emptyText, onOpen }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[0.9375rem] font-bold">{title}</h3>
        <button type="button" onClick={onOpen} className="inline-flex cursor-pointer items-center gap-1 text-[0.8125rem] font-semibold text-brand hover:underline">
          Open <ArrowRight className="size-[0.875rem]" />
        </button>
      </div>
      <p className="mt-3 text-[2rem] leading-none font-bold">{waiting}</p>
      <p className="mt-1 text-[0.8125rem] text-gray-500 dark:text-muted-dark">{waiting ? "waiting for your decision" : emptyText}</p>
      {decided > 0 && (
        <p className="mt-3 inline-flex items-center gap-1.5 text-[0.8125rem] text-amber-700 dark:text-amber-300">
          <Clock className="size-[0.875rem]" /> {decided} {decidedText}, waiting for tonight's update
        </p>
      )}
    </Card>
  );
}

function ScheduleCard({ title, entry }) {
  if (!entry) return <Card title={title}><p className="text-[0.875rem]">No schedule yet.</p></Card>;
  return (
    <Card title={title}>
      <p className="text-[1.25rem] font-bold">{formatDay(entry.next_due)}</p>
      <p className="mt-1 text-[0.8125rem] text-gray-500 dark:text-muted-dark">
        Every {plural(entry.interval_days, "day")} · last on {formatDateTime(entry.last_extraction)} · set by {entry.decided_by === "ai" ? "the AI" : entry.decided_by}
      </p>
      {entry.reason && <p className="mt-2 text-[0.8125rem]">{entry.reason}</p>}
    </Card>
  );
}

function StatusRow({ ok, title, detail }) {
  return (
    <li className="flex items-start gap-3 border-b border-gray-100 py-2.5 last:border-b-0 dark:border-line-dark">
      {ok
        ? <CircleCheck className="mt-0.5 size-[1.125rem] shrink-0 text-emerald-600 dark:text-emerald-400" />
        : <TriangleAlert className="mt-0.5 size-[1.125rem] shrink-0 text-amber-600 dark:text-amber-400" />}
      <div>
        <p className="text-[0.875rem] font-semibold">{title}</p>
        <p className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">{detail}</p>
      </div>
    </li>
  );
}

export default function OverviewTab({ overview, error, onRetry, onOpenTab }) {
  if (error) return <div className="p-8"><ErrorBox error={error} onRetry={onRetry} /></div>;
  if (!overview) return <Loading />;
  const { google_matches: google, removed_restaurants: removed, nearby_exclusions: exclusions } = overview;
  const last = overview.last_run;
  const ai = overview.ai_failed;
  const invalid = overview.validation_invalid;
  const graphInvalid = overview.graph_invalid;
  const graph = overview.graph_waiting;
  const invalidCount = invalid.restaurants + invalid.areas + invalid.nearby_places;

  return (
    <div className="mx-auto flex max-w-[80rem] flex-col gap-8 p-8">
      <section>
        <h2 className="mb-3 text-[1rem] font-bold">Needs your decision</h2>
        <div className="grid grid-cols-3 gap-4">
          <DecisionCard title="Google matches" waiting={google.waiting_decision} decided={google.waiting_update}
            decidedText="decided" emptyText="nothing to check" onOpen={() => onOpenTab("google")} />
          <DecisionCard title="Removed restaurants" waiting={removed.waiting_decision} decided={removed.waiting_update}
            decidedText="decided" emptyText="nothing removed from OpenStreetMap" onOpen={() => onOpenTab("removed")} />
          <Card>
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-[0.9375rem] font-bold">Nearby places</h3>
              <button type="button" onClick={() => onOpenTab("nearby")} className="inline-flex cursor-pointer items-center gap-1 text-[0.8125rem] font-semibold text-brand hover:underline">
                Open <ArrowRight className="size-[0.875rem]" />
              </button>
            </div>
            <p className="mt-3 text-[2rem] leading-none font-bold">{exclusions.total}</p>
            <p className="mt-1 text-[0.8125rem] text-gray-500 dark:text-muted-dark">places excluded from the counts</p>
            {exclusions.waiting_update > 0 && (
              <p className="mt-3 inline-flex items-center gap-1.5 text-[0.8125rem] text-amber-700 dark:text-amber-300">
                <Clock className="size-[0.875rem]" /> {exclusions.waiting_update} still counted until tonight's update
              </p>
            )}
          </Card>
        </div>
        <p className="mt-3 text-[0.8125rem] text-gray-500 dark:text-muted-dark">
          Decisions are written into the files in src/reference and take effect in the nightly update at 00:00 (the laptop must be on).
          Until then you can still change or undo them.
        </p>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-[1rem] font-bold">Automatic updates</h2>
          <button type="button" onClick={() => onOpenTab("history")} className="inline-flex cursor-pointer items-center gap-1 text-[0.8125rem] font-semibold text-brand hover:underline">
            See the update history <ArrowRight className="size-[0.875rem]" />
          </button>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <ScheduleCard title="Next OpenStreetMap extraction" entry={overview.schedule.osm} />
          <ScheduleCard title="Next Google refresh" entry={overview.schedule.google} />
          <Card title="Last run" action={overview.running_since && <Badge tone="blue">Running since {formatDateTime(overview.running_since)}</Badge>}>
            {last ? (
              <>
                <p className="text-[0.875rem] font-semibold">{formatDateTime(last.started)} – {formatDateTime(last.finished)}</p>
                <p className="mt-1 text-[0.8125rem] text-gray-500 dark:text-muted-dark">Did: {last.did}</p>
                <p className="mt-1 text-[0.8125rem]">{capitalise(last.result)}</p>
                {(last.warnings || []).map((text) => (
                  <p key={text} className="mt-2 flex gap-1.5 text-[0.8125rem] text-amber-700 dark:text-amber-300">
                    <TriangleAlert className="mt-0.5 size-[0.875rem] shrink-0" /> {text}
                  </p>
                ))}
                <button type="button" onClick={() => onOpenTab("logs", { day: last.started.slice(0, 10) })}
                  className="mt-3 inline-flex cursor-pointer items-center gap-1 text-[0.8125rem] font-semibold text-brand hover:underline">
                  Open its log <ArrowRight className="size-[0.875rem]" />
                </button>
              </>
            ) : <p className="text-[0.875rem]">No run yet.</p>}
            {overview.unfinished && (
              <p className="mt-2 text-[0.8125rem] text-amber-700 dark:text-amber-300">
                Stopped at stage {overview.unfinished.stage} ({overview.unfinished.error}); the next run continues from it.
              </p>
            )}
          </Card>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-[1rem] font-bold">Handled without you</h2>
        <Card>
          <ul>
            <StatusRow ok={!ai.restaurants && !ai.reviews} title="AI answers"
              detail={ai.restaurants || ai.reviews
                ? `${plural(ai.restaurants, "restaurant")} and ${plural(ai.reviews, "review")} have no AI answer yet. They are asked again every night.`
                : "Every restaurant and review has its AI answer."} />
            <StatusRow ok={!overview.address_failed} title="Address lookups"
              detail={overview.address_failed
                ? `${plural(overview.address_failed, "restaurant")} without an address: looked up again at the next merging.`
                : "No failed address lookups."} />
            <StatusRow ok={!invalidCount} title="Validation"
              detail={invalidCount
                ? `${invalid.restaurants} restaurants, ${invalid.areas} sections and ${invalid.nearby_places} nearby places were rejected (data/review/validation_invalid.json). Fixing them needs a developer.`
                : `Nothing rejected (checked ${formatDateTime(invalid.checked_at)}).`} />
            <StatusRow ok={!graphInvalid.nodes && !graphInvalid.relationships} title="Knowledge graph check"
              detail={graphInvalid.nodes || graphInvalid.relationships
                ? `${graphInvalid.nodes} nodes and ${graphInvalid.relationships} relationships were rejected (data/review/graph_invalid.json). Fixing them needs a developer.`
                : `Nothing rejected (checked ${formatDateTime(graphInvalid.checked_at)}).`} />
            <StatusRow ok={!graph.changes && !graph.rebuild_clusters} title="Knowledge graph copy"
              detail={graph.changes || graph.rebuild_clusters
                ? `${plural(graph.changes, "change")} not copied to Neo4j yet. Open the FoodSight instance in Neo4j Desktop; the next run copies them.`
                : "Neo4j matches the database."} />
          </ul>
        </Card>
      </section>
    </div>
  );
}
