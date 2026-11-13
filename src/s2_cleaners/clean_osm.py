"""
Cleans data/1_raw/osm_raw.csv → data/2_cleaned/osm_cleaned.csv.

Step 0 — Hold back restaurants waiting for review: every osm_id listed in
          data/review/google_match_review.json is left out (and so never
          reaches merging, profiling or the database) until a person decides
          its Google match in src/reference/google_match_overrides.json and the Google
          extraction is run again. Also left out: every osm_id in
          data/reports/google_duplicates.json (the same shop mapped twice in OSM;
          the copy nearest Google's pin is kept).

Step 0b — Remove restaurants with no name: OSM gave no name (nor name:en or
          brand), so Google was not searched for them either; a restaurant
          needs a name to be stored.

Step 1 — Remove duplicate rows: when the same osm_id appears more than
          once, keep only the first occurrence.

Step 2 — Tidy spaces in all text fields: trim both ends and turn a run of
          spaces into one ("San Francisco  Coffee" → "San Francisco Coffee").
          Names are otherwise kept exactly as OSM writes them: no change of
          capitals and no characters removed ("McDonald's", "PappaRich",
          "Dough! Bakery & Cafe" stay as they are).

Step 3 — Keep only the road in the street: when addr:street holds more than
          the road ("Jalan PJU 5/3, Dataran Sunway", "Kelana Square, Jalan
          SS7/26, Kelana Jaya"), keep the comma-separated part that starts
          with a road word (Jalan, Jln, Lorong, Persiaran, ...). A street with
          no such part is kept as written.

Step 4 — Tidy websites, only in ways that cannot break the link: lower-case
          the scheme and domain, drop tracking parameters (utm_..., igsh,
          igshid, fbclid, gclid) and a trailing "/". http and https, and a
          "www.", are kept as written: some sites work only one way.

Step 5 — Validate coordinates: clear latitude and longitude (set to
          empty string) if they fall outside the bounding box for
          Petaling Jaya:
            - latitude  must be between 2.9 and 3.3
            - longitude must be between 101.4 and 101.8
          The row itself is kept — missing coords may still be useful.

Step 6 — Standardise phone numbers with the phonenumbers library (Google's
          libphonenumber):
            - A value with several numbers (split on ; / ,) keeps the first
              valid Malaysian number.
            - Landlines and mobiles: +60, the area or mobile code, a dash,
              then the digits: +603-78656815, +6012-3456789, +6011-23063718.
            - 1-300, 1-700 and 1-800 numbers keep their Malaysian form
              (1-300-88-2525): they cannot be dialled from abroad.
            - A value with no valid Malaysian number is kept as written.

Step 7 — Validate postcodes: clear the postcode unless it is 5 digits
          (Malaysian format). The row itself is kept.

Step 8 — Write a closing time of midnight as 24:00, the same way as
          clean_google.py, so one closing time is written one way:
          "10:00-00:00" → "10:00-24:00", and in a split shift
          "11:00-15:00, 18:00-00:00" → "11:00-15:00, 18:00-24:00". Opening at
          midnight ("00:00-02:00") and closing after it ("17:00-01:00") are
          kept. Only the day columns change; hours_raw stays as OSM wrote it.
"""

import csv
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import phonenumbers

INPUT_CSV = os.path.join("data", "1_raw", "osm_raw.csv")
OUTPUT_CSV = os.path.join("data", "2_cleaned", "osm_cleaned.csv")
# Written by extract_google.py: restaurants waiting for a person's review,
# and extra copies of the same shop dropped as duplicates
MATCH_REVIEW_JSON = os.path.join("data", "review", "google_match_review.json")
DUPLICATES_JSON = os.path.join("data", "reports", "google_duplicates.json")

# PJ bounding box for coordinate validation
LAT_MIN, LAT_MAX = 2.9, 3.3
LON_MIN, LON_MAX = 101.4, 101.8

