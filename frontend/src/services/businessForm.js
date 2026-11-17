import { useEffect, useState } from "react";
import { getBusinessOptions } from "../api/businessApi.js";
import { defaultHours, hoursErrors } from "./businessHours.js";

export const BUSINESS_STEPS = ["Business & location", "Public information", "Verify & submit"];


// The lists come from the backend (GET /business/options), which reads src/reference/categories.json,
// so the form always offers what the pipeline accepts. They are empty until loadBusinessOptions()
// has finished: render the form only after useBusinessOptions() says "ready".
export let BUSINESS_STYLES = [];
export let RESTAURANT_TYPES = [];
// restaurant.business_status a business can register with: OPERATIONAL (Open now), FUTURE_OPENING
export let BUSINESS_STATUSES = [];
export let CUISINES = [];            // [{value, label, definition, category}]
export let SERVICE_STYLES = [];
export let TARGET_SEGMENTS = [];
export let AMBIANCES = [];
export let FACILITY_GROUPS = [];     // [{key, title, items: [{value, label}]}], facility.category order
export let MAX_CUISINES = 3;
export let MAX_TARGET_SEGMENTS = 3;
export let MAX_AMBIANCES = 2;
export let CITY = "Petaling Jaya, Selangor";

function setBusinessOptions(options) {
  BUSINESS_STYLES = options.businessStyles;
  RESTAURANT_TYPES = options.restaurantTypes;
  BUSINESS_STATUSES = options.businessStatuses;
  CUISINES = options.cuisines;
  SERVICE_STYLES = options.serviceStyles;
  TARGET_SEGMENTS = options.targetSegments;
  AMBIANCES = options.ambiances;
  FACILITY_GROUPS = options.facilityGroups;
  MAX_CUISINES = options.limits.cuisines;
  MAX_TARGET_SEGMENTS = options.limits.targetSegments;
  MAX_AMBIANCES = options.limits.ambiance;
  CITY = options.city;
}

let optionsRequest = null;
let optionsReady = false;

export function loadBusinessOptions() {
  optionsRequest ??= getBusinessOptions().then(
    (options) => {
      setBusinessOptions(options);
      optionsReady = true;
    },
    (error) => {
      optionsRequest = null;
      throw error;
    },
  );
  return optionsRequest;
}

// "loading", "ready" or "error"; retry() asks again after an error.
export function useBusinessOptions() {
  const [state, setState] = useState(optionsReady ? "ready" : "loading");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (optionsReady) return undefined;
    let alive = true;
    loadBusinessOptions().then(() => alive && setState("ready"), () => alive && setState("error"));
    return () => { alive = false; };
  }, [attempt]);
  return { state, retry: () => { setState("loading"); setAttempt((value) => value + 1); } };
}

// The form's own halal choices; the backend saves them as business_profile.halal_status
// (halal or non-halal) with a certified yes/no.
export const HALAL_STATUSES = [
  { value: "halal_certified", label: "Halal (Certified)" },
  { value: "halal_not_certified", label: "Halal (Not Certified)" },
  { value: "not_halal", label: "Not Halal" },
];

export const YES_NO = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
];

export const MAX_DESCRIPTION = 1000;
export const MAX_AVERAGE_SPEND = 1000;

// "SS 21 (Damansara Uptown, Damansara Utama)" -> "SS 21"
export const shortArea = (area) => (area ?? "").replace(/\s*\(.*\)$/, "");
export const DEFAULT_LOCATION = { latitude: 3.1189, longitude: 101.6187 };

export const MAX_FILE_BYTES = 10 * 1024 * 1024;   // also MAX_FILE_BYTES in backend/app/business/submissions.py
export const DOCUMENT_TYPES = ["application/pdf", "image/jpeg", "image/png"];
export const PHOTO_TYPES = ["image/jpeg", "image/png"];

export function emptyBusinessForm() {
  return {
    managerName: "", managerPhone: "",
    businessName: "", businessStyle: "independent", brandName: "",
    businessPhone: "", businessEmail: "", restaurantType: "", businessStatus: "OPERATIONAL", website: "",
    address: "", postcode: "", area: "", location: { ...DEFAULT_LOCATION },
    ssmNumber: "", ssmCertificate: null, premisesLicence: null, storefrontPhoto: null,
    halalStatus: "", halalCertificate: null, halalExpiry: "", sellsPork: "", servesAlcohol: "",
    hours: defaultHours(),
    cuisines: [], serviceStyle: "", targetSegments: [], ambiance: [], averageSpend: "", description: "",
    facilities: [],
  };
}

