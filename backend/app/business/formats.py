"""Turning the Register Business form's values into the pipeline's formats, so a submitted
restaurant looks like every other one: phones as +603-78652210, websites tidied, opening
hours as "07:00-15:00, 17:00-22:00" / "Closed" / "00:00-24:00", and the section a pin is in.

The phone and website rules are copies of src/s2_cleaners/clean_google.py (_standardise_phone,
_tidy_website); the backend container cannot import the pipeline. Change them together."""

import json
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import phonenumbers
from sqlalchemy import text

# Numbers that can be dialled only inside Malaysia (1-300, 1-700, 1-800): kept as 1-300-88-2525.
_DIAL_IN_MALAYSIA_ONLY = {
    phonenumbers.PhoneNumberType.TOLL_FREE,
    phonenumbers.PhoneNumberType.SHARED_COST,
    phonenumbers.PhoneNumberType.UAN,
    phonenumbers.PhoneNumberType.PREMIUM_RATE,
}
_TRACKING_PARAMETER = re.compile(r"^(utm_\w*|igsh|igshid|fbclid|gclid)$", re.IGNORECASE)

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
CLOSED = "Closed"
ALL_DAY = "00:00-24:00"
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def standardise_phone(local: str) -> str | None:
    """The number after +60 as the form takes it ("12-345 6789", "3-7865 2210", a leading 0
    allowed), in the pipeline's format (+6012-3456789, +603-78652210), or None when it is not a
    valid Malaysian number."""
    digits = re.sub(r"\D", "", local or "")
    if not digits:
        return None
    try:
        number = phonenumbers.parse("+60" + digits.lstrip("0"), "MY")
    except phonenumbers.NumberParseException:
        return None
    if number.country_code != 60 or not phonenumbers.is_valid_number(number):
        return None
    national = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
    if phonenumbers.number_type(number) in _DIAL_IN_MALAYSIA_ONLY:
        return national
    if "-" not in national:
        return f"+60{number.national_number}"
    code, rest = national.split("-", 1)
    return f"+60{code.lstrip('0')}-{re.sub(r'[^0-9]', '', rest)}"


def local_phone(stored: str | None) -> str:
    """A saved phone back in the form's shape: the part after +60 ("+6012-3456789" -> "12-3456789")."""
    stored = stored or ""
    return stored[3:] if stored.startswith("+60") else stored


def tidy_website(url: str) -> str | None:
    """A full http(s) link, tidied only in ways that cannot break it (lower-case scheme and
    domain, no tracking parameters, no trailing /), or None when it is not a full link."""
    url = (url or "").strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or "." not in parts.netloc:
        return None
    query = parts.query
    pairs = parse_qsl(query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if not _TRACKING_PARAMETER.match(k)]
    if len(kept) != len(pairs):
        query = urlencode(kept)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, parts.fragment))


def hours_to_columns(hours) -> tuple[dict, str | None]:
    """The form's week ([{open, allDay, periods: [{from, to}]}] for Monday to Sunday) as the
    seven day columns, or an error message. A closing time of midnight is written 24:00, as
    the pipeline does (_closing_midnight_as_24); a close after midnight (22:00-02:00) is kept."""
    if not isinstance(hours, list) or len(hours) != len(DAYS):
        return {}, "Give the opening hours for all seven days."
    columns = {}
    for day, entry in zip(DAYS, hours):
        entry = entry if isinstance(entry, dict) else {}
        if not entry.get("open"):
            columns[day] = CLOSED
            continue
        if entry.get("allDay"):
            columns[day] = ALL_DAY
            continue
        periods = entry.get("periods") or []
        if not periods:
            return {}, f"Add the opening hours for {day.title()}, or switch the day off."
        parts = []
        for period in periods:
            start, end = str(period.get("from") or ""), str(period.get("to") or "")
            if not (_TIME.match(start) and _TIME.match(end)) or start == end:
                return {}, f"Check the opening hours for {day.title()}."
            parts.append(f"{start}-{'24:00' if end == '00:00' else end}")
        columns[day] = ", ".join(parts)
        if len(columns[day]) > 50:
            return {}, f"{day.title()} has too many opening periods."
    if all(value == CLOSED for value in columns.values()):
        return {}, "Open on at least one day."
    return columns, None


def columns_to_hours(row) -> list[dict]:
    """The seven day columns back in the form's shape (the reverse of hours_to_columns)."""
    week = []
    for day in DAYS:
        value = (row.get(day) or CLOSED).strip()
        if value == CLOSED:
            week.append({"open": False, "allDay": False, "periods": []})
        elif value == ALL_DAY:
            week.append({"open": True, "allDay": True, "periods": []})
        else:
            periods = []
            for part in value.split(","):
                start, _, end = part.strip().partition("-")
                periods.append({"from": start, "to": "00:00" if end == "24:00" else end})
            week.append({"open": True, "allDay": False, "periods": periods})
    return week


# ---------------------------------------------------------------------------
# The section (public.area) a pin is in
# ---------------------------------------------------------------------------

_AREAS = {"loaded": 0.0, "shapes": []}
AREAS_RELOAD_SECONDS = 3600   # sections change only when the pipeline reloads them


def _inside_ring(lon, lat, ring):
    """Ray casting: True when the point is inside a closed ring of [lon, lat] points."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _inside_polygon(lon, lat, rings):
    """Inside the outer ring and in none of its holes."""
    return bool(rings) and _inside_ring(lon, lat, rings[0]) and not any(
        _inside_ring(lon, lat, hole) for hole in rings[1:])


def _load_areas(db):
    shapes = []
    for name, outline in db.execute(text("SELECT name, boundary_geojson FROM public.area")).all():
        try:
            geometry = json.loads(outline or "")
        except ValueError:
            continue
        if geometry.get("type") == "Polygon":
            polygons = [geometry["coordinates"]]
        elif geometry.get("type") == "MultiPolygon":
            polygons = geometry["coordinates"]
        else:
            continue
        shapes.append((name, polygons))
    _AREAS.update(loaded=time.monotonic(), shapes=shapes)


def area_for(db, latitude: float, longitude: float) -> str | None:
    """The name of the section the pin is in (as public.area.name), or None when it is outside
    Petaling Jaya. The 65 sections cover the city without gaps or overlaps."""
    if not _AREAS["shapes"] or time.monotonic() - _AREAS["loaded"] > AREAS_RELOAD_SECONDS:
        _load_areas(db)
    for name, polygons in _AREAS["shapes"]:
        if any(_inside_polygon(longitude, latitude, rings) for rings in polygons):
            return name
    return None


def short_area(name: str | None) -> str:
    """"SS 21 (Damansara Uptown, Damansara Utama)" -> "SS 21"."""
    return (name or "").split(" (")[0]
