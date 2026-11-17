"""Business submissions (migration 028): checking the Register Business form, saving it, and
turning saved rows back into the form's shape. Used by routes.py (the user's side) and
admin_routes.py (the admin's side).

The form's field ids (businessName, halalCertificate, location, hours, ...) are the names used
everywhere a field is pointed at: the admin's marks (submission_field_check.field), the
fields a user changed (submission_round.changed_fields) and the flags shown back on the form.
They are stored in the database, so a field id must not be renamed in the frontend."""

import os
import re
from datetime import date, datetime
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import text

from app import config
from app.business import formats, options

# business_submission.status (src/reference/categories.json)
WAITING, UNDER_REVIEW, REJECTED, APPROVED, LIVE = "waiting", "under_review", "rejected", "approved", "live"
REVIEWABLE = (WAITING, UNDER_REVIEW)
_STATUSES = set(options.columns()["business_submission.status"]["values"])
assert {WAITING, UNDER_REVIEW, REJECTED, APPROVED, LIVE} <= _STATUSES, "business_submission.status changed"

# The form's three halal choices -> (business_profile.halal_status, certified)
HALAL_CHOICES = {
    "halal_certified": ("halal", True),
    "halal_not_certified": ("halal", False),
    "not_halal": ("non-halal", False),
}
assert {status for status, _ in HALAL_CHOICES.values()} <= options.allowed("business_profile.halal_status")
YES_NO = {"yes": True, "no": False}
# Business styles that need a brand name
CHAIN_STYLES = {"local_chain", "international_chain"}
assert CHAIN_STYLES <= options.allowed("business_profile.business_style")

# Uploaded files: the form's field -> submission_document.kind, and the types each takes
DOCUMENT_KINDS = {
    "ssmCertificate": "ssm_certificate",
    "premisesLicence": "premises_licence",
    "storefrontPhoto": "storefront_photo",
    "halalCertificate": "halal_certificate",
}
FIELD_FOR_KIND = {kind: field for field, kind in DOCUMENT_KINDS.items()}
REQUIRED_DOCUMENTS = ("ssmCertificate", "storefrontPhoto")
PDF, JPEG, PNG = "application/pdf", "image/jpeg", "image/png"
DOCUMENT_TYPES = {
    "ssmCertificate": (PDF, JPEG, PNG),
    "premisesLicence": (PDF, JPEG, PNG),
    "halalCertificate": (PDF, JPEG, PNG),
    "storefrontPhoto": (JPEG, PNG),
}
MAX_FILE_BYTES = 10 * 1024 * 1024   # also MAX_FILE_BYTES in frontend/src/services/businessForm.js
MAX_AVERAGE_SPEND = 1000            # also in businessForm.js
NOTE_MAX = 500                      # submission_field_check.note
LOCAL_TIME = ZoneInfo(os.getenv("APP_TIMEZONE") or "Asia/Kuala_Lumpur")

# How each field is named in messages and emails
FIELD_LABELS = {
    "managerName": "Full name", "managerPhone": "Contact phone",
    "businessName": "Business name", "businessStyle": "Business style", "brandName": "Brand name",
    "businessPhone": "Business phone", "businessEmail": "Business email",
    "restaurantType": "Restaurant type", "businessStatus": "Status", "website": "Website or social page",
    "address": "Address", "postcode": "Postcode", "location": "Map pin",
    "ssmNumber": "SSM registration number", "ssmCertificate": "SSM certificate",
    "premisesLicence": "MBPJ food-premises licence", "storefrontPhoto": "Storefront photo",
    "halalStatus": "Halal status", "halalExpiry": "Certificate expiration date",
    "halalCertificate": "Halal certificate", "sellsPork": "Sells pork", "servesAlcohol": "Items containing alcohol",
    "hours": "Opening hours", "cuisines": "Cuisines served", "serviceStyle": "Service style",
    "averageSpend": "Average spend per person", "targetSegments": "Who usually dines here",
    "ambiance": "Ambiance", "description": "Short description", "facilities": "Facilities",
}
DAYS = formats.DAYS
_TABLE_READY = {"ok": False}


class SubmissionsNotReady(Exception):
    """The tables of migration 028 do not exist yet."""


def require_tables(db):
    if _TABLE_READY["ok"]:
        return
    if db.execute(text("SELECT to_regclass('public.business_submission')")).scalar() is None:
        raise SubmissionsNotReady()
    _TABLE_READY["ok"] = True


