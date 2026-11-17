import { useState } from "react";
import { Check, ChevronDown, Store, X } from "lucide-react";
import Logo from "../../assets/logo.svg";
import DarkModeLogo from "../../assets/logo-dark.svg";
import { asFlags } from "../../services/businessForm";
import "../../styles/business.css";
import "../../styles/submissions.css";

const formatWhen = (iso) => {
  const date = new Date(iso);
  return `${date.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
};

// The steps of the current round (business_submission.status: waiting, under_review, rejected,
// approved, live). A resubmission starts a new round.
function progressSteps(submission) {
  const { status } = submission;
  const resubmitted = submission.round > 1;
  const steps = [{
    key: "submitted", label: resubmitted ? `Resubmitted (round ${submission.round})` : "Submitted", at: submission.submittedAt,
    state: "done", detail: resubmitted ? "We received your changes." : "We received your registration.",
  }];
  if (status === "waiting") {
    steps.push({ key: "review", label: "Under review", state: "pending", detail: "Waiting for an admin to start reviewing your details." });
    return steps;
  }
  steps.push({
    key: "review", label: "Under review", at: submission.reviewStartedAt, state: status === "under_review" ? "current" : "done",
    detail: "An admin is checking your details and documents.",
  });
  if (status === "rejected") {
    steps.push({ key: "rejected", label: "Changes needed", at: submission.decidedAt, state: "rejected", detail: "Fix each flagged item below, then resubmit." });
  }
  if (status === "approved" || status === "live") {
    steps.push({ key: "approved", label: "Approved", at: submission.decidedAt, state: "approved", detail: "Your registration was approved." });
    steps.push(status === "live"
      ? { key: "live", label: "On FoodSight", at: submission.liveAt, state: "approved", detail: "Your restaurant is on FoodSight's map and chatbot." }
      : { key: "live", label: "On FoodSight", state: "current", detail: "It appears after tonight's update." });
  }
  return steps;
}

function ProgressStep({ step, detailId, isLast, open, onToggle, children }) {
  return (
    <li className={`my-sub-step is-${step.state}`}>
      <span className="my-sub-dot" aria-hidden="true">
        {step.state === "rejected" ? <X /> : step.state === "done" || step.state === "approved" ? <Check /> : null}
      </span>
      {!isLast && <span className="my-sub-line" aria-hidden="true" />}
      <div className="my-sub-step-body">
        <button type="button" className="my-sub-step-head" aria-expanded={open} aria-controls={detailId} onClick={onToggle}>
          <span className="my-sub-step-label">{step.label}</span>
          {step.at && <span className="my-sub-step-time">{formatWhen(step.at)}</span>}
          <ChevronDown className={open ? "is-open" : ""} aria-hidden="true" />
        </button>
        {open && (
          <div id={detailId} className="my-sub-step-detail">
            <p>{step.detail}</p>
            {children}
          </div>
        )}
      </div>
    </li>
  );
}

function SubmissionCard({ submission, defaultOpen, onResubmit }) {
  const [open, setOpen] = useState(defaultOpen);
  const steps = progressSteps(submission);
  const [openStep, setOpenStep] = useState(steps.at(-1).key);
  const bodyId = `submission-${submission.id}`;

  return (
    <section className="business-section my-sub-card">
      <button type="button" className="my-sub-head" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)}>
        <span className="my-sub-icon" aria-hidden="true"><Store /></span>
        <h2>{submission.form.businessName}</h2>
        <ChevronDown className={`my-sub-chevron${open ? " is-open" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div id={bodyId} className="my-sub-progress">
          <h3>Review progress</h3>
          <ol className="my-sub-steps">
            {steps.map((step, index) => (
              <ProgressStep
                key={step.key} step={step} detailId={`${bodyId}-${step.key}`} isLast={index === steps.length - 1}
                open={openStep === step.key} onToggle={() => setOpenStep(openStep === step.key ? null : step.key)}
              >
                {step.key === "rejected" && (
                  <>
                    {asFlags(submission.issues).map((issue) => (
                      <div key={issue.label} className="my-sub-issue">
                        <strong>{issue.section} · {issue.label}</strong>
                        <p>{issue.note}</p>
                      </div>
                    ))}
                    <div className="my-sub-actions">
                      <button type="button" className="business-next-btn" onClick={() => onResubmit(submission)}>Resubmit</button>
                    </div>
                  </>
                )}
              </ProgressStep>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

// state: "loading", "ready" or "error" (GET /business/submissions); onRetry asks again.
export default function MySubmissions({ submissions, state = "ready", onRetry, onResubmit, onRegister, darkMode = false }) {
  return (
    <main className="business-area">
      <div className="business-card">
        <header className="business-header my-sub-header">
          <img src={darkMode ? DarkModeLogo : Logo} alt="FoodSight" className="business-logo" />
        </header>
        {state !== "ready" ? (
          <section className="business-section my-sub-empty" role="status">
            {state === "loading" ? <p>Loading your submissions…</p> : (
              <>
                <p>We could not load your submissions. Check your connection and try again.</p>
                <button type="button" className="business-next-btn" onClick={onRetry}>Try again</button>
              </>
            )}
          </section>
        ) : submissions.length ? (
          <div className="business-form">
            {submissions.map((submission, index) => (
              <SubmissionCard key={submission.id} submission={submission} defaultOpen={index === 0} onResubmit={onResubmit} />
            ))}
          </div>
        ) : (
          <section className="business-section my-sub-empty">
            <p>You haven't registered a business yet.</p>
            <button type="button" className="business-next-btn" onClick={onRegister}>Register Business</button>
          </section>
        )}
      </div>
    </main>
  );
}
