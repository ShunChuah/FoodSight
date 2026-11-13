"""
Cleans data/1_raw/google_raw.csv → data/2_cleaned/google_cleaned.csv.

Step 1 — Normalise business_status:
            - Map 'CLOSED_PERMANENTLY' → 'PERMANENTLY_CLOSED' and
              'CLOSED_TEMPORARILY' → 'TEMPORARILY_CLOSED'
            - Set empty/null business_status → 'UNKNOWN'
            - Any other value not allowed in src/reference/categories.json (such as
              Google's BUSINESS_STATUS_UNSPECIFIED) → 'UNKNOWN', so the
              validator does not reject the whole restaurant

Step 2 — Validate rating_score: clear the field (set to empty string)
          if the value is not a number between 1.0 and 5.0 inclusive.
          The row itself is kept — a missing rating is still a valid record.

Step 3 — Standardise phone numbers with the phonenumbers library, the same
          way as clean_osm.py so the merger sees one number written one way:
            - A value with several numbers keeps the first valid Malaysian one.
            - Landlines and mobiles: +603-78656815, +6012-3456789,
              +6011-23063718.
            - 1-300, 1-700 and 1-800 numbers keep their Malaysian form
              (1-300-88-2525).
            - A value with no valid Malaysian number is kept as written.

Step 4 — Tidy the address fields: strip spaces from formatted_address,
          postcode and street, and clear the postcode unless it is 5 digits
          (Malaysian format). The row itself is kept.

Step 5 — Tidy websites, only in ways that cannot break the link (as in
          clean_osm.py): lower-case the scheme and domain, drop tracking
          parameters (utm_..., igsh, igshid, fbclid, gclid) and a trailing
          "/". http and https, and a "www.", are kept as written.

Step 6 — Write a closing time of midnight as 24:00, the same way as
          clean_osm.py: "10:00-00:00" → "10:00-24:00", and in a split shift
          "11:00-15:00, 18:00-00:00" → "11:00-15:00, 18:00-24:00". Opening at
          midnight ("00:00-02:00") and closing after it ("17:00-01:00") are
          kept. Only the day columns change; hours_raw stays as Google sent it.
"""

import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import phonenumbers

# Lets `src` be imported when this file is run directly, not through run_2_preprocessing.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.categories import allowed_values

INPUT_CSV = os.path.join("data", "1_raw", "google_raw.csv")
OUTPUT_CSV = os.path.join("data", "2_cleaned", "google_cleaned.csv")

_BUSINESS_STATUS_MAP = {
    "CLOSED_PERMANENTLY": "PERMANENTLY_CLOSED",
    "CLOSED_TEMPORARILY": "TEMPORARILY_CLOSED",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_status(status):
    """Rename Google's status values; an empty or unknown one becomes UNKNOWN."""
    s = _BUSINESS_STATUS_MAP.get(status.strip(), status.strip())
    return s if s in allowed_values("restaurant.business_status") else "UNKNOWN"


def _valid_rating(value):
    """Return True if value is a float between 1.0 and 5.0 inclusive."""
    try:
        r = float(value)
        return 1.0 <= r <= 5.0
    except (TypeError, ValueError):
        return False


# Numbers that can be dialled only inside Malaysia (1-300, 1-700, 1-800):
# kept in their Malaysian form, 1-300-88-2525.
_DIAL_IN_MALAYSIA_ONLY = {
    phonenumbers.PhoneNumberType.TOLL_FREE,
    phonenumbers.PhoneNumberType.SHARED_COST,
    phonenumbers.PhoneNumberType.UAN,
    phonenumbers.PhoneNumberType.PREMIUM_RATE,
}


def _standardise_phone(phone):
    """Return the first valid Malaysian number in a value, read by the
    phonenumbers library. The same function is in src/s2_cleaners/clean_osm.py
    (which also reports how each value was read); change both together.

        03-7865 6815   → +603-78656815
        011-2306 3718  → +6011-23063718
        1-300-88-2525  → 1-300-88-2525
    A value with no valid Malaysian number is kept as written.
    """
    raw = phone.strip()
    for part in re.split(r"[;/,]", raw):
        part = part.strip()
        if not part:
            continue
        try:
            number = phonenumbers.parse(part, "MY")
        except phonenumbers.NumberParseException:
            continue
        if number.country_code != 60 or not phonenumbers.is_valid_number(number):
            continue
        national = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
        if phonenumbers.number_type(number) in _DIAL_IN_MALAYSIA_ONLY:
            return national
        if "-" not in national:
            return f"+60{number.national_number}"
        code, rest = national.split("-", 1)  # "03", "7865 6815"
        digits = re.sub(r"\D", "", rest)
        return f"+60{code.lstrip('0')}-{digits}"
    return raw


# Query parameters that only track where a click came from. The same rule is
# in src/s2_cleaners/clean_osm.py; change both together.
_TRACKING_PARAMETER = re.compile(r"^(utm_\w*|igsh|igshid|fbclid|gclid)$", re.IGNORECASE)


def _tidy_website(url):
    """Tidy a link only in ways that cannot break it: lower-case the scheme
    and domain, drop tracking parameters and a trailing "/". http/https and
    "www." are kept as written. A value that is not a full link is returned
    as it is."""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.scheme or not parts.netloc:
        return url
    query = parts.query
    pairs = parse_qsl(query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if not _TRACKING_PARAMETER.match(k)]
    if len(kept) != len(pairs):
        query = urlencode(kept)
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, parts.fragment)
    )


