import {
  AMBIANCES, BUSINESS_STATUSES, BUSINESS_STYLES, FACILITY_GROUPS, HALAL_STATUSES, RESTAURANT_TYPES, SERVICE_STYLES,
  TARGET_SEGMENTS, YES_NO, formatFileSize, isChain,
} from "./businessForm.js";
import { formatDate, formatPhone, formatSpend, summariseHours } from "./businessReview.js";

const DAY = 24 * 60 * 60 * 1000;
const NOT_PROVIDED = "Not provided";
const labelIn = (options, value) => options.find((option) => option.value === value)?.label ?? NOT_PROVIDED;
const labelsIn = (options, values) => (values.length ? values.map((value) => labelIn(options, value)).join(", ") : NOT_PROVIDED);
const filled = (text) => text?.trim() || NOT_PROVIDED;

export const REVIEW_STATUS = {
  not_started: { label: "Not started", tone: "neutral" },
  in_progress: { label: "In progress", tone: "info" },
};

export function reviewStatus(submission) {
  if (submission.status !== "waiting") return submission.status;
  return Object.keys(submission.review).length ? "in_progress" : "not_started";
}

// "SS 21 (Damansara Uptown, Damansara Utama)" -> "SS 21"
export const shortArea = (area) => area.replace(/\s*\(.*\)$/, "");

export function formatDay(iso) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(iso) {
  const date = new Date(iso);
  const time = date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return `${formatDay(iso)}, ${time}`;
}

const plural = (count, unit) => `${count} ${unit}${count === 1 ? "" : "s"}`;

// Waiting 3 days or more is shown as overdue.
export function waitingTime(iso, now = Date.now()) {
  const hours = Math.floor((now - new Date(iso).getTime()) / (60 * 60 * 1000));
  if (hours < 1) return { text: "Under an hour", overdue: false };
  if (hours < 24) return { text: plural(hours, "hour"), overdue: false };
  const days = Math.floor(hours / 24);
  return { text: plural(days, "day"), overdue: days >= 3 };
}

const file = (key, label, value) => ({
  key, label, kind: "file", value: value ? `${value.name} · ${formatFileSize(value.size)}` : NOT_PROVIDED, file: value,
});

// Item keys match the form field ids, so a flag can point the owner back at the field.
export function reviewSections(form) {
  const halal = [{ key: "halalStatus", label: "Halal status", value: labelIn(HALAL_STATUSES, form.halalStatus) }];
  if (form.halalStatus === "halal_certified") {
    halal.push({ key: "halalExpiry", label: "Certificate expiration date", value: formatDate(form.halalExpiry) });
    halal.push({ ...file("halalCertificate", "Halal certificate", form.halalCertificate), group: "Halal certificate" });
  }
  if (form.halalStatus === "not_halal") {
    halal.push({ key: "sellsPork", label: "Sells pork", value: labelIn(YES_NO, form.sellsPork) });
    halal.push({ key: "servesAlcohol", label: "Items containing alcohol", value: labelIn(YES_NO, form.servesAlcohol) });
  }

  const facilities = FACILITY_GROUPS
    .map((group) => ({
      key: `facilities-${group.title}`,
      label: group.title,
      value: group.items.filter((item) => form.facilities.includes(item.value)).map((item) => item.label).join(", "),
    }))
    .filter((item) => item.value);

  const website = ["", "https://", "http://"].includes(form.website.trim()) ? "" : form.website.trim();

  return [
    { title: "Store manager information", items: [
      { key: "managerName", label: "Full name", value: filled(form.managerName) },
      { key: "managerPhone", label: "Contact phone", value: formatPhone(form.managerPhone) },
    ] },
    { title: "General information", items: [
      { key: "businessName", label: "Business name", value: filled(form.businessName) },
      { key: "businessStyle", label: "Business style", value: labelIn(BUSINESS_STYLES, form.businessStyle) },
      ...(isChain(form.businessStyle) ? [{ key: "brandName", label: "Brand name", value: filled(form.brandName) }] : []),
      { key: "businessPhone", label: "Business phone", value: formatPhone(form.businessPhone) },
      { key: "businessEmail", label: "Business email", value: filled(form.businessEmail) },
      { key: "restaurantType", label: "Restaurant type", value: labelIn(RESTAURANT_TYPES, form.restaurantType) },
      { key: "businessStatus", label: "Status", value: labelIn(BUSINESS_STATUSES, form.businessStatus) },
      { key: "website", label: "Website or social page", value: website || NOT_PROVIDED, kind: website ? "link" : "text" },
    ] },
    { title: "Business location", items: [
      { key: "address", label: "Address", value: filled(form.address) },
      { key: "postcode", label: "Postcode", value: filled(form.postcode) },
      { key: "area", label: "Area · City", value: `${shortArea(form.area)} · Petaling Jaya` },
      { key: "location", label: "Map pin", kind: "map", value: `${form.location.latitude.toFixed(4)}, ${form.location.longitude.toFixed(4)}`, location: form.location },
    ] },
    { title: "Business verification", items: [
      { key: "ssmNumber", label: "SSM registration number", value: filled(form.ssmNumber) },
      { ...file("ssmCertificate", "SSM certificate", form.ssmCertificate), group: "Documents" },
      { ...file("premisesLicence", "MBPJ food-premises licence", form.premisesLicence), group: "Documents" },
      { ...file("storefrontPhoto", "Storefront photo", form.storefrontPhoto), group: "Documents" },
    ] },
    { title: "Halal status", items: halal },
    { title: "Opening hours", items: [{ key: "hours", label: "Opening hours", kind: "hours", lines: summariseHours(form.hours) }] },
    { title: "Food & dining experience", items: [
      { key: "cuisines", label: "Cuisines served", value: form.cuisines.length ? form.cuisines.join(", ") : NOT_PROVIDED },
      { key: "serviceStyle", label: "Service style", value: labelIn(SERVICE_STYLES, form.serviceStyle) },
      { key: "averageSpend", label: "Average spend per person", value: formatSpend(form.averageSpend) },
      { key: "targetSegments", label: "Who usually dines here", value: labelsIn(TARGET_SEGMENTS, form.targetSegments) },
      { key: "ambiance", label: "Ambiance", value: labelsIn(AMBIANCES, form.ambiance) },
      { key: "description", label: "Short description", value: filled(form.description) },
    ] },
    { title: "Facilities & services", items: facilities.length ? facilities : [{ key: "facilities", label: "Facilities", value: "None selected" }] },
  ];
}

