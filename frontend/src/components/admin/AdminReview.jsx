import { Fragment, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, ChevronRight, FileText, Flag, Image, X } from "lucide-react";
import GeneralDialog from "../modals/GeneralDialog";
import { LocationPreview } from "../business/LocationPicker";
import FileViewer from "./FileViewer";
import { decideSubmission, getAdminSubmission, markField } from "../../api/businessApi";
import { flaggedIssues, formatDateTime, reviewProgress, reviewSections, tabOf } from "../../services/adminSubmissions";

// business_submission.status
const HEADER_PILL = {
  waiting: { label: "Pending review", tone: "info" },
  under_review: { label: "In review", tone: "info" },
  approved: { label: "Approved · added tonight", tone: "success" },
  live: { label: "Live on FoodSight", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
};
const REVIEWABLE = ["waiting", "under_review"];

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

// changed: the user changed this field in this resubmission; previousNote: what was flagged last time
function ReviewItem({ item, mark, readOnly, changed, previousNote, onMark, onNote, onNoteDone, onOpenFile, darkMode }) {
  const flagged = mark?.state === "flagged";
  const noteId = `note-${item.key}`;
  const showLabel = item.kind !== "file" && item.kind !== "hours";
  return (
    <div className={`admin-item${flagged ? " is-flagged" : ""}${item.kind === "file" ? " is-file" : ""}`}>
      <div className="admin-item-main">
        <div className="admin-item-body">
          {(changed || previousNote) && (
            <p className="admin-item-changed">
              {changed ? "Changed in this resubmission" : "Not changed"}
              {previousNote ? ` · flagged last time: ${previousNote}` : ""}
            </p>
          )}
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
              id={noteId} rows={2} value={mark.note} maxLength={500} placeholder="Tell the owner what to change"
              onChange={(event) => onNote(event.target.value)} onBlur={onNoteDone}
            />
          )}
        </div>
      )}
    </div>
  );
}

// Restaurants already on FoodSight within 100 m of the pin, alike names first: is this a duplicate?
function NearbyRestaurants({ nearby }) {
  if (!nearby?.length) return null;
  return (
    <section className="admin-section">
      <h2>Already on FoodSight near this pin</h2>
      {nearby.map((place) => (
        <div key={place.restaurantId} className="admin-item">
          <div className="admin-item-main">
            <div className="admin-item-body">
              <p className="admin-item-label">{place.distanceM} m away{place.source === "submitted" ? " · from a submission" : ""}</p>
              <p className="admin-item-value">{place.name}{place.address ? ` · ${place.address}` : ""}</p>
            </div>
            {place.similarName && <span className="admin-pill is-danger">Similar name</span>}
          </div>
        </div>
      ))}
    </section>
  );
}

