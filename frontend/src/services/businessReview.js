import {
  AMBIANCES, BUSINESS_STATUSES, BUSINESS_STYLES, CITY, FACILITY_GROUPS, HALAL_STATUSES, RESTAURANT_TYPES,
  SERVICE_STYLES, TARGET_SEGMENTS, YES_NO, isChain,
} from "./businessForm.js";
import { DAYS } from "./businessHours.js";

const NOT_PROVIDED = "Not provided";
const labelIn = (options, value) => options.find((option) => option.value === value)?.label ?? NOT_PROVIDED;
const labelsIn = (options, values) => (values.length ? values.map((value) => labelIn(options, value)).join(", ") : NOT_PROVIDED);
const filled = (text) => text?.trim() || NOT_PROVIDED;

export function formatPhone(local) {
  const number = local.trim().replace(/^0/, "");
  return number ? `+60 ${number}` : NOT_PROVIDED;
}

// Parsed as a calendar date so no time zone shifts the day.
export function formatDate(iso) {
  if (!iso) return NOT_PROVIDED;
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function formatSpend(amount) {
  const value = Number(amount);
  return amount && value > 0 ? `RM ${value.toFixed(2)} per person` : NOT_PROVIDED;
}

function dayHours(day) {
  if (!day.open) return "Closed";
  if (day.allDay) return "Open 24 hours";
  return day.periods.map((period) => `${period.from} – ${period.to}`).join(", ");
}

// Consecutive days with the same hours share one line: "Monday – Saturday: 08:00 – 22:00".
export function summariseHours(hours) {
  const lines = [];
  hours.forEach((day, index) => {
    const text = dayHours(day);
    const last = lines.at(-1);
    if (last && last.text === text && last.to === index - 1) last.to = index;
    else lines.push({ from: index, to: index, text });
  });
  return lines.map(({ from, to, text }) => ({
    label: from === to ? DAYS[from] : `${DAYS[from]} – ${DAYS[to]}`,
    value: text,
  }));
}

export function reviewSections(form) {
  const halal = [{ label: "Halal status", value: labelIn(HALAL_STATUSES, form.halalStatus) }];
  if (form.halalStatus === "halal_certified") {
    halal.push({ label: "Halal certificate", value: form.halalCertificate?.name ?? NOT_PROVIDED });
    halal.push({ label: "Certificate expiration date", value: formatDate(form.halalExpiry) });
  }
  if (form.halalStatus === "not_halal") {
    halal.push({ label: "Sells pork", value: labelIn(YES_NO, form.sellsPork) });
    halal.push({ label: "Items containing alcohol", value: labelIn(YES_NO, form.servesAlcohol) });
  }

  const facilities = FACILITY_GROUPS
    .map((group) => ({ label: group.title, value: group.items.filter((item) => form.facilities.includes(item.value)).map((item) => item.label).join(", ") }))
    .filter((row) => row.value);

  return [
    { title: "Store manager information", step: 0, field: "managerName", rows: [
      { label: "Full name", value: filled(form.managerName) },
      { label: "Contact phone", value: formatPhone(form.managerPhone) },
    ] },
    { title: "General information", step: 0, field: "businessName", rows: [
      { label: "Business name", value: filled(form.businessName) },
      { label: "Business style", value: labelIn(BUSINESS_STYLES, form.businessStyle) },
      ...(isChain(form.businessStyle) ? [{ label: "Brand name", value: filled(form.brandName) }] : []),
      { label: "Business phone", value: formatPhone(form.businessPhone) },
      { label: "Business email", value: filled(form.businessEmail) },
      { label: "Restaurant type", value: labelIn(RESTAURANT_TYPES, form.restaurantType) },
      { label: "Status", value: labelIn(BUSINESS_STATUSES, form.businessStatus) },
      { label: "Website or social page", value: ["", "https://", "http://"].includes(form.website.trim()) ? NOT_PROVIDED : form.website.trim() },
    ] },
    { title: "Business location", step: 0, field: "address", rows: [
      { label: "Address", value: filled(form.address) },
      { label: "Postcode", value: filled(form.postcode) },
      { label: "Area", value: filled(form.area) },
      { label: "City", value: CITY },
      { label: "Location", value: form.location ? `${form.location.latitude.toFixed(4)}, ${form.location.longitude.toFixed(4)}` : NOT_PROVIDED },
    ] },
    { title: "Business verification", step: 0, field: "ssmNumber", rows: [
      { label: "SSM registration number", value: filled(form.ssmNumber) },
      { label: "SSM certificate", value: form.ssmCertificate?.name ?? NOT_PROVIDED },
      { label: "MBPJ food-premises licence", value: form.premisesLicence?.name ?? NOT_PROVIDED },
      { label: "Storefront photo", value: form.storefrontPhoto?.name ?? NOT_PROVIDED },
    ] },
    { title: "Halal status", step: 0, field: "halalStatus", rows: halal },
    { title: "Opening hours", step: 1, field: "hours-monday", rows: summariseHours(form.hours) },
    { title: "Food & dining experience", step: 1, field: "cuisines", rows: [
      { label: "Cuisines served", value: form.cuisines.length ? form.cuisines.join(", ") : NOT_PROVIDED },
      { label: "Service style", value: labelIn(SERVICE_STYLES, form.serviceStyle) },
      { label: "Average spend per person", value: formatSpend(form.averageSpend) },
      { label: "Who usually dines here", value: labelsIn(TARGET_SEGMENTS, form.targetSegments) },
      { label: "Ambiance", value: labelsIn(AMBIANCES, form.ambiance) },
      { label: "Short description", value: filled(form.description) },
    ] },
    { title: "Facilities & services", step: 1, field: "facilities-title", rows: facilities.length ? facilities : [{ label: "Facilities", value: "None selected" }] },
  ];
}
