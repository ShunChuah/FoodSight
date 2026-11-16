import { Fragment, useState } from "react";
import { Link, Navigate, useLocation, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, ChevronRight, FileText, Flag, Image, X } from "lucide-react";
import GeneralDialog from "../modals/GeneralDialog";
import { LocationPreview } from "../business/LocationPicker";
import FileViewer from "./FileViewer";
import { flaggedIssues, formatDateTime, reviewProgress, reviewSections } from "../../services/adminSubmissions";
import { MOCK_REVIEWER } from "../../../data/mockAdminSubmissions";

const HEADER_PILL = {
  waiting: { label: "Pending review", tone: "info" },
  approved: { label: "Approved", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
};

function CheckToggle({ label, state, onChange, readOnly }) {
  return (
    <div className="admin-check" role="group" aria-label={label}>
      <button
        type="button" className={`admin-check-ok${state === "checked" ? " is-on" : ""}`}
        aria-pressed={state === "checked"} disabled={readOnly} onClick={() => onChange("checked")}
      >
        <Check aria-hidden="true" /> Checked
      </button>
      <button
        type="button" className={`admin-check-flag${state === "flagged" ? " is-on" : ""}`}
        aria-pressed={state === "flagged"} disabled={readOnly} onClick={() => onChange("flagged")}
      >
        <Flag aria-hidden="true" /> {state === "flagged" ? "Flagged" : "Flag"}
      </button>
    </div>
  );
}

function ItemValue({ item, onOpenFile, darkMode }) {
  if (item.kind === "link") {
    const href = /^https?:\/\//.test(item.value) ? item.value : `https://${item.value}`;
    return <a className="admin-link" href={href} target="_blank" rel="noreferrer">{item.value}</a>;
  }
  if (item.kind === "hours") {
    return (
      <dl className="admin-hours">
        {item.lines.map((line) => (
          <div key={line.label}><dt>{line.label}</dt><dd>{line.value}</dd></div>
        ))}
      </dl>
    );
  }
  if (item.kind === "map") {
    const { latitude, longitude } = item.location;
    return (
      <div className="admin-map-wrap">
        <LocationPreview location={item.location} darkMode={darkMode} className="admin-map" />
        <a className="admin-link" href={`https://www.google.com/maps?q=${latitude},${longitude}`} target="_blank" rel="noreferrer">
          Open in Google Maps
        </a>
      </div>
    );
  }
  if (item.kind === "file") {
    if (!item.file) return <p className="admin-item-value">{item.value}</p>;
    const Icon = item.file.type.startsWith("image/") ? Image : FileText;
    return (
      <div className="admin-file">
        <span className="admin-file-icon" aria-hidden="true"><Icon /></span>
        <span className="admin-file-text">
          <strong>{item.label}</strong>
          <span>{item.value}</span>
        </span>
        <button type="button" className="admin-btn admin-btn-outline admin-btn-small" aria-haspopup="dialog" onClick={() => onOpenFile(item)}>Open</button>
      </div>
    );
  }
  return <p className="admin-item-value">{item.value}</p>;
}

function ReviewItem({ item, mark, readOnly, onMark, onNote, onOpenFile, darkMode }) {
  const flagged = mark?.state === "flagged";
  const noteId = `note-${item.key}`;
  const showLabel = item.kind !== "file" && item.kind !== "hours";
  return (
    <div className={`admin-item${flagged ? " is-flagged" : ""}${item.kind === "file" ? " is-file" : ""}`}>
      <div className="admin-item-main">
        <div className="admin-item-body">
          {showLabel && <p className="admin-item-label">{item.label}</p>}
          <ItemValue item={item} onOpenFile={onOpenFile} darkMode={darkMode} />
        </div>
        <CheckToggle label={item.label} state={mark?.state} onChange={onMark} readOnly={readOnly} />
      </div>
      {flagged && (
        <div className="admin-note">
          <label htmlFor={noteId}>What needs fixing</label>
          {readOnly ? (
            <p id={noteId}>{mark.note}</p>
          ) : (
            <textarea
              id={noteId} rows={2} value={mark.note} placeholder="Tell the owner what to change"
              onChange={(event) => onNote(event.target.value)}
            />
          )}
        </div>
      )}
    </div>
  );
}

export default function AdminReview() {
  const { id } = useParams();
  const { submissions, updateSubmission, setNotice, darkMode } = useOutletContext();
  const navigate = useNavigate();
  const location = useLocation();
  const [stage, setStage] = useState("details");
  const [confirming, setConfirming] = useState(null);
  const [viewing, setViewing] = useState(null);
  const submission = submissions.find((item) => item.id === id);
  if (!submission) return <Navigate to="/admin/submissions" replace />;

  const { form } = submission;
  const readOnly = submission.status !== "waiting";
  const backTab = location.state?.tab ?? (readOnly ? submission.status : "waiting");
  const backTo = backTab === "waiting" ? "/admin/submissions" : `/admin/submissions?tab=${backTab}`;
  const sections = reviewSections(form);
  // A decision needs every item reviewed, so on decided submissions anything not flagged was checked.
  const review = readOnly
    ? Object.fromEntries(sections.flatMap((section) => section.items).map((item) => [item.key, submission.review[item.key] ?? { state: "checked", note: "" }]))
    : submission.review;
  const progress = reviewProgress(sections, review);
  const issues = flaggedIssues(sections, review);
  const pill = HEADER_PILL[submission.status];

  const setMark = (key, change) => updateSubmission(id, (current) => ({
    ...current,
    review: { ...current.review, [key]: { state: "checked", note: "", ...current.review[key], ...change } },
  }));
  const openFile = (item) => setViewing({ title: item.label, file: item.file });

  const decide = (status) => {
    updateSubmission(id, (current) => ({ ...current, status, decidedAt: new Date().toISOString(), decidedBy: MOCK_REVIEWER }));
    setNotice(`${form.businessName} was ${status}.`);
    navigate(`/admin/submissions?tab=${status}`);
  };

  return (
    <div className="admin-card admin-panel admin-review">
      <nav className="admin-breadcrumb" aria-label="Breadcrumb">
        <Link to={backTo}>Submissions</Link>
        <ChevronRight aria-hidden="true" />
        <span aria-current="page">{form.businessName}</span>
      </nav>

      <header className="admin-review-head">
        <div className="admin-review-title">
          <h1>{form.businessName}</h1>
          <span className={`admin-pill is-${pill.tone}`}>{pill.label}</span>
        </div>
        <p>
          Submitted {formatDateTime(submission.submittedAt)}
        </p>
      </header>

      {stage === "details" ? (
        <>
          {sections.map((section) => {
            const hasFlag = section.items.some((item) => review[item.key]?.state === "flagged");
            return (
              <section key={section.title} className={`admin-section${hasFlag ? " has-flag" : ""}`}>
                <h2>{section.title}</h2>
                {section.items.map((item, index) => (
                  <Fragment key={item.key}>
                    {item.group && item.group !== section.items[index - 1]?.group && (
                      <p className="admin-item-group">{item.group}</p>
                    )}
                    <ReviewItem
                      item={item} mark={review[item.key]} readOnly={readOnly} onOpenFile={openFile} darkMode={darkMode}
                      onMark={(state) => setMark(item.key, { state })}
                      onNote={(note) => setMark(item.key, { note })}
                    />
                  </Fragment>
                ))}
              </section>
            );
          })}

          {!readOnly && (
            <div className="admin-review-foot">
              <p className="admin-progress" aria-live="polite">
                {progress.done} of {progress.total} checked
                {progress.missingNotes > 0 && ` · ${progress.missingNotes} ${progress.missingNotes === 1 ? "flag needs" : "flags need"} a note`}
              </p>
              <button
                type="button" className="admin-btn admin-btn-primary" disabled={!progress.complete}
                onClick={() => {
                  setStage("decision");
                  document.querySelector(".admin-panel")?.scrollTo({ top: 0 });
                }}
              >
                Next <ArrowRight aria-hidden="true" />
              </button>
            </div>
          )}
        </>
      ) : (
        <section className="admin-section admin-decision">
          <h2>Decision</h2>
          <div className="admin-issues">
            <h3>Flagged issue{issues.length === 1 ? "" : "s"}</h3>
            {issues.length ? issues.map((issue) => (
              <div key={issue.key} className="admin-issue">
                <strong>{issue.section}</strong>
                <span className="admin-issue-field">{issue.label}</span>
                <p>{issue.note}</p>
              </div>
            )) : <p className="admin-issues-none">Nothing was flagged. Every item was checked.</p>}
          </div>
          <div className="admin-decision-actions">
            <button type="button" className="admin-btn admin-btn-outline" onClick={() => setStage("details")}>
              <ArrowLeft aria-hidden="true" /> Back
            </button>
            <span className="admin-spacer" />
            {/* Any flagged issue means the submission can only be rejected. */}
            {issues.length ? (
              <button type="button" className="admin-btn admin-btn-reject" onClick={() => setConfirming("rejected")}>
                <X aria-hidden="true" /> Reject
              </button>
            ) : (
              <button type="button" className="admin-btn admin-btn-approve" onClick={() => setConfirming("approved")}>
                <Check aria-hidden="true" /> Approve
              </button>
            )}
          </div>
        </section>
      )}

      {viewing && <FileViewer title={viewing.title} file={viewing.file} onClose={() => setViewing(null)} />}

      {confirming && (
        <GeneralDialog
          title={confirming === "approved" ? "Approve business" : "Reject business"}
          description={confirming === "approved"
            ? `${form.businessName} will be added to FoodSight and the owner will be emailed at ${form.businessEmail}.`
            : `The owner will be emailed at ${form.businessEmail}${issues.length ? " with the flagged issues" : ""}. This can't be undone.`}
          secondaryLabel="Cancel"
          primaryLabel={confirming === "approved" ? "Approve" : "Reject"}
          onSecondary={() => setConfirming(null)}
          onClose={() => setConfirming(null)}
          onPrimary={() => decide(confirming)}
          destructive={confirming === "rejected"}
        />
      )}
    </div>
  );
}
