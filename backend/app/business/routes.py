"""Register Business, the user's side (/api/v1/business/...): the form's lists, the section a pin
is in, and the user's own submissions (submit, read, resubmit after a rejection, open a file).

A submission waits for an admin (admin_routes.py). An approved one is added to FoodSight by the
next nightly pipeline run (src/s3_mergers/submissions.py), which sets it live. Any logged-in,
verified user can submit; each user sees only their own submissions."""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Response, UploadFile, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.backend import current_user
from app.auth.models import User
from app.business import formats, options
from app.business import submissions as subs
from app.database import get_db

router = APIRouter(prefix="/business", tags=["business"])

DocumentKind = Path(pattern="^(ssm_certificate|premises_licence|storefront_photo|halal_certificate)$")


def _tables(db):
    try:
        subs.require_tables(db)
    except subs.SubmissionsNotReady:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SUBMISSIONS_NOT_READY")


def _invalid(errors):
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": "SUBMISSION_INVALID", "fields": errors})


def _read_form(form: str) -> dict:
    try:
        data = json.loads(form)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SUBMISSION_BAD_FORM")
    return data


async def _read_uploads(files: dict) -> tuple[dict, dict]:
    """The files sent with the form: {field: {name, type, data}}, checked by their first bytes
    and size; and {field: message} for the ones refused."""
    uploads, errors = {}, {}
    for field, upload in files.items():
        if upload is None or not upload.filename:
            continue
        data = await upload.read(subs.MAX_FILE_BYTES + 1)
        kind = subs.file_type(data)
        if len(data) > subs.MAX_FILE_BYTES:
            errors[field] = "This file is over 10 MB."
        elif not data or kind not in subs.DOCUMENT_TYPES[field]:
            errors[field] = ("Upload a PDF, JPG or PNG file." if subs.PDF in subs.DOCUMENT_TYPES[field]
                             else "Upload a JPG or PNG file.")
        else:
            uploads[field] = {"name": upload.filename, "type": kind, "data": data}
    return uploads, errors


def _own(db, submission_id, user):
    row = subs.load_row(db, submission_id)
    if row is None or row["user_id"] != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SUBMISSION_NOT_FOUND")
    return row


def _one(db, row):
    return subs.submissions_json(db, [row], admin=False)[0]


@router.get("/options")
def read_options(db: Session = Depends(get_db), user: User = Depends(current_user)):
    city = db.execute(text("SELECT name, state FROM public.city ORDER BY city_id LIMIT 1")).first()
    return options.form_options(", ".join(part for part in city if part) if city else "Petaling Jaya, Selangor")