// Next is allowed once every item is checked or flagged, and every flag says what needs fixing.
export function reviewProgress(sections, review) {
  const items = sections.flatMap((section) => section.items);
  const done = items.filter((item) => review[item.key]?.state).length;
  const missingNotes = items.filter((item) => review[item.key]?.state === "flagged" && !review[item.key].note.trim()).length;
  return { done, total: items.length, missingNotes, complete: done === items.length && missingNotes === 0 };
}

export function flaggedIssues(sections, review) {
  return sections.flatMap((section) => section.items
    .filter((item) => review[item.key]?.state === "flagged")
    .map((item) => ({ key: item.key, section: section.title, label: item.label, note: review[item.key].note })));
}

export const EMPTY_FILTERS = { date: "", reviewStatus: "", area: "", halalStatus: "", sort: "oldest" };

const sameDay = (iso, day) => {
  const date = new Date(iso);
  const [year, month, dayOfMonth] = day.split("-").map(Number);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === dayOfMonth;
};

export function visibleSubmissions(submissions, tab, filters, search) {
  const query = search.trim().toLowerCase();
  const rows = submissions.filter((submission) => {
    const { form } = submission;
    if (submission.status !== tab) return false;
    if (filters.date && !sameDay(submission.submittedAt, filters.date)) return false;
    if (filters.reviewStatus && reviewStatus(submission) !== filters.reviewStatus) return false;
    if (filters.area && form.area !== filters.area) return false;
    if (filters.halalStatus && form.halalStatus !== filters.halalStatus) return false;
    if (!query) return true;
    return [form.businessName, form.managerName, form.ssmNumber].some((text) => text.toLowerCase().includes(query));
  });
  const direction = filters.sort === "newest" ? -1 : 1;
  return rows.sort((a, b) => direction * (new Date(a.submittedAt) - new Date(b.submittedAt)));
}

export function decidedWithin(submissions, status, days, now = Date.now()) {
  return submissions.filter((submission) => submission.status === status && now - new Date(submission.decidedAt) <= days * DAY).length;
}

// Monday of each of the last `count` weeks, oldest first.
export function weekStarts(count, now = new Date()) {
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7));
  return Array.from({ length: count }, (_, index) => new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() - 7 * (count - 1 - index)));
}