def today():
    return datetime.now(LOCAL_TIME).date()


def file_type(data: bytes) -> str | None:
    """The type from the file's first bytes, so a renamed file of another kind is refused."""
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    return None


def items(textual) -> list[str]:
    """A comma list as stored ("Malay, Nyonya") -> ["Malay", "Nyonya"]."""
    return [part.strip() for part in (textual or "").split(",") if part.strip()]


def facility_field(category: str) -> str:
    """The admin's mark for one facility group: facilities-parking."""
    return f"facilities-{category}"


# ---------------------------------------------------------------------------
# Checking the form
# ---------------------------------------------------------------------------


def parse_form(db, form: dict, has_document) -> tuple[dict, str | None, dict]:
    """Check the form the way the frontend does and turn it into business_submission columns.
    has_document(field) says whether a file is (or stays) uploaded for a document field.
    Returns (columns, section name, {field id: message}); with any message nothing is saved."""
    errors = {}
    values = {}

    def text_field(field, column, missing, most, required=True):
        value = str(form.get(field) or "").strip()
        if not value:
            if required:
                errors[field] = missing
            values[column] = None
        elif len(value) > most:
            errors[field] = f"Keep it to {most} characters."
        else:
            values[column] = value

    def phone_field(field, column, missing):
        if not str(form.get(field) or "").strip():
            errors[field] = missing
            return
        phone = formats.standardise_phone(str(form[field]))
        if phone is None:
            errors[field] = "Enter a valid Malaysian number after +60, such as 12-345 6789."
        values[column] = phone

    def pick_one(field, column, column_name, missing):
        value = form.get(field)
        if value not in options.allowed(column_name):
            errors[field] = missing
        values[column] = value

    def pick_many(field, column, allowed, most, missing):
        picked = form.get(field) if isinstance(form.get(field), list) else []
        if not picked:
            errors[field] = missing
        elif len(picked) > most:
            errors[field] = f"Pick up to {most}."
        elif len(set(picked)) != len(picked):
            errors[field] = "Each value can be picked once."
        elif not all(isinstance(value, str) and value in allowed for value in picked):
            errors[field] = "Pick only from the list."
        values[column] = ", ".join(picked) if picked else None
        return picked

    # Store manager (admin only)
    text_field("managerName", "manager_name", "Enter the store manager's full name.", 150)
    phone_field("managerPhone", "manager_phone", "Enter a contact phone number.")

    # General information
    text_field("businessName", "name", "Enter the business name.", 255)
    pick_one("businessStyle", "business_style", "business_profile.business_style", "Choose the business style.")
    if values["business_style"] in CHAIN_STYLES:
        text_field("brandName", "brand", "Enter the brand name.", 150)
    else:
        values["brand"] = None
    phone_field("businessPhone", "phone", "Enter the business phone number.")
    email = str(form.get("businessEmail") or "").strip()
    try:
        values["business_email"] = validate_email(email, check_deliverability=False).normalized
        if len(values["business_email"]) > 254:
            raise EmailNotValidError("too long")
    except EmailNotValidError:
        errors["businessEmail"] = "Enter a valid email, such as hello@cafe.my."
        values["business_email"] = email
    pick_one("restaurantType", "restaurant_type", "business_profile.restaurant_type", "Choose the restaurant type.")
    status = form.get("businessStatus")
    if status not in options.REGISTRABLE_STATUSES:
        errors["businessStatus"] = "Choose the status."
    values["business_status"] = status
    website = str(form.get("website") or "").strip()
    if website in ("", "https://", "http://"):
        values["website"] = None
    else:
        values["website"] = formats.tidy_website(website)
        if values["website"] is None:
            errors["website"] = "Enter a full link, such as https://foodsight.my."
        elif len(values["website"]) > 500:
            errors["website"] = "Keep the link to 500 characters."

    # Location
    text_field("address", "address", "Enter the street address.", 450)
    postcode = str(form.get("postcode") or "").strip()
    if not re.fullmatch(r"\d{5}", postcode):
        errors["postcode"] = "A postcode has 5 digits." if postcode else "Enter the postcode."
    values["postcode"] = postcode
    location = form.get("location") if isinstance(form.get("location"), dict) else {}
    area = None
    try:
        latitude, longitude = float(location["latitude"]), float(location["longitude"])
        values["latitude"], values["longitude"] = latitude, longitude
        area = formats.area_for(db, latitude, longitude)
        if area is None:
            errors["location"] = "Place the pin inside Petaling Jaya."
    except (KeyError, TypeError, ValueError):
        errors["location"] = "Place the pin on your entrance."

    # Business verification (admin only)
    ssm = re.sub(r"[\s-]", "", str(form.get("ssmNumber") or ""))
    if not re.fullmatch(r"\d{12}", ssm):
        errors["ssmNumber"] = ("An SSM registration number has 12 digits." if ssm
                               else "Enter the SSM registration number.")
    values["ssm_number"] = ssm
    for field in REQUIRED_DOCUMENTS:
        if not has_document(field):
            errors[field] = f"Upload the {FIELD_LABELS[field].lower().replace('ssm', 'SSM')}."

    # Halal status
    choice = form.get("halalStatus")
    halal_status, certified = HALAL_CHOICES.get(choice, (None, False))
    if halal_status is None:
        errors["halalStatus"] = "Choose the halal status."
    values["halal_status"], values["halal_certified"] = halal_status, certified
    values["halal_cert_expiry"] = None
    values["sells_pork"] = values["serves_alcohol"] = None
    if certified:
        if not has_document("halalCertificate"):
            errors["halalCertificate"] = "Upload the halal certificate."
        try:
            expiry = date.fromisoformat(str(form.get("halalExpiry") or ""))
            values["halal_cert_expiry"] = expiry
            if expiry < today():
                errors["halalExpiry"] = "This certificate has expired."
        except ValueError:
            errors["halalExpiry"] = "Choose the certificate's expiration date."
    if choice == "not_halal":
        for field, column in (("sellsPork", "sells_pork"), ("servesAlcohol", "serves_alcohol")):
            if form.get(field) not in YES_NO:
                errors[field] = "Choose Yes or No."
            values[column] = YES_NO.get(form.get(field))

    # Opening hours
    hours, problem = formats.hours_to_columns(form.get("hours"))
    if problem:
        errors["hours"] = problem
    for day in DAYS:
        values[day] = hours.get(day)

    # Food and dining
    cuisine_names = {choice["value"] for choice in options.cuisines()}
    pick_many("cuisines", "cuisines", cuisine_names, options.most("cuisine.name"), "Pick at least one cuisine.")
    pick_one("serviceStyle", "service_style", "business_profile.service_style", "Choose the service style.")
    spend = str(form.get("averageSpend") or "").strip()
    if not spend:
        errors["averageSpend"] = "Enter what one person usually spends."
    elif not re.fullmatch(r"\d+(\.\d{1,2})?", spend) or float(spend) <= 0:
        errors["averageSpend"] = "Enter an amount in RM, such as 12.50."
    elif float(spend) > MAX_AVERAGE_SPEND:
        errors["averageSpend"] = f"Enter an amount up to RM{MAX_AVERAGE_SPEND}."
    values["avg_meal_price"] = float(spend) if re.fullmatch(r"\d+(\.\d{1,2})?", spend) else None
    pick_many("targetSegments", "target_segment", options.allowed("business_profile.target_segment"),
              options.most("business_profile.target_segment"), "Pick at least one group of diners.")
    ambiance = pick_many("ambiance", "ambiance", options.allowed("business_profile.ambiance"),
                         options.most("business_profile.ambiance"), "Pick at least one ambiance.")
    if "ambiance" not in errors and "lively" in ambiance and "quiet" in ambiance:
        errors["ambiance"] = "A place can't be both lively and quiet. Pick one."
    text_field("description", "description", "Write a short description of the restaurant.", 1000)

    # Facilities (optional), kept in the list's order so a reorder is no change
    names = options.facility_categories()
    chosen = form.get("facilities") if isinstance(form.get("facilities"), list) else []
    if not all(isinstance(name, str) and name in names for name in chosen):
        errors["facilities"] = "Pick only facilities from the list."
    values["facilities"] = ", ".join(name for name in names if name in chosen) or None

    return values, area, errors