@router.get("/area")
def read_area(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    name = formats.area_for(db, latitude, longitude)
    return {"area": name, "shortName": formats.short_area(name) if name else None}


@router.get("/submissions")
def read_my_submissions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    _tables(db)
    rows = db.execute(text("SELECT * FROM public.business_submission WHERE user_id = :user "
                           "ORDER BY created_at DESC"), {"user": user.id}).mappings().all()
    return subs.submissions_json(db, [dict(row) for row in rows], admin=False)


@router.get("/submissions/{submission_id}")
def read_my_submission(submission_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _tables(db)
    return _one(db, _own(db, submission_id, user))


@router.post("/submissions", status_code=status.HTTP_201_CREATED)
async def submit(
    form: str = Form(...),
    ssmCertificate: UploadFile | None = File(None),  # noqa: N803  (the form's field ids)
    premisesLicence: UploadFile | None = File(None),  # noqa: N803
    storefrontPhoto: UploadFile | None = File(None),  # noqa: N803
    halalCertificate: UploadFile | None = File(None),  # noqa: N803
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _tables(db)
    data = _read_form(form)
    uploads, file_errors = await _read_uploads({"ssmCertificate": ssmCertificate, "premisesLicence": premisesLicence,
                                                "storefrontPhoto": storefrontPhoto,
                                                "halalCertificate": halalCertificate})
    values, _, errors = subs.parse_form(db, data, lambda field: field in uploads)
    errors.update(file_errors)
    if errors:
        _invalid(errors)
    submission_id = subs.insert_row(db, "business_submission",
                                    {**values, "user_id": user.id, "status": subs.WAITING, "round_no": 1},
                                    "submission_id")
    subs.insert_row(db, "submission_round", {"submission_id": submission_id, "round_no": 1}, "round_id")
    for field, upload in uploads.items():
        if field == "halalCertificate" and not values["halal_certified"]:
            continue   # a file for a choice the user left: not kept
        subs.save_document(db, submission_id, field, upload)
    db.commit()
    return _one(db, subs.load_row(db, submission_id))


@router.put("/submissions/{submission_id}")
async def resubmit(
    submission_id: int,
    form: str = Form(...),
    ssmCertificate: UploadFile | None = File(None),  # noqa: N803
    premisesLicence: UploadFile | None = File(None),  # noqa: N803
    storefrontPhoto: UploadFile | None = File(None),  # noqa: N803
    halalCertificate: UploadFile | None = File(None),  # noqa: N803
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """A rejected submission, fixed and sent again. A file field in the form that still has a
    value keeps the saved file unless a new one is sent; one left empty removes it. Every field
    the admin flagged must have changed."""
    _tables(db)
    row = _own(db, submission_id, user)
    if row["status"] != subs.REJECTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "SUBMISSION_NOT_EDITABLE")
    data = _read_form(form)
    uploads, file_errors = await _read_uploads({"ssmCertificate": ssmCertificate, "premisesLicence": premisesLicence,
                                                "storefrontPhoto": storefrontPhoto,
                                                "halalCertificate": halalCertificate})
    saved = subs.load_documents(db, [submission_id]).get(submission_id, {})
    kept = {field for field in subs.DOCUMENT_KINDS if field not in uploads and data.get(field) and field in saved}
    values, _, errors = subs.parse_form(db, data, lambda field: field in uploads or field in kept)
    errors.update(file_errors)
    if errors:
        _invalid(errors)
    if not values["halal_certified"]:
        kept.discard("halalCertificate")
        uploads.pop("halalCertificate", None)

    # What changed, and whether every flagged field did
    old_documents = {field: doc["id"] for field, doc in saved.items()}
    new_documents = {field: ("new" if field in uploads else old_documents[field] if field in kept else None)
                     for field in subs.DOCUMENT_KINDS}
    before = subs.field_values(row, old_documents)
    after = subs.field_values(values, new_documents)
    changed = [field for field in after if after[field] != before.get(field)]
    rounds = subs.load_rounds(db, [submission_id]).get(submission_id, [])
    current = next(r for r in rounds if r["round_no"] == row["round_no"])
    marks = subs.load_checks(db, [current["round_id"]]).get(current["round_id"], {})
    unchanged = {field: "Change this before you resubmit: " + mark["note"]
                 for field, mark in marks.items() if mark["state"] == "flagged" and field not in changed}
    if unchanged:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"code": "FLAGGED_FIELDS_UNCHANGED", "fields": unchanged})

    next_round = row["round_no"] + 1
    subs.update_row(db, submission_id, {**values, "status": subs.WAITING, "round_no": next_round})
    round_id = subs.insert_row(db, "submission_round", {
        "submission_id": submission_id, "round_no": next_round,
        "changed_fields": ", ".join(field for field in changed if field != "facilities") or None,
    }, "round_id")
    # The fields the user left alone and the admin checked last time start as checked
    review = set(subs.review_fields(values))
    for field, mark in marks.items():
        if mark["state"] == "checked" and field in review and field not in changed:
            db.execute(text("INSERT INTO public.submission_field_check (round_id, field, state) "
                            "VALUES (:round, :field, 'checked')"), {"round": round_id, "field": field})
    for field in subs.DOCUMENT_KINDS:
        if field in uploads:
            subs.save_document(db, submission_id, field, uploads[field])
        elif field not in kept:
            subs.delete_document(db, submission_id, field)
    db.commit()
    return _one(db, subs.load_row(db, submission_id))


@router.get("/submissions/{submission_id}/documents/{kind}")
def read_my_document(submission_id: int, kind: str = DocumentKind,
                     db: Session = Depends(get_db), user: User = Depends(current_user)):
    _tables(db)
    _own(db, submission_id, user)
    return document_response(db, submission_id, kind)


def document_response(db, submission_id, kind):
    """One uploaded file, shown in the browser (inline), never cached by a shared cache."""
    document = subs.read_document(db, submission_id, kind)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DOCUMENT_NOT_FOUND")
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in document["file_name"])
    return Response(bytes(document["content"]), media_type=document["content_type"], headers={
        "Content-Disposition": f'inline; filename="{safe_name}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })
