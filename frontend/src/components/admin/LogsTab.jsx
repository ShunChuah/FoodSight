import { useEffect, useState } from "react";
import { CircleAlert, FileText, TriangleAlert } from "lucide-react";
import { getLogDay, getLogDays, getLogText } from "../../api/adminApi.js";
import { STAGE_LABELS, capitalise, formatDay, formatSize, plural, runLabel } from "../../services/adminFormat.js";
import { Badge, Card, EmptyState, ErrorBox, ListButton, ListScroll, Loading, SplitView } from "./AdminUi.jsx";

// Read only: data/logs, one file per day, split by the backend into runs (an update with its
// stages, or a stage run by hand) with their problem lines. Each run or stage can show its
// full text (at most 5,000 lines).

function ProblemBadges({ item }) {
  return (
    <>
      {item.errors > 0 && <Badge tone="red">{plural(item.errors, "error")}</Badge>}
      {item.warnings > 0 && <Badge tone="amber">{plural(item.warnings, "warning")}</Badge>}
    </>
  );
}

function Problems({ problems }) {
  if (!problems.length) return null;
  return (
    <ul className="mt-1.5 flex flex-col gap-1">
      {problems.map((problem) => (
        <li key={problem.line} className="flex gap-2 text-[0.8125rem]">
          {problem.level === "error"
            ? <CircleAlert className="mt-0.5 size-[0.875rem] shrink-0 text-red-600 dark:text-red-400" />
            : <TriangleAlert className="mt-0.5 size-[0.875rem] shrink-0 text-amber-600 dark:text-amber-400" />}
          <span className="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono text-[0.75rem]">{problem.text}</span>
          {problem.count > 1 && <span className="shrink-0 text-[0.75rem] font-semibold text-gray-500 dark:text-muted-dark">×{problem.count}</span>}
        </li>
      ))}
    </ul>
  );
}

function FullText({ day, start, end }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(null);
  const [error, setError] = useState(null);

  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (text) return;
    try {
      setText(await getLogText(day, start, end));
    } catch (err) {
      setError(err);
    }
  };

  return (
    <div className="mt-1.5">
      <button type="button" onClick={toggle} className="inline-flex cursor-pointer items-center gap-1 text-[0.75rem] font-semibold text-brand hover:underline">
        <FileText className="size-[0.875rem]" /> {open ? "Hide the full text" : `Show the full text (${plural(end - start + 1, "line")})`}
      </button>
      {open && error && <div className="mt-1.5"><ErrorBox error={error} /></div>}
      {open && !error && !text && <p className="mt-1.5 text-[0.75rem] text-gray-500">Loading…</p>}
      {open && text && (
        <div className="mt-1.5">
          {text.skipped > 0 && (
            <p className="mb-1 text-[0.75rem] text-gray-500 dark:text-muted-dark">
              The first {text.skipped.toLocaleString("en-GB")} lines are left out (the last 5,000 are shown); the whole log is data/logs/{day}.log.
            </p>
          )}
          <pre className="max-h-[28rem] overflow-auto rounded-[0.5rem] bg-zinc-900 p-3 font-mono text-[0.6875rem] leading-relaxed text-zinc-100">
            {text.lines.map((line, index) => {
              const number = text.start + index;
              const tone = / - (ERROR|CRITICAL) - |^Traceback/.test(line) ? "text-red-300" : / - WARNING - |^WARNING: /.test(line) ? "text-amber-300" : "";
              return (
                <span key={number} className={`block ${tone}`}>
                  <span className="mr-3 inline-block w-[3.5rem] select-none text-right text-zinc-500">{number}</span>{line}
                </span>
              );
            })}
          </pre>
        </div>
      )}
    </div>
  );
}

function Stage({ day, stage }) {
  return (
    <li className="border-t border-[#f0f0f1] py-2 first:border-t-0 dark:border-line-dark">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.8125rem] font-semibold">{STAGE_LABELS[stage.script] || stage.command}</span>
        {stage.args && <span className="text-[0.75rem] text-gray-500 dark:text-muted-dark">{stage.args}</span>}
        <span className="text-[0.75rem] text-gray-500 tabular-nums dark:text-muted-dark">
          {stage.open ? "no end line: cut off" : `${stage.started} · ${stage.duration}`}
        </span>
        <ProblemBadges item={stage} />
      </div>
      <Problems problems={stage.problems} />
      <FullText day={day} start={stage.first_line} end={stage.last_line} />
    </li>
  );
}

