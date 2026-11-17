import { useState } from "react";
import { Link, useNavigate, useOutletContext, useSearchParams } from "react-router-dom";
import { DateInput, SelectInput } from "../business/BusinessFields";
import { HALAL_STATUSES, RESTAURANT_TYPES } from "../../services/businessForm";
import { formatPhone } from "../../services/businessReview";
import {
  EMPTY_FILTERS, REVIEW_STATUS, formatDay, reviewStatus, shortArea, tabOf, visibleSubmissions, waitingTime,
} from "../../services/adminSubmissions";
import { SearchBox } from "./AdminUi.jsx";

const TABS = [
  { id: "waiting", label: "Waiting" },
  { id: "approved", label: "Approved" },
  { id: "rejected", label: "Rejected" },
];

const ALL = (label) => ({ value: "", label });
const REVIEW_OPTIONS = [ALL("All status"), ...["not_started", "in_progress"].map((value) => ({ value, label: REVIEW_STATUS[value].label }))];
// The areas the submissions are in (each found from its pin), A to Z
const areaOptions = (submissions) => [
  ALL("All areas"),
  ...[...new Set(submissions.map((submission) => submission.form.area).filter(Boolean))].sort()
    .map((area) => ({ value: area, label: shortArea(area) })),
];
const HALAL_OPTIONS = [ALL("All status"), ...HALAL_STATUSES];
const SORT_OPTIONS = [{ value: "oldest", label: "Oldest first" }, { value: "newest", label: "Newest first" }];

const typeLabel = (value) => RESTAURANT_TYPES.find((type) => type.value === value)?.label ?? "Restaurant";

function StatusPill({ status }) {
  const { label, tone } = REVIEW_STATUS[status];
  return <span className={`admin-pill is-${tone}`}>{label}</span>;
}

export default function AdminSubmissions() {
  const { submissions, submissionsInfo } = useOutletContext();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((item) => item.id === params.get("tab")) ? params.get("tab") : "waiting";
  const [draft, setDraft] = useState(EMPTY_FILTERS);
  // Filters apply on Apply; search applies as you type.
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [search, setSearch] = useState("");

  const isWaiting = tab === "waiting";
  const rows = visibleSubmissions(submissions, tab, filters, search);
  const waitingCount = submissions.filter((submission) => tabOf(submission.status) === "waiting").length;
  const set = (field) => (value) => setDraft((previous) => ({ ...previous, [field]: value }));
  const reset = () => {
    setDraft(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
  };
  const openTab = (id) => {
    setParams(id === "waiting" ? {} : { tab: id });
    reset();
  };
  const open = (submission) => navigate(`/admin/submissions/${submission.id}`, { state: { tab } });

  return (
    <div className="admin-card admin-panel">
      <h1>Submissions</h1>

      <div className="admin-tabs" role="tablist" aria-label="Submission status">
        {TABS.map((item) => (
          <button
            key={item.id} type="button" role="tab" aria-selected={tab === item.id}
            className={`admin-tab${tab === item.id ? " is-active" : ""}`} onClick={() => openTab(item.id)}
          >
            {item.label}
            {item.id === "waiting" && <span className="admin-tab-count">{waitingCount}</span>}
          </button>
        ))}
      </div>

      <form
        className="admin-filters"
        onSubmit={(event) => {
          event.preventDefault();
          setFilters(draft);
        }}
      >
        <DateInput id="filter-date" label="Date submitted" value={draft.date} onChange={set("date")} />
        {isWaiting && (
          <SelectInput id="filter-review" label="Review status" value={draft.reviewStatus} onChange={set("reviewStatus")} options={REVIEW_OPTIONS} />
        )}
        <SelectInput id="filter-area" label="Area" value={draft.area} onChange={set("area")} options={areaOptions(submissions)} />
        <SelectInput id="filter-halal" label="Halal status" value={draft.halalStatus} onChange={set("halalStatus")} options={HALAL_OPTIONS} />
        <SelectInput id="filter-sort" label="Sort by" value={draft.sort} onChange={set("sort")} options={SORT_OPTIONS} />
        <div className="admin-filter-actions">
          <button type="submit" className="admin-btn admin-btn-primary">Apply</button>
          <button type="button" className="admin-btn admin-btn-muted" onClick={reset}>Reset</button>
        </div>
      </form>

      {/* The admin pages' one search box (the same as on the pipeline pages) */}
      <SearchBox
        className="my-6" placeholder="Search business, manager or SSM no." aria-label="Search submissions"
        value={search} onChange={(event) => setSearch(event.target.value)}
      />

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th scope="col">Business</th>
              {isWaiting && <th scope="col">Review status</th>}
              <th scope="col">Store manager</th>
              <th scope="col">Submitted</th>
              <th scope="col">{isWaiting ? "Waiting" : tab === "approved" ? "Approved" : "Rejected"}</th>
              <th scope="col"><span className="sr-only">Action</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((submission) => {
              const { form } = submission;
              const waited = waitingTime(submission.submittedAt);
              return (
                <tr key={submission.id}>
                  <td>
                    <Link className="admin-row-title" to={`/admin/submissions/${submission.id}`} state={{ tab }}>{form.businessName}</Link>
                    <span className="admin-row-sub">{typeLabel(form.restaurantType)} · {shortArea(form.area)}</span>
                  </td>
                  {isWaiting && <td><StatusPill status={reviewStatus(submission)} /></td>}
                  <td>
                    <span className="admin-row-title">{form.managerName}</span>
                    <span className="admin-row-sub">{formatPhone(form.managerPhone)}</span>
                  </td>
                  <td>{formatDay(submission.submittedAt)}</td>
                  <td className={isWaiting && waited.overdue ? "admin-overdue" : undefined}>
                    {isWaiting ? waited.text : formatDay(submission.decidedAt)}
                  </td>
                  <td className="admin-row-action">
                    <button type="button" className="admin-btn admin-btn-outline" onClick={() => open(submission)}>
                      {isWaiting ? "Review" : "View"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {submissionsInfo?.state === "loading" && <p className="admin-empty">Loading submissions…</p>}
        {submissionsInfo?.state === "error" && <p className="admin-empty">We could not load the submissions. Reload the page to try again.</p>}
        {submissionsInfo?.state === "ready" && rows.length === 0 && <p className="admin-empty">No submissions match these filters.</p>}
      </div>
    </div>
  );
}