# Text fields to strip whitespace from
TEXT_FIELDS = [
    "name",
    "amenity_type",
    "brand",
    "phone",
    "website",
    "full_address",
    "postcode",
    "street",
    "hours_raw",
    "cuisine_raw",
    "halal_tag",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _osm_ids_in(path, key):
    """osm_ids listed under `key` in a JSON file from extract_google.py
    (none if the file is missing)."""
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {item["osm_id"] for item in json.load(f).get(key, [])}


def _tidy_spaces(text):
    """Trim both ends and turn every run of spaces into one."""
    return re.sub(r"\s+", " ", text).strip()


# A comma-separated part that starts with one of these is the road. The same
# list is in src/s3_mergers/merge_data.py (_ROAD), which reads a street out of a
# full address; change both together.
_ROAD = re.compile(
    r"(?:Jalan|Jln|Lorong|Lrg|Persiaran|Lebuhraya|Lebuh|Lingkaran|Lintasan|Laluan|Road)\b",
    re.IGNORECASE,
)


def _road_part(street):
    """Keep only the road of a street that holds more ("Jalan PJU 5/3,
    Dataran Sunway" → "Jalan PJU 5/3"). A street without a comma, or with no
    part starting with a road word, is returned as it is."""
    if "," not in street:
        return street
    for part in street.split(","):
        part = part.strip()
        if _ROAD.match(part):
            return part
    return street


# Query parameters that only track where a click came from. The same rule is
# in src/s2_cleaners/clean_google.py; change both together.
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
    function is in src/s2_cleaners/clean_google.py; change both together."""
    return _CLOSING_MIDNIGHT.sub("-24:00", hours)


def _valid_lat(value):
    try:
        return LAT_MIN <= float(value) <= LAT_MAX
    except (TypeError, ValueError):
        return False


def _valid_lon(value):
    try:
        return LON_MIN <= float(value) <= LON_MAX
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
    """Return (phone, how) with the first valid Malaysian number in a value,
    read by the phonenumbers library. The same function is in
    src/s2_cleaners/clean_google.py; change both together.

        03-7865 6815                     → +603-78656815
        011-2306 3718                    → +6011-23063718
        +60 3-7865 6815;+60 3-7865 6816  → +603-78656815 (the first one)
        1-300-88-2525                    → 1-300-88-2525
        +603-795534321 (a digit too many) → kept as written

    `how` is "first of several" when the value held more than one number,
    "kept as written" when it held no valid Malaysian number, else "".
    """
    raw = phone.strip()
    parts = [p.strip() for p in re.split(r"[;/,]", raw) if p.strip()]
    for part in parts:
        try:
            number = phonenumbers.parse(part, "MY")
        except phonenumbers.NumberParseException:
            continue
        if number.country_code != 60 or not phonenumbers.is_valid_number(number):
            continue
        how = "first of several" if len(parts) > 1 else ""
        national = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
        if phonenumbers.number_type(number) in _DIAL_IN_MALAYSIA_ONLY:
            return national, how
        if "-" not in national:
            return f"+60{number.national_number}", how
        code, rest = national.split("-", 1)  # "03", "7865 6815"
        digits = re.sub(r"\D", "", rest)
        return f"+60{code.lstrip('0')}-{digits}", how
    return raw, ("kept as written" if raw else "")


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

    # Step 0 — hold back restaurants waiting for review, drop duplicates
    held = _osm_ids_in(MATCH_REVIEW_JSON, "items")
    duplicates = _osm_ids_in(DUPLICATES_JSON, "dropped")
    before = len(rows)
    rows = [r for r in rows if r.get("osm_id", "").strip() not in held]
    held_out = before - len(rows)
    before = len(rows)
    rows = [r for r in rows if r.get("osm_id", "").strip() not in duplicates]
    duplicates_out = before - len(rows)

    # Step 0b — remove restaurants with no name
    before = len(rows)
    rows = [r for r in rows if r.get("name", "").strip()]
    unnamed_out = before - len(rows)

    # Step 1 — remove duplicate osm_id rows
    seen_ids = set()
    deduped = []
    for row in rows:
        oid = row.get("osm_id", "").strip()
        if oid not in seen_ids:
            seen_ids.add(oid)
            deduped.append(row)
    duplicates_removed = len(rows) - len(deduped)
    rows = deduped

    # Step 2 — tidy spaces in all text fields (names otherwise kept as written)
    spaces_tidied = 0
    for row in rows:
        for field in TEXT_FIELDS:
            if field in row:
                tidied = _tidy_spaces(row[field])
                if tidied != row[field]:
                    row[field] = tidied
                    spaces_tidied += 1

    # Step 3 — keep only the road in the street
    street_trimmed = 0
    for row in rows:
        road = _road_part(row.get("street", ""))
        if road != row.get("street", ""):
            row["street"] = road
            street_trimmed += 1

    # Step 4 — tidy websites (only changes that cannot break the link)
    website_tidied = 0
    for row in rows:
        tidied = _tidy_website(row.get("website", ""))
        if tidied != row.get("website", ""):
            row["website"] = tidied
            website_tidied += 1

    # Step 5 — validate coordinates (clear out-of-bounds values)
    coords_cleared = 0
    for row in rows:
        lat = row.get("latitude", "").strip()
        lon = row.get("longitude", "").strip()
        if (lat and not _valid_lat(lat)) or (lon and not _valid_lon(lon)):
            row["latitude"] = ""
            row["longitude"] = ""
            coords_cleared += 1

    # Step 6 — standardise phone numbers
    phone_changed = 0
    phone_how = {"first of several": 0, "kept as written": 0}
    for row in rows:
        original = row.get("phone", "")
        standardised, how = _standardise_phone(original)
        if how:
            phone_how[how] += 1
        if standardised != original:
            row["phone"] = standardised
            phone_changed += 1

    # Step 7 — validate postcodes (clear anything that is not 5 digits)
    postcode_cleared = 0
    for row in rows:
        postcode = row.get("postcode", "")
        if postcode and not re.fullmatch(r"\d{5}", postcode):
            row["postcode"] = ""
            postcode_cleared += 1

    # Step 8 — write a closing time of midnight as 24:00
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
    print(f"    Held back for Google review     : {held_out}"
          + (f" (decide them in src/reference/google_match_overrides.json; see {MATCH_REVIEW_JSON})" if held_out else ""))
    print(f"    Duplicates dropped (same shop)  : {duplicates_out}"
          + (f" (see {DUPLICATES_JSON})" if duplicates_out else ""))
    print(f"    No name (removed)               : {unnamed_out}")
    print(f"    Duplicate osm_id removed        : {duplicates_removed}")
    print(f"    Text values with spaces tidied  : {spaces_tidied}")
    print(f"    Streets cut to the road part    : {street_trimmed}")
    print(f"    Websites tidied                 : {website_tidied}")
    print(f"    Coordinates cleared (out of PJ) : {coords_cleared}")
    print(f"    Phone numbers standardised      : {phone_changed}"
          f" (several numbers, first kept: {phone_how['first of several']};"
          f" no valid number, kept as written: {phone_how['kept as written']})")
    print(f"    Postcodes cleared (not 5 digits): {postcode_cleared}")
    print(f"    Days closing 00:00 → 24:00      : {midnight_changed}")
    print(f"  After  : {len(rows)} rows -> {OUTPUT_CSV}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)
    main()