export default function AdminReview() {
  const { id } = useParams();
  const { reloadSubmissions, setNotice, darkMode } = useOutletContext();
  const navigate = useNavigate();
  const location = useLocation();
  // The submission as last read or saved, for the id it was read for
  const [loaded, setLoaded] = useState({ id: null, state: "loading", submission: null });
  const loadState = loaded.id === id ? loaded.state : "loading";
  const submission = loaded.id === id ? loaded.submission : null;
  const setSubmission = (next) => setLoaded((previous) => ({ ...previous, submission: next }));
  // Flags whose note is still being written: saved once the note box is left with a note in it
  const [drafts, setDrafts] = useState({});
  const [stage, setStage] = useState("details");
  const [confirming, setConfirming] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    getAdminSubmission(id).then(
      (found) => { if (alive) setLoaded({ id, state: "ready", submission: found }); },
      (error) => { if (alive) setLoaded({ id, state: error.response?.status === 404 ? "missing" : "error", submission: null }); },
    );
    return () => { alive = false; };
  }, [id]);

  if (loadState !== "ready") {
    return (
      <div className="admin-card admin-panel admin-review">
        <nav className="admin-breadcrumb" aria-label="Breadcrumb"><Link to="/admin/submissions">Submissions</Link></nav>
        <p className="admin-empty">
          {loadState === "loading" ? "Loading the submission…"
            : loadState === "missing" ? "This submission does not exist." : "We could not load this submission. Reload the page to try again."}
        </p>
      </div>
    );
  }

  const { form } = submission;
  const readOnly = !REVIEWABLE.includes(submission.status);
  const backTab = location.state?.tab ?? tabOf(submission.status);
  const backTo = backTab === "waiting" ? "/admin/submissions" : `/admin/submissions?tab=${backTab}`;
  const wanted = new Set(submission.reviewFields);
  const sections = reviewSections(form)
    .map((section) => ({ ...section, items: section.items.filter((item) => wanted.has(item.key)) }))
    .filter((section) => section.items.length);
  // A decided submission was fully marked, so anything not flagged was checked
  const review = readOnly
    ? Object.fromEntries(sections.flatMap((section) => section.items).map((item) => [item.key, submission.review[item.key] ?? { state: "checked", note: "" }]))
    : { ...submission.review, ...drafts };
  const progress = reviewProgress(sections, review);
  const issues = flaggedIssues(sections, review);
  const pill = HEADER_PILL[submission.status] ?? HEADER_PILL.waiting;
  const changed = new Set(submission.changedFields);

  const save = async (key, state, note = "") => {
    try {
      setSubmission(await markField(submission.id, key, state, note));
      setDrafts((previous) => {
        const next = { ...previous };
        delete next[key];
        return next;
      });
      reloadSubmissions();
    } catch {
      setNotice("That mark could not be saved. Check your connection and try again.");
    }
  };
  const setMark = (key, state) => {
    if (state === "checked") save(key, "checked");
    else setDrafts((previous) => ({ ...previous, [key]: { state: "flagged", note: review[key]?.note ?? "" } }));
  };
  const setNote = (key, note) => setDrafts((previous) => ({ ...previous, [key]: { state: "flagged", note } }));
  const saveNote = (key) => {
    const draft = drafts[key];
    if (draft?.note.trim()) save(key, "flagged", draft.note.trim());
  };
  const openFile = (item) => setViewing({ title: item.label, file: item.file });

  const toDecision = async () => {
    // Flags written but not saved yet (the note box still focused)
    await Promise.all(Object.entries(drafts).filter(([, draft]) => draft.note.trim())
      .map(([key, draft]) => save(key, "flagged", draft.note.trim())));
    setStage("decision");
    document.querySelector(".admin-panel")?.scrollTo({ top: 0 });
  };

  const decide = async (decision) => {
    setBusy(true);
    try {
      await decideSubmission(submission.id, decision);
      setNotice(decision === "approved"
        ? `${form.businessName} was approved. It is added at tonight's update, and the owner was emailed.`
        : `${form.businessName} was rejected. The owner was emailed with the flagged items.`);
      reloadSubmissions();
      navigate(`/admin/submissions?tab=${decision}`);
    } catch {
      setNotice("The decision could not be saved. Reload the page and try again.");
      setConfirming(null);
    } finally {
      setBusy(false);
    }
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
          {submission.round > 1 ? `Resubmitted (round ${submission.round}) ` : "Submitted "}
          {formatDateTime(submission.submittedAt)}
          {submission.reviewer && ` · reviewer ${submission.reviewer}`}
        </p>
      </header>

      {stage === "details" ? (
        <>
          <NearbyRestaurants nearby={submission.nearby} />
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
                      changed={submission.round > 1 && changed.has(item.key)} previousNote={submission.previousFlags[item.key]}
                      onMark={(state) => setMark(item.key, state)}
                      onNote={(note) => setNote(item.key, note)}
                      onNoteDone={() => saveNote(item.key)}
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
              <button type="button" className="admin-btn admin-btn-primary" disabled={!progress.complete} onClick={toDecision}>
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
            {/* Any flagged issue means the submission can only be rejected (the backend checks the same). */}
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
            ? `${form.businessName} will be added to FoodSight at tonight's update. The owner is emailed at ${form.businessEmail} now.`
            : `The owner is emailed at ${form.businessEmail} with the ${issues.length} flagged item${issues.length === 1 ? "" : "s"}, and can fix them and resubmit.`}
          secondaryLabel="Cancel"
          primaryLabel={busy ? "Saving…" : confirming === "approved" ? "Approve" : "Reject"}
          onSecondary={() => setConfirming(null)}
          onClose={() => setConfirming(null)}
          onPrimary={() => !busy && decide(confirming)}
          destructive={confirming === "rejected"}
        />
      )}
    </div>
  );
}