# ---------------------------------------------------------------------------
# Which fields the admin marks, and which ones the user changed
# ---------------------------------------------------------------------------


def review_fields(values) -> list[str]:
    """Every field the admin marks Checked or Flag, in the page's order. The same list as
    reviewSections() in frontend/src/services/adminSubmissions.js."""
    fields = ["managerName", "managerPhone", "businessName", "businessStyle"]
    if values.get("business_style") in CHAIN_STYLES:
        fields.append("brandName")
    fields += ["businessPhone", "businessEmail", "restaurantType", "businessStatus", "website",
               "address", "postcode", "location",
               "ssmNumber", "ssmCertificate", "premisesLicence", "storefrontPhoto", "halalStatus"]
    if values.get("halal_certified"):
        fields += ["halalExpiry", "halalCertificate"]
    if values.get("halal_status") == "non-halal":
        fields += ["sellsPork", "servesAlcohol"]
    fields += ["hours", "cuisines", "serviceStyle", "averageSpend", "targetSegments", "ambiance", "description"]
    categories = options.facility_categories()
    present = {categories[name] for name in items(values.get("facilities")) if name in categories}
    groups = [facility_field(key) for key in options.columns()["facility.category"]["values"] if key in present]
    return fields + (groups or ["facilities"])


def field_values(values, documents) -> dict:
    """Each field's value in a form that compares: what decides whether a resubmission changed
    a field. documents: {field: the document's id, "new" for a new upload, None for none}."""
    v = values
    expiry = v.get("halal_cert_expiry")
    out = {
        "managerName": v.get("manager_name"), "managerPhone": v.get("manager_phone"),
        "businessEmail": v.get("business_email"), "ssmNumber": v.get("ssm_number"),
        "businessName": v.get("name"), "brandName": v.get("brand"), "businessStyle": v.get("business_style"),
        "restaurantType": v.get("restaurant_type"), "businessStatus": v.get("business_status"),
        "businessPhone": v.get("phone"), "website": v.get("website"), "description": v.get("description"),
        "address": v.get("address"), "postcode": v.get("postcode"),
        "location": (round(float(v["latitude"]), 6), round(float(v["longitude"]), 6)),
        "halalStatus": (v.get("halal_status"), bool(v.get("halal_certified"))),
        "halalExpiry": expiry.isoformat() if expiry else None,
        "sellsPork": v.get("sells_pork"), "servesAlcohol": v.get("serves_alcohol"),
        "hours": tuple(v.get(day) for day in DAYS),
        "cuisines": v.get("cuisines"), "serviceStyle": v.get("service_style"),
        "averageSpend": round(float(v["avg_meal_price"]), 2),
        "targetSegments": v.get("target_segment"), "ambiance": v.get("ambiance"),
        "facilities": v.get("facilities"),
    }
    categories = options.facility_categories()
    chosen = items(v.get("facilities"))
    for key in options.columns()["facility.category"]["values"]:
        out[facility_field(key)] = tuple(name for name in chosen if categories.get(name) == key)
    for field in DOCUMENT_KINDS:
        out[field] = documents.get(field)
    return out


