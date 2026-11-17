import { CircleCheck } from "lucide-react";
import { reviewSections } from "../../services/businessReview";

export function ReviewDetails({ form, onEdit, flags = [] }) {
  return (
    <section className="business-section business-review" aria-labelledby="review-title">
      <h2 id="review-title">Review your details</h2>
      <dl className="business-review-list">
        {reviewSections(form).map((section) => (
          <div key={section.title} className={`business-review-row${flags.some((flag) => flag.section === section.title) ? " is-flagged" : ""}`}>
            <dt>{section.title}</dt>
            <dd>
              {section.rows.map((row) => (
                <p key={row.label}>
                  <strong>{row.label}:</strong> {row.value}
                </p>
              ))}
            </dd>
            <button
              type="button"
              className="business-review-edit"
              onClick={() => onEdit(section.step, section.field)}
              aria-label={`Edit ${section.title.toLowerCase()}`}
            >
              Edit
            </button>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function SubmittedNotice({ email }) {
  return (
    <section className="business-section business-submitted" role="status">
      <CircleCheck aria-hidden="true" />
      <h2>Submitted for review</h2>
      <p>
        Thanks! An admin will check your business details and documents and email you at{" "}
        <strong>{email.trim() || "your business email"}</strong> with the decision. Once approved, your
        restaurant appears on FoodSight after that night's update. You can follow it under Submissions.
      </p>
    </section>
  );
}
