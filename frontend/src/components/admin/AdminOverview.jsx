import { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { ArrowRight, ArrowUp, Check, Clock3, Loader, Utensils, X } from "lucide-react";
import { Dropdown } from "../business/BusinessFields";
import { decidedWithin, reviewStatus, weekStarts } from "../../services/adminSubmissions";
import { MOCK_GRAPH_RESTAURANTS, MOCK_WEEKLY_SUBMISSIONS } from "../../../data/mockAdminSubmissions";

const RANGES = [
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 90, label: "Last 90 days" },
];

function StatTile({ label, value, note, tone, Icon }) {
  return (
    <div className="admin-card admin-stat">
      <span className={`admin-stat-icon is-${tone}`} aria-hidden="true"><Icon /></span>
      <div>
        <p className="admin-stat-label">{label}</p>
        <p className="admin-stat-value">{value}</p>
        {note && <p className="admin-stat-note">{note}</p>}
      </div>
    </div>
  );
}

function WeeklyChart({ counts }) {
  const [hovered, setHovered] = useState(null);
  const weeks = weekStarts(counts.length);
  const top = Math.max(10, Math.ceil(Math.max(...counts) / 10) * 10);
  const ticks = Array.from({ length: top / 5 + 1 }, (_, index) => index * 5);
  const label = (date) => date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });

  return (
    <section className="admin-card admin-chart" aria-labelledby="weekly-title">
      <h2 id="weekly-title">New submissions per week</h2>
      <div className="admin-chart-plot">
        <div className="admin-chart-grid" aria-hidden="true">
          {ticks.map((tick) => (
            <div key={tick} className="admin-chart-line" style={{ bottom: `${(tick / top) * 100}%` }}>
              {tick % 10 === 0 && <span>{tick}</span>}
            </div>
          ))}
        </div>
        <ol className="admin-chart-bars">
          {counts.map((count, index) => {
            const isLast = index === counts.length - 1;
            return (
              <li
                key={weeks[index].toISOString()}
                tabIndex={0}
                aria-label={`Week of ${label(weeks[index])}: ${count} submissions`}
                onMouseEnter={() => setHovered(index)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(index)}
                onBlur={() => setHovered(null)}
              >
                <div className="admin-chart-bar" style={{ height: `${(count / top) * 100}%` }}>
                  {(isLast || hovered === index) && <span className="admin-chart-value">{count}</span>}
                  {hovered === index && (
                    <span className="admin-chart-tip" role="tooltip">
                      Week of {label(weeks[index])}<strong>{count} submissions</strong>
                    </span>
                  )}
                </div>
                <span className="admin-chart-week">{label(weeks[index])}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

export default function AdminOverview() {
  const { submissions } = useOutletContext();
  const navigate = useNavigate();
  const [range, setRange] = useState(30);
  const rangeLabel = RANGES.find((option) => option.value === range).label;

  const waiting = submissions.filter((submission) => submission.status === "waiting");
  const notStarted = waiting.filter((submission) => reviewStatus(submission) === "not_started").length;
  const approved = decidedWithin(submissions, "approved", range);
  const rejected = decidedWithin(submissions, "rejected", range);
  const oldest = [...waiting].sort((a, b) => new Date(a.submittedAt) - new Date(b.submittedAt))[0];

  return (
    <div className="admin-card admin-panel admin-overview">
      <header className="admin-overview-head">
        <h1>Overview</h1>
        <div className="admin-overview-actions">
          <Dropdown
            id="overview-range" className="admin-range" ariaLabel="Date range"
            value={range} options={RANGES} onChange={setRange}
          />
          <button
            type="button" className="admin-btn admin-btn-primary" disabled={!oldest}
            onClick={() => navigate(`/admin/submissions/${oldest.id}`)}
          >
            Start reviewing <ArrowRight aria-hidden="true" />
          </button>
        </div>
      </header>

      <div className="admin-stats">
        <StatTile label="Not started" value={notStarted} tone="neutral" Icon={Clock3} />
        <StatTile label="In progress" value={waiting.length - notStarted} tone="info" Icon={Loader} />
        <StatTile label="Approved" value={approved} note={rangeLabel} tone="success" Icon={Check} />
        <StatTile label="Rejected" value={rejected} note={rangeLabel} tone="danger" Icon={X} />
      </div>

      <div className="admin-card admin-graph-total">
        <span className="admin-stat-icon is-brand" aria-hidden="true"><Utensils /></span>
        <div>
          <p className="admin-stat-label">Total restaurants in knowledge graph</p>
          <p className="admin-stat-value">
            {MOCK_GRAPH_RESTAURANTS.toLocaleString("en-US")} <small>Restaurant nodes</small>
          </p>
        </div>
        <span className="admin-growth">
          <ArrowUp aria-hidden="true" /> +{approved} in the {rangeLabel.toLowerCase()}
        </span>
      </div>

      <WeeklyChart counts={MOCK_WEEKLY_SUBMISSIONS} />
    </div>
  );
}