# ---------------------------------------------------------------------------
# Reading and writing rows
# ---------------------------------------------------------------------------


def load_row(db, submission_id):
    row = db.execute(text("SELECT * FROM public.business_submission WHERE submission_id = :id"),
                     {"id": submission_id}).mappings().first()
    return dict(row) if row else None


def load_documents(db, submission_ids) -> dict:
    """{submission_id: {field: {id, name, size, type}}}, without the files' bytes."""
    found = {}
    if not submission_ids:
        return found
    rows = db.execute(text(
        "SELECT document_id, submission_id, kind, file_name, content_type, size_bytes "
        "FROM public.submission_document WHERE submission_id = ANY(:ids)"), {"ids": list(submission_ids)}).mappings()
    for row in rows:
        field = FIELD_FOR_KIND.get(row["kind"])
        if field:
            found.setdefault(row["submission_id"], {})[field] = {
                "id": row["document_id"], "name": row["file_name"], "size": row["size_bytes"],
                "type": row["content_type"]}
    return found


def load_rounds(db, submission_ids) -> dict:
    """{submission_id: [round, ...]} oldest first, each with its reviewer's username."""
    found = {}
    if not submission_ids:
        return found
    rows = db.execute(text(
        "SELECT r.*, u.username AS reviewer_name FROM public.submission_round r "
        "LEFT JOIN auth.users u ON u.user_id = r.reviewer_id "
        "WHERE r.submission_id = ANY(:ids) ORDER BY r.submission_id, r.round_no"),
        {"ids": list(submission_ids)}).mappings()
    for row in rows:
        found.setdefault(row["submission_id"], []).append(dict(row))
    return found


