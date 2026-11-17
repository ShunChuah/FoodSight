"""Business submissions, the admin's side (/api/v1/admin/submissions/...): the list, one
submission with its files and the restaurants already near its pin, a Checked or Flag mark on
each field, and the decision. Only admins (auth.users.is_superuser).

Rules (the same as the admin page):
  - every field must be marked, and every flag needs a note telling the user what to fix
  - any flag means Reject only; no flags means Approve only
  - the owner is emailed at the business email when the admin decides (one email; the
    restaurant itself appears after the next nightly update, which sets the submission live)
Changes use PUT and POST, never GET (the SameSite cookie rule)."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import config
from app.auth.backend import current_admin
from app.auth.email import send_email
from app.auth.models import User
from app.business import submissions as subs
from app.business.routes import DocumentKind, _tables, document_response
from app.database import get_db

router = APIRouter(prefix="/admin/submissions", tags=["admin"], dependencies=[Depends(current_admin)])


class Mark(BaseModel):
    state: Literal["checked", "flagged"]
    note: str = Field(default="", max_length=subs.NOTE_MAX)


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]


def _row(db, submission_id):
    _tables(db)
    row = subs.load_row(db, submission_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SUBMISSION_NOT_FOUND")
    return row


def _current_round(db, row):
    return db.execute(text("SELECT * FROM public.submission_round WHERE submission_id = :id AND round_no = :round"),
                      {"id": row["submission_id"], "round": row["round_no"]}).mappings().first()


def _detail(db, row):
    data = subs.submissions_json(db, [row], admin=True)[0]
    data["nearby"] = subs.nearby_restaurants(db, row)
    return data


@router.get("")
def list_submissions(db: Session = Depends(get_db)):
    """Every submission (newest first), and how many restaurants FoodSight has."""
    _tables(db)
    rows = db.execute(text("SELECT * FROM public.business_submission ORDER BY created_at DESC")).mappings().all()
    counts = db.execute(text("SELECT count(*), count(*) FILTER (WHERE source = 'submitted') "
                             "FROM public.restaurant")).first()
    return {
        "submissions": subs.submissions_json(db, [dict(row) for row in rows], admin=True),
        "restaurants": counts[0],
        "submittedRestaurants": counts[1],
    }


@router.get("/{submission_id}")
def read_submission(submission_id: int, db: Session = Depends(get_db)):
    return _detail(db, _row(db, submission_id))


@router.get("/{submission_id}/documents/{kind}")
def read_document(submission_id: int, kind: str = DocumentKind, db: Session = Depends(get_db)):
    _row(db, submission_id)
    return document_response(db, submission_id, kind)


@router.put("/{submission_id}/checks/{field}")
def mark_field(submission_id: int, field: str, body: Mark, db: Session = Depends(get_db),
               admin: User = Depends(current_admin)):
    """Checked, or Flag with a note. The first mark starts the review (under review)."""
    row = _row(db, submission_id)
    if row["status"] not in subs.REVIEWABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "SUBMISSION_ALREADY_DECIDED")
    if field not in subs.review_fields(row):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "FIELD_NOT_REVIEWED")
    note = body.note.strip()
    if body.state == "flagged" and not note:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "FLAG_NOTE_EMPTY")
    current = _current_round(db, row)
    db.execute(text(
        "INSERT INTO public.submission_field_check (round_id, field, state, note) VALUES (:round, :field, :state, :note) "
        "ON CONFLICT (round_id, field) DO UPDATE SET state = EXCLUDED.state, note = EXCLUDED.note, checked_at = now()"),
        {"round": current["round_id"], "field": field, "state": body.state,
         "note": note if body.state == "flagged" else None})
    if current["review_started_at"] is None:
        db.execute(text("UPDATE public.submission_round SET reviewer_id = :admin, review_started_at = now() "
                        "WHERE round_id = :round"), {"admin": admin.id, "round": current["round_id"]})
    if row["status"] == subs.WAITING:
        db.execute(text("UPDATE public.business_submission SET status = :status WHERE submission_id = :id"),
                   {"status": subs.UNDER_REVIEW, "id": submission_id})
    db.commit()
    return _detail(db, subs.load_row(db, submission_id))


@router.post("/{submission_id}/decision")
def decide(submission_id: int, body: Decision, background: BackgroundTasks, db: Session = Depends(get_db),
           admin: User = Depends(current_admin)):
    row = _row(db, submission_id)
    if row["status"] not in subs.REVIEWABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "SUBMISSION_ALREADY_DECIDED")
    current = _current_round(db, row)
    marks = subs.load_checks(db, [current["round_id"]]).get(current["round_id"], {})
    missing = [field for field in subs.review_fields(row) if field not in marks]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "REVIEW_NOT_COMPLETE", "fields": missing})
    flagged = {field: mark["note"] for field, mark in marks.items() if mark["state"] == "flagged"}
    if body.decision == "approved" and flagged:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "FLAGGED_CANNOT_APPROVE")
    if body.decision == "rejected" and not flagged:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "NOTHING_FLAGGED")
    db.execute(text("UPDATE public.submission_round SET decision = :decision, decided_at = :now, "
                    "reviewer_id = COALESCE(reviewer_id, :admin), "
                    "review_started_at = COALESCE(review_started_at, :now) WHERE round_id = :round"),
               {"decision": body.decision, "now": datetime.now(timezone.utc), "admin": admin.id,
                "round": current["round_id"]})
    db.execute(text("UPDATE public.business_submission SET status = :status WHERE submission_id = :id"),
               {"status": subs.APPROVED if body.decision == "approved" else subs.REJECTED, "id": submission_id})
    db.commit()
    subject, message = decision_email(row, body.decision, flagged)
    background.add_task(send_email, row["business_email"], subject, message)
    return _detail(db, subs.load_row(db, submission_id))


def decision_email(row, decision, flagged):
    """The one email the owner gets: approved (it appears after tonight's update), or what to fix."""
    link = f"{config.FRONTEND_URL}/chat"
    greeting = f"Hi {row['manager_name']},"
    if decision == "approved":
        return (f"FoodSight: {row['name']} is approved",
                f"{greeting}\n\nWe checked your registration of {row['name']} and approved it. It will appear "
                "on FoodSight's map and chatbot after tonight's update.\n\n"
                f"You can follow it under Submissions on FoodSight: {link}\n\nFoodSight")
    lines = "\n".join(f"- {subs.FIELD_LABELS.get(field, 'Facilities: ' + field.split('-', 1)[-1].replace('_', ' '))}: "
                      f"{note}" for field, note in flagged.items())
    return (f"FoodSight: please update your registration of {row['name']}",
            f"{greeting}\n\nWe checked your registration of {row['name']}, and these need changing:\n\n{lines}\n\n"
            f"Open Submissions on FoodSight, choose Resubmit, change each of these and send it again: {link}"
            "\n\nFoodSight")