export const isChain = (style) => style === "local_chain" || style === "international_chain";

// Form sections in page order; the last three are on step 2.
export const FORM_SECTIONS = [
  "Store manager information", "General information", "Business location", "Business verification", "Halal status",
  "Opening hours", "Food & dining experience", "Facilities & services",
];
export const sectionStep = (title) => (FORM_SECTIONS.indexOf(title) >= 5 ? 1 : 0);
export const sectionId = (title) => `section-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

// The section each field is in. Field ids are stored with the admin's marks in the database
// (submission_field_check.field), so never rename one.
const SECTION_FIELDS = {
  "Store manager information": ["managerName", "managerPhone"],
  "General information": ["businessName", "businessStyle", "brandName", "businessPhone", "businessEmail", "restaurantType", "businessStatus", "website"],
  "Business location": ["address", "postcode", "location"],
  "Business verification": ["ssmNumber", "ssmCertificate", "premisesLicence", "storefrontPhoto"],
  "Halal status": ["halalStatus", "halalExpiry", "halalCertificate", "sellsPork", "servesAlcohol"],
  "Opening hours": ["hours"],
  "Food & dining experience": ["cuisines", "serviceStyle", "averageSpend", "targetSegments", "ambiance", "description"],
};
export function sectionOf(field) {
  if (field === "facilities" || field.startsWith("facilities-")) return "Facilities & services";
  return Object.keys(SECTION_FIELDS).find((title) => SECTION_FIELDS[title].includes(field)) ?? "General information";
}
export const stepOf = (field) => sectionStep(sectionOf(field));

// The admin's flags from a rejected submission ({field, label, note}) as the form shows them: a
// field's flag on that field; a facility group's flag on the Facilities section, with its group key
// ("all" for the flag on Facilities when none were picked).
export function asFlags(issues = []) {
  return issues.map((issue) => {
    const group = issue.field === "facilities" ? "all"
      : issue.field.startsWith("facilities-") ? issue.field.slice("facilities-".length) : null;
    const label = group && group !== "all"
      ? `Facilities: ${FACILITY_GROUPS.find((item) => item.key === group)?.title ?? group}` : issue.label;
    return { section: sectionOf(issue.field), field: group ? undefined : issue.field, group, label, note: issue.note };
  });
}

// The facilities picked in one group (for a facility group's flag: changed or not).
export function groupFacilities(facilities, groupKey) {
  const group = FACILITY_GROUPS.find((item) => item.key === groupKey);
  return group ? group.items.map((item) => item.value).filter((value) => facilities.includes(value)) : [];
}

// Closed or 24-hour days still need a period in case they're reopened.
export function formForEditing(saved) {
  const base = emptyBusinessForm();
  return {
    ...base,
    ...saved,
    hours: saved.hours.map((day, index) => ({ ...day, periods: day.periods.length ? day.periods : base.hours[index].periods })),
  };
}

const digits = (value) => value.replace(/[\s-]/g, "");
// After the fixed +60: mobile (12-345 6789) or landline (3-7955 1234), leading 0 allowed.
const LOCAL_PHONE = /^0?[1-9]\d{7,9}$/;

export function fullPhone(local) {
  return `+60${digits(local).replace(/^0/, "")}`;
}
const EMAIL_LOCAL = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/;
const DOMAIN_LABEL = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/;

// One @, no stray dots or spaces in the name, and a domain ending in 2+ letters (cafe.com.my).
export function emailError(value) {
  const email = value.trim();
  if (!email) return "Enter the business email.";
  if (/\s/.test(email)) return "An email can't contain spaces.";
  const at = email.split("@");
  if (at.length !== 2) return at.length < 2 ? "An email needs an @, such as hello@cafe.my." : "An email has only one @.";
  const [local, domain] = at;
  if (!local || !domain) return "Enter a full email, such as hello@cafe.my.";
  const labels = domain.split(".");
  const validDomain = labels.length >= 2 && labels.every((label) => DOMAIN_LABEL.test(label)) && /^[A-Za-z]{2,}$/.test(labels.at(-1));
  if (email.length > 254 || local.length > 64 || !EMAIL_LOCAL.test(local) || !validDomain) {
    return "Enter a valid email, such as hello@cafe.my.";
  }
  return null;
}

function websiteError(value) {
  const text = value.trim();
  if (!text || text === "https://" || text === "http://") return null;
  try {
    const url = new URL(text);
    if ((url.protocol === "http:" || url.protocol === "https:") && url.hostname.includes(".")) return null;
  } catch {
    // Invalid URL: fall through to the message below.
  }
  return "Enter a full link, such as https://foodsight.my.";
}

export function fileError(file, types) {
  if (!file) return null;
  if (!types.includes(file.type)) return types.includes("application/pdf") ? "Upload a PDF, JPG or PNG file." : "Upload a JPG or PNG file.";
  if (file.size > MAX_FILE_BYTES) return "This file is over 10 MB.";
  return null;
}

export function formatFileSize(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function todayIso(now = new Date()) {
  const pad = (number) => String(number).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

// Errors are keyed by field, in page order (the first one is scrolled to).
export function businessStepOneErrors(form, today = todayIso()) {
  const errors = {};
  const required = (field, message) => {
    if (!String(form[field] ?? "").trim()) errors[field] = message;
  };
  const phone = (field, message) => {
    if (!form[field].trim()) errors[field] = message;
    else if (!LOCAL_PHONE.test(digits(form[field]))) errors[field] = "Enter the number after +60, such as 12-345 6789.";
  };

  required("managerName", "Enter the store manager's full name.");
  phone("managerPhone", "Enter a contact phone number.");
  required("businessName", "Enter the business name.");
  if (isChain(form.businessStyle)) required("brandName", "Enter the brand name.");
  phone("businessPhone", "Enter the business phone number.");
  const email = emailError(form.businessEmail);
  if (email) errors.businessEmail = email;
  required("restaurantType", "Choose the restaurant type.");
  required("businessStatus", "Choose the status.");
  const website = websiteError(form.website);
  if (website) errors.website = website;

  required("address", "Enter the street address.");
  if (!form.postcode.trim()) errors.postcode = "Enter the postcode.";
  else if (!/^\d{5}$/.test(form.postcode.trim())) errors.postcode = "A postcode has 5 digits.";
  // The area is worked out from the pin (GET /business/area): none means the pin is outside PJ
  if (!form.location) errors.location = "Place the pin on your entrance.";
  else if (!form.area) errors.location = "Place the pin inside Petaling Jaya.";

  if (!form.ssmNumber.trim()) errors.ssmNumber = "Enter the SSM registration number.";
  else if (!/^\d{12}$/.test(digits(form.ssmNumber))) errors.ssmNumber = "An SSM registration number has 12 digits.";
  if (!form.ssmCertificate) errors.ssmCertificate = "Upload the SSM certificate.";
  if (!form.storefrontPhoto) errors.storefrontPhoto = "Upload a photo of the storefront.";

  if (!form.halalStatus) errors.halalStatus = "Choose the halal status.";
  if (form.halalStatus === "halal_certified") {
    if (!form.halalCertificate) errors.halalCertificate = "Upload the halal certificate.";
    if (!form.halalExpiry) errors.halalExpiry = "Choose the certificate's expiration date.";
    else if (form.halalExpiry < today) errors.halalExpiry = "This certificate has expired.";
  }
  if (form.halalStatus === "not_halal") {
    if (!form.sellsPork) errors.sellsPork = "Choose Yes or No.";
    if (!form.servesAlcohol) errors.servesAlcohol = "Choose Yes or No.";
  }
  return errors;
}

// Everything on step 2 is required except Facilities & services.
export function businessStepTwoErrors(form) {
  const errors = { ...hoursErrors(form.hours) };
  if (!form.cuisines.length) errors.cuisines = "Pick at least one cuisine.";
  if (!form.serviceStyle) errors.serviceStyle = "Choose the service style.";
  const spend = form.averageSpend.trim();
  if (!spend) errors.averageSpend = "Enter what one person usually spends.";
  else if (!/^\d+(\.\d{1,2})?$/.test(spend) || Number(spend) <= 0) errors.averageSpend = "Enter an amount in RM, such as 12.50.";
  else if (Number(spend) > MAX_AVERAGE_SPEND) errors.averageSpend = `Enter an amount up to RM${MAX_AVERAGE_SPEND}.`;
  if (!form.targetSegments.length) errors.targetSegments = "Pick at least one group of diners.";
  if (!form.ambiance.length) errors.ambiance = "Pick at least one ambiance.";
  else if (form.ambiance.includes("lively") && form.ambiance.includes("quiet")) {
    errors.ambiance = "A place can't be both lively and quiet. Pick one.";
  }
  const description = form.description.trim();
  if (!description) errors.description = "Write a short description of the restaurant.";
  else if (description.length > MAX_DESCRIPTION) errors.description = `Keep the description to ${MAX_DESCRIPTION} characters.`;
  return errors;
}