def load_checks(db, round_ids) -> dict:
    """{round_id: {field: {state, note}}}."""
    found = {}
    if not round_ids:
        return found
    rows = db.execute(text("SELECT round_id, field, state, note FROM public.submission_field_check "
                           "WHERE round_id = ANY(:ids)"), {"ids": list(round_ids)}).mappings()
    for row in rows:
        found.setdefault(row["round_id"], {})[row["field"]] = {"state": row["state"], "note": row["note"] or ""}
    return found


def insert_row(db, table, values, returning):
    columns = list(values)
    return db.execute(text(
        f"INSERT INTO public.{table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)}) "
        f"RETURNING {returning}"), values).scalar()


def update_row(db, submission_id, values):
    db.execute(text(f"UPDATE public.business_submission SET {', '.join(f'{c} = :{c}' for c in values)} "
                    "WHERE submission_id = :submission_id"), {**values, "submission_id": submission_id})


def save_document(db, submission_id, field, upload):
    """Add or replace one uploaded file (upload: {name, type, data})."""
    db.execute(text(
        "INSERT INTO public.submission_document (submission_id, kind, file_name, content_type, size_bytes, content) "
        "VALUES (:sid, :kind, :name, :type, :size, :data) "
        "ON CONFLICT (submission_id, kind) DO UPDATE SET file_name = EXCLUDED.file_name, "
        "content_type = EXCLUDED.content_type, size_bytes = EXCLUDED.size_bytes, content = EXCLUDED.content, "
        "uploaded_at = now()"),
        {"sid": submission_id, "kind": DOCUMENT_KINDS[field], "name": upload["name"][:255], "type": upload["type"],
         "size": len(upload["data"]), "data": upload["data"]})


def delete_document(db, submission_id, field):
    db.execute(text("DELETE FROM public.submission_document WHERE submission_id = :sid AND kind = :kind"),
               {"sid": submission_id, "kind": DOCUMENT_KINDS[field]})


def read_document(db, submission_id, kind):
    return db.execute(text(
        "SELECT file_name, content_type, content FROM public.submission_document "
        "WHERE submission_id = :sid AND kind = :kind"), {"sid": submission_id, "kind": kind}).mappings().first()


# ---------------------------------------------------------------------------
# Back to the form's shape
# ---------------------------------------------------------------------------


def _iso(value):
    return value.isoformat() if value else None


def row_to_form(row, documents, document_url, area):
    """A saved submission in the shape the frontend's form uses."""
    choice = next((key for key, value in HALAL_CHOICES.items()
                   if value == (row["halal_status"], bool(row["halal_certified"]))), "")
    yes_no = {True: "yes", False: "no", None: ""}
    files = {field: ({"name": doc["name"], "size": doc["size"], "type": doc["type"],
                      "url": document_url(DOCUMENT_KINDS[field])} if (doc := documents.get(field)) else None)
             for field in DOCUMENT_KINDS}
    return {
        "managerName": row["manager_name"], "managerPhone": formats.local_phone(row["manager_phone"]),
        "businessName": row["name"], "businessStyle": row["business_style"], "brandName": row["brand"] or "",
        "businessPhone": formats.local_phone(row["phone"]), "businessEmail": row["business_email"],
        "restaurantType": row["restaurant_type"], "businessStatus": row["business_status"],
        "website": row["website"] or "",
        "address": row["address"], "postcode": row["postcode"], "area": area or "",
        "location": {"latitude": row["latitude"], "longitude": row["longitude"]},
        "ssmNumber": row["ssm_number"], **files,
        "halalStatus": choice, "halalExpiry": _iso(row["halal_cert_expiry"]) or "",
        "sellsPork": yes_no[row["sells_pork"]], "servesAlcohol": yes_no[row["serves_alcohol"]],
        "hours": formats.columns_to_hours(row),
        "cuisines": items(row["cuisines"]), "serviceStyle": row["service_style"],
        "averageSpend": f"{row['avg_meal_price']:.2f}",
        "targetSegments": items(row["target_segment"]), "ambiance": items(row["ambiance"]),
        "description": row["description"], "facilities": items(row["facilities"]),
    }