function Run({ day, run }) {
  const update = run.script === "run_update.py";
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.9375rem] font-bold tabular-nums">{run.started.slice(0, 5)}</span>
        <span className="text-[0.9375rem] font-bold">{runLabel(run)}</span>
        {!update && <Badge>run by hand</Badge>}
        {run.open
          ? <Badge tone="amber">Running now, or cut off</Badge>
          : <span className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">{run.duration}</span>}
        <ProblemBadges item={run} />
      </div>
      {update && run.did && !run.args.startsWith("--stat") && (
        <p className="mt-1 text-[0.8125rem] text-gray-600 dark:text-muted-dark">Why: {run.did}</p>
      )}
      {update && run.result && !run.args.startsWith("--stat") && (
        <p className="mt-0.5 text-[0.8125rem]">Result: {capitalise(run.result)}</p>
      )}
      <Problems problems={run.problems} />
      {run.stages.length > 0 && (
        <ul className="mt-2 rounded-[0.625rem] border border-[#f0f0f1] px-3 dark:border-line-dark">
          {run.stages.map((stage) => <Stage key={stage.first_line} day={day} stage={stage} />)}
        </ul>
      )}
      <FullText day={day} start={run.first_line} end={run.last_line} />

    </Card>
  );
}

export default function LogsTab({ day: chosenDay, onDay }) {
  const [days, setDays] = useState(null);
  const [daysError, setDaysError] = useState(null);
  const [version, setVersion] = useState(0);
  const [detail, setDetail] = useState(null);
  const [onlyProblems, setOnlyProblems] = useState(false);

  useEffect(() => {
    let alive = true;
    getLogDays().then((data) => { if (alive) { setDays(data.days); setDaysError(null); } }, (err) => { if (alive) setDaysError(err); });
    return () => { alive = false; };
  }, [version]);

  const current = days?.some((d) => d.day === chosenDay) ? chosenDay : days?.[0]?.day;

  useEffect(() => {
    if (!current) return undefined;
    let alive = true;
    getLogDay(current).then(
      (data) => { if (alive) setDetail({ day: current, data }); },
      (error) => { if (alive) setDetail({ day: current, error }); },
    );
    return () => { alive = false; };
  }, [current, version]);

  if (daysError) return <ErrorBox error={daysError} onRetry={() => setVersion((v) => v + 1)} />;
  if (!days) return <Loading />;
  if (!days.length) return <EmptyState title="No logs yet" text="Every pipeline run writes its output to data/logs, one file per day." />;

  const shown = detail?.day === current ? detail : null;
  const runs = shown?.data?.runs || [];
  const visible = onlyProblems ? runs.filter((run) => run.errors || run.warnings) : runs;

  return (
    <SplitView
      list={(
        <>
          <div className="admin-split-tools">
            <p className="admin-split-note">{plural(days.length, "day")} of logs, newest first</p>
          </div>
          <ListScroll>
            {days.map((d) => (
              <ListButton key={d.day} selected={d.day === current} onClick={() => onDay(d.day)}>
                <div className="flex items-center justify-between gap-2">
                  <p className="admin-row-title">{formatDay(d.day)}</p>
                  <span className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">{formatSize(d.size)}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">{plural(d.runs, "run")}</span>
                  <ProblemBadges item={d} />
                </div>
              </ListButton>
            ))}
          </ListScroll>
        </>
      )}
    >
      {!shown && <Loading />}
      {shown?.error && <div className="p-6"><ErrorBox error={shown.error} /></div>}
      {shown?.data && (
        <div key={current} className="flex flex-col gap-4 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-[1.25rem] font-bold">{formatDay(current)}</h2>
              <p className="text-[0.8125rem] text-gray-500 dark:text-muted-dark">
                {plural(runs.length, "run")} · {shown.data.lines.toLocaleString("en-GB")} lines · data/logs/{current}.log
              </p>
            </div>
            <label className="inline-flex cursor-pointer items-center gap-2 text-[0.8125rem]">
              <input type="checkbox" checked={onlyProblems} onChange={(event) => setOnlyProblems(event.target.checked)} className="size-[1rem] accent-brand" />
              Only runs with problems
            </label>
          </div>
          {shown.data.loose_problems.length > 0 && (
            <Card title="Outside any run"><Problems problems={shown.data.loose_problems} /></Card>
          )}
          {visible.map((run) => <Run key={run.first_line} day={current} run={run} />)}
          {!visible.length && <p className="text-[0.875rem] text-gray-500 dark:text-muted-dark">No run with problems on this day.</p>}
        </div>
      )}
    </SplitView>
  );
}
