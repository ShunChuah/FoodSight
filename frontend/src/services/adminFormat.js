import { errorCode } from "../api/client.js";

// Text helpers for the admin review page (kept apart from its components for fast refresh).

const MESSAGES = {
  ADMIN_FILES_NOT_MOUNTED: "The backend cannot see the pipeline's files. Restart it with docker compose up -d.",
  ADMIN_FILE_UNREADABLE: "A pipeline file could not be read (it may be being written right now). Try again in a moment.",
  REVIEW_ITEM_NOT_FOUND: "This item is no longer waiting for review: an update has probably run. Refresh the list.",
  DECISION_ALREADY_APPLIED: "An update has already applied this decision, so it can no longer be undone here.",
  GOOGLE_PLACE_ALREADY_GIVEN: "This Google place is already given to another restaurant. Undo that decision first.",
  REVIEW_ITEM_HAS_NO_GOOGLE_PLACE: "This item has no Google place to approve.",
  NOT_IN_THIS_GROUP: "That restaurant is not one of the restaurants that matched this Google place.",
  PIN_CHOICE_NOT_ALLOWED: "Google's pin can only be chosen with Same place, when the pins are more than 50 m apart.",
  NEARBY_PLACE_NOT_FOUND: "This place is no longer in the nearby places table.",
  EXCLUSION_REASON_EMPTY: "Write why this place should not be counted.",
  REPORT_NOT_FOUND: "This change report no longer exists.",
  LOG_NOT_FOUND: "This day's log no longer exists.",
};

export function adminErrorMessage(error) {
  if (!error?.response) return "Could not reach the server. Check your connection and try again.";
  if (error.response.status === 403) return "Only admins can use this page.";
  return MESSAGES[errorCode(error)] || "Something went wrong. Please try again.";
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

// A start and end time: "17 Nov, 13:19–13:31" on one day, "17 Nov, 23:50 – 18 Nov, 00:10" across midnight.
export function formatTimeRange(start, end) {
  const from = new Date(start);
  const to = end ? new Date(end) : new Date(NaN);
  if (!start || Number.isNaN(from.getTime())) return formatDateTime(start);
  const day = (date) => date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const time = (date) => date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (Number.isNaN(to.getTime())) return `${day(from)}, ${time(from)}`;
  if (from.toDateString() === to.toDateString()) return `${day(from)}, ${time(from)}–${time(to)}`;
  return `${day(from)}, ${time(from)} – ${day(to)}, ${time(to)}`;
}

// The scheduler's reason without its consequence, which the card already shows as "Every N days":
// "The change share of 0.7% is below the 3% threshold, so the interval should be increased ..."
// -> "The change share of 0.7% is below the 3% threshold." A reason with no such clause stays whole.
const CONSEQUENCE = /,\s+(?:so|requiring|therefore|thus|hence|which|meaning|indicating|warranting|suggesting|justifying)\b/i;

export function shortReason(text) {
  if (!text) return "";
  const cut = text.search(CONSEQUENCE);
  const short = (cut > 0 ? text.slice(0, cut) : text).trim().replace(/[.;:,]+$/, "");
  return `${short.charAt(0).toUpperCase()}${short.slice(1)}.`;
}

// A plain date such as "2026-11-26", shown as that day wherever the browser is.
export function formatDay(value) {
  if (!value) return "—";
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Date(year, month - 1, day).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

export function capitalise(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1).replaceAll("_", " ") : "";
}

export function plural(count, word, many = `${word}s`) {
  return `${count} ${count === 1 ? word : many}`;
}

export const REASON_LABELS = {
  too_far: "Pins too far apart",
  name_partly_alike: "Names partly alike",
  shared_google_place: "Shared Google place",
  replaces_removed: "Replaces a removed restaurant",
};

export const REMOVED_DECISIONS = {
  closed: { label: "Closed", text: "Keep it as permanently closed: its history stays, and it no longer counts as open." },
  delete: { label: "Delete", text: "Remove it from the database, with its reviews and links, and from the graph. This cannot be undone after the update." },
  keep: { label: "Keep", text: "Leave it as it is (OpenStreetMap deleted it by mistake)." },
};

// The two sources' colours on the Google matches pages: titles, pins and table headings
export const OSM_COLOR = "#16a34a";
export const GOOGLE_COLOR = "#2563eb";

export const WEEKDAYS =["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

export const TONIGHT = "It takes effect in tonight's update (00:00, while the laptop is on).";

// 0.0066 -> "0.7%"
export function formatShare(share) {
  if (share == null) return "—";
  const percent = share * 100;
  return `${percent < 10 ? percent.toFixed(1) : Math.round(percent)}%`;
}

export function formatNumber(value) {
  return value == null ? "—" : value.toLocaleString("en-GB");
}

export function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const STAGE_LABELS = {
  "run_1_extraction.py": "1 Extraction",
  "run_2_preprocessing.py": "2 Cleaning",
  "run_3_merging.py": "3 Merging",
  "run_4_profiling.py": "4 AI profiling",
  "run_5_validation.py": "5 Validation",
  "run_6_clustering.py": "6 Clustering",
  "run_7_loading.py": "7 Loading",
  "run_8_graph.py": "8 Knowledge graph",
};

// What a run in the log is: the update runner, its status check, or a stage run by hand.
export function runLabel(run) {
  if (run.script === "run_update.py") {
    if (run.args.startsWith("--stat")) return "Status check";
    return run.args ? `Update (${run.args})` : "Update";
  }
  const stage = STAGE_LABELS[run.script] || run.script;
  return `${stage}${run.args ? ` ${run.args}` : ""}`;
}