def submission_json(db, row, documents, rounds, checks, *, admin):
    """One submission for the API. The user sees their form, the timeline and, when rejected,
    the flagged fields; the admin also sees this round's marks, last round's flags, the fields
    the user changed and who decided."""
    sid = row["submission_id"]
    prefix = "admin/submissions" if admin else "business/submissions"
    document_url = lambda kind: f"{config.BACKEND_URL}/api/v1/{prefix}/{sid}/documents/{kind}"  # noqa: E731
    current = next((r for r in rounds if r["round_no"] == row["round_no"]), None) or {}
    previous = next((r for r in rounds if r["round_no"] == row["round_no"] - 1), None)
    marks = checks.get(current.get("round_id"), {})
    flags = [{"field": field, "label": FIELD_LABELS.get(field, field), "note": mark["note"]}
             for field, mark in marks.items() if mark["state"] == "flagged"]
    live_at = None
    if row["restaurant_id"]:
        live_at = db.execute(text("SELECT created_at FROM public.restaurant WHERE restaurant_id = :id"),
                             {"id": row["restaurant_id"]}).scalar()
    data = {
        "id": sid,
        "status": row["status"],
        "round": row["round_no"],
        "createdAt": _iso(row["created_at"]),
        "submittedAt": _iso(current.get("submitted_at")) or _iso(row["created_at"]),
        "reviewStartedAt": _iso(current.get("review_started_at")),
        "decidedAt": _iso(current.get("decided_at")),
        "restaurantId": row["restaurant_id"],
        "liveAt": _iso(live_at),
        "form": row_to_form(row, documents, document_url, formats.area_for(db, row["latitude"], row["longitude"])),
        "issues": flags if row["status"] == REJECTED else [],
        "rounds": [{"round": r["round_no"], "submittedAt": _iso(r["submitted_at"]),
                    "reviewStartedAt": _iso(r["review_started_at"]), "decidedAt": _iso(r["decided_at"]),
                    "decision": r["decision"], "changedFields": items(r["changed_fields"])} for r in rounds],
    }
    if admin:
        data.update({
            "decidedBy": current.get("reviewer_name") if current.get("decided_at") else None,
            "reviewer": current.get("reviewer_name"),
            "review": marks,
            "previousFlags": {field: mark["note"] for field, mark in checks.get((previous or {}).get("round_id"), {}).items()
                              if mark["state"] == "flagged"},
            "changedFields": items(current.get("changed_fields")),
            "reviewFields": review_fields(row),
        })
    return data


def submissions_json(db, rows, *, admin):
    ids = [row["submission_id"] for row in rows]
    documents, rounds = load_documents(db, ids), load_rounds(db, ids)
    checks = load_checks(db, [r["round_id"] for found in rounds.values() for r in found])
    return [submission_json(db, row, documents.get(row["submission_id"], {}), rounds.get(row["submission_id"], []),
                            checks, admin=admin) for row in rows]


# ---------------------------------------------------------------------------
# Restaurants already near the pin (the admin's duplicate check)
# ---------------------------------------------------------------------------


def _distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * asin(sqrt(a))


def _plain(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def nearby_restaurants(db, row, radius_m=100, limit=10):
    """FoodSight restaurants within radius_m of the submission's pin, alike names first, so the
    admin can tell whether the business is already on FoodSight."""
    lat, lon = row["latitude"], row["longitude"]
    box = radius_m / 111_000 * 1.5
    rows = db.execute(text(
        "SELECT r.restaurant_id, r.name, r.source, r.business_status, l.latitude, l.longitude, l.full_address "
        "FROM public.restaurant r JOIN public.location l ON l.location_id = r.location_id "
        "WHERE l.latitude BETWEEN :lat - :box AND :lat + :box AND l.longitude BETWEEN :lon - :box AND :lon + :box "
        "AND r.restaurant_id IS DISTINCT FROM :own"),
        {"lat": lat, "lon": lon, "box": box, "own": row["restaurant_id"]}).mappings()
    found = []
    name = _plain(row["name"])
    for other in rows:
        distance = _distance_m(lat, lon, other["latitude"], other["longitude"])
        if distance > radius_m:
            continue
        other_name = _plain(other["name"])
        alike = SequenceMatcher(None, name, other_name).ratio() >= 0.6 or (
            bool(name) and bool(other_name) and (name in other_name or other_name in name))
        found.append({"restaurantId": other["restaurant_id"], "name": other["name"], "source": other["source"],
                      "businessStatus": other["business_status"], "address": other["full_address"],
                      "distanceM": round(distance), "similarName": alike})
    found.sort(key=lambda item: (not item["similarName"], item["distanceM"]))
    return found[:limit]