DAY_COLUMNS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_CLOSING_MIDNIGHT = re.compile(r"-00:00(?!\d)")


def _closing_midnight_as_24(hours):
    """Write a closing time of midnight as 24:00: "10:00-00:00" →
    "10:00-24:00". An opening at midnight ("00:00-02:00") is kept. The same
    function is in src/s2_cleaners/clean_osm.py; change both together."""
    return _CLOSING_MIDNIGHT.sub("-24:00", hours)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if not os.path.exists(INPUT_CSV):
        sys.exit(f"ERROR: {INPUT_CSV} not found. Run extraction first.")

    with open(INPUT_CSV, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    total_before = len(rows)

    # Step 1 — normalise business_status
    status_remapped = 0
    status_defaulted = 0
    for row in rows:
        original = row.get("business_status", "").strip()
        normalised = _normalise_status(original)
        if normalised != original:
            row["business_status"] = normalised
            if original in _BUSINESS_STATUS_MAP:
                status_remapped += 1
            else:
                status_defaulted += 1

    # Step 2 — validate rating_score (clear invalid, keep row)
    rating_cleared = 0
    for row in rows:
        val = row.get("rating_score", "").strip()
        if val and not _valid_rating(val):
            row["rating_score"] = ""
            rating_cleared += 1

    # Step 3 — standardise phone numbers
    phone_changed = 0
    for row in rows:
        original = row.get("phone", "")
        standardised = _standardise_phone(original)
        if standardised != original:
            row["phone"] = standardised
            phone_changed += 1

    # Step 4 — tidy the address fields (clear postcodes that are not 5 digits)
    postcode_cleared = 0
    for row in rows:
        for field in ("formatted_address", "postcode", "street"):
            if field in row:
                row[field] = row[field].strip()
        if row.get("postcode") and not re.fullmatch(r"\d{5}", row["postcode"]):
            row["postcode"] = ""
            postcode_cleared += 1

    # Step 5 — tidy websites (only changes that cannot break the link)
    website_tidied = 0
    for row in rows:
        tidied = _tidy_website(row.get("website", ""))
        if tidied != row.get("website", ""):
            row["website"] = tidied
            website_tidied += 1

    # Step 6 — write a closing time of midnight as 24:00
    midnight_changed = 0
    for row in rows:
        for day in DAY_COLUMNS:
            written = _closing_midnight_as_24(row.get(day, ""))
            if written != row.get(day, ""):
                row[day] = written
                midnight_changed += 1

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    print(f"  Input  : {INPUT_CSV}")
    print(f"  Before : {total_before} rows")
    print(f"    business_status renamed (CLOSED_...)          : {status_remapped}")
    print(f"    business_status empty/unknown → UNKNOWN       : {status_defaulted}")
    print(f"    rating_score cleared (out of range)           : {rating_cleared}")
    print(f"    phone numbers standardised                    : {phone_changed}")
    print(f"    postcodes cleared (not 5 digits)              : {postcode_cleared}")
    print(f"    websites tidied                               : {website_tidied}")
    print(f"    days closing 00:00 → 24:00                    : {midnight_changed}")
    print(f"  After  : {len(rows)} rows -> {OUTPUT_CSV}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)
    main()
