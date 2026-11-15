import { defaultHours, hoursErrors } from "./businessHours.js";

export const BUSINESS_STEPS = ["Business & location", "Public information", "Verify & submit"];


// business_profile.business_style (without "unknown")
export const BUSINESS_STYLES = [
  { value: "independent", label: "Independent" },
  { value: "international_chain", label: "International chain" },
  { value: "local_chain", label: "Local chain" },
];

// business_profile.restaurant_type
export const RESTAURANT_TYPES = [
  { value: "bakery", label: "Bakery" },
  { value: "banquet_restaurant", label: "Banquet restaurant" },
  { value: "bar_pub", label: "Bar or pub" },
  { value: "cafe", label: "Cafe" },
  { value: "canteen", label: "Canteen" },
  { value: "casual_restaurant", label: "Casual restaurant" },
  { value: "cloud_kitchen", label: "Cloud kitchen" },
  { value: "dessert_shop", label: "Dessert shop" },
  { value: "drinks_shop", label: "Drinks shop" },
  { value: "fast_food", label: "Fast food" },
  { value: "fine_dining", label: "Fine dining" },
  { value: "food_court", label: "Food court" },
  { value: "hawker_stall", label: "Hawker stall" },
  { value: "kopitiam", label: "Kopitiam" },
  { value: "mamak", label: "Mamak" },
  { value: "warung", label: "Warung" },
  { value: "other", label: "Other" },
];

// restaurant.business_status (PERMANENTLY_CLOSED and UNKNOWN don't fit a new registration)
export const BUSINESS_STATUSES = [
  { value: "OPERATIONAL", label: "Opening now" },
  { value: "FUTURE_OPENING", label: "Opening soon" },
  { value: "TEMPORARILY_CLOSED", label: "Temporarily closed" },
];

export const HALAL_STATUSES = [
  { value: "halal_certified", label: "Halal (Certified)" },
  { value: "halal_not_certified", label: "Halal (Not Certified)" },
  { value: "not_halal", label: "Not Halal" },
];

export const YES_NO = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
];

// cuisine.name
export const CUISINES = [
  "Alcohol",
  "American",
  "Bakery",
  "Bangladeshi",
  "Bubble Tea",
  "Burgers",
  "Chinese (China)",
  "Chinese (Hong Kong)",
  "Chinese (Malaysia)",
  "Chinese (Taiwan)",
  "Coffee",
  "Desserts",
  "European",
  "French",
  "Fried Chicken",
  "Fusion",
  "Healthy",
  "Hot Pot & BBQ",
  "Indian",
  "Indian Muslim",
  "Indonesian",
  "Italian",
  "Japanese",
  "Korean",
  "Latin American",
  "Malay",
  "Malaysian",
  "Mexican",
  "Middle Eastern",
  "Nepali",
  "Nyonya",
  "Other Southeast Asian",
  "Pakistani",
  "Pizza",
  "Sandwiches",
  "Seafood",
  "Snacks",
  "Sri Lankan",
  "Tea & Juice",
  "Thai",
  "Vegetarian",
  "Vietnamese",
  "Western",
  "Other",
];
export const MAX_CUISINES = 3;

// business_profile.service_style (without "unknown")
export const SERVICE_STYLES = [
  { value: "buffet", label: "Buffet" },
  { value: "counter_service", label: "Counter service" },
  { value: "delivery_only", label: "Delivery only" },
  { value: "self_service", label: "Self service" },
  { value: "table_service", label: "Table service" },
  { value: "takeaway_only", label: "Takeaway only" },
];

// business_profile.target_segment
export const TARGET_SEGMENTS = [
  { value: "business_diners", label: "Business diners" },
  { value: "commuters", label: "Commuters" },
  { value: "couples", label: "Couples" },
  { value: "families", label: "Families" },
  { value: "foreign_workers", label: "Foreign workers" },
  { value: "large_groups", label: "Large groups" },
  { value: "late_night_crowd", label: "Late-night crowd" },
  { value: "local_residents", label: "Local residents" },
  { value: "mall_shoppers", label: "Mall shoppers" },
  { value: "office_workers", label: "Office workers" },
  { value: "seniors", label: "Seniors" },
  { value: "solo_diners", label: "Solo diners" },
  { value: "students", label: "Students" },
  { value: "tourists", label: "Tourists" },
  { value: "young_adults", label: "Young adults" },
];
export const MAX_TARGET_SEGMENTS = 3;

// business_profile.ambiance
export const AMBIANCES = [
  { value: "aesthetic", label: "Aesthetic" },
  { value: "casual", label: "Casual" },
  { value: "cosy", label: "Cosy" },
  { value: "elegant", label: "Elegant" },
  { value: "lively", label: "Lively" },
  { value: "modern", label: "Modern" },
  { value: "nature", label: "Nature" },
  { value: "no_frills", label: "No frills" },
  { value: "quiet", label: "Quiet" },
  { value: "romantic", label: "Romantic" },
  { value: "scenic_view", label: "Scenic view" },
  { value: "themed", label: "Themed" },
  { value: "traditional", label: "Traditional" },
];
export const MAX_AMBIANCES = 2;

// facility.name, in the design's order. "Pet friendly" has no graph facility yet (the graph has "Dogs Allowed").
const facilities = (...pairs) => pairs.map(([value, label = value]) => ({ value, label }));
export const FACILITY_GROUPS = [
  { title: "Service", items: facilities(["Dine-in"], ["Takeout"], ["Delivery"], ["Reservations"], ["Curbside Pickup", "Curbside pickup"]) },
  { title: "Meals", items: facilities(["Breakfast"], ["Brunch"], ["Lunch"], ["Dinner"]) },
  { title: "Drinks", items: facilities(["Beer"], ["Wine"], ["Cocktails"], ["Coffee"]) },
  { title: "Menu", items: facilities(["Dessert"], ["Kids Menu", "Kids' menu"]) },
  { title: "Dietary", items: facilities(["Vegetarian Options", "Vegetarian options"]) },
  { title: "Suitability", items: facilities(["Good for Children", "Good for children"], ["Good for Groups", "Good for crowds"], ["Dogs Allowed", "Pet friendly"]) },
  { title: "Amenities", items: facilities(["Outdoor Seating", "Outdoor seating"], ["Restroom"]) },
  { title: "Entertainment", items: facilities(["Live Sports", "Live sports"], ["Live Music", "Live music"]) },
  { title: "Accessibility", items: facilities(["Wheelchair Accessible", "Wheelchair accessible"], ["Wheelchair Seating", "Wheelchair seating"], ["Wheelchair Restroom", "Wheelchair restroom"], ["Wheelchair Parking", "Wheelchair parking"]) },
  { title: "Parking", items: facilities(["Free Parking Lot", "Free parking lot"], ["Paid Parking Lot", "Paid parking lot"], ["Free Street Parking", "Free street parking"], ["Paid Street Parking", "Paid street parking"], ["Free Garage Parking", "Free garage parking"], ["Paid Garage Parking", "Paid garage parking"], ["Valet Parking", "Valet parking"]) },
  { title: "Payment", items: facilities(["Credit Card", "Credit card"], ["Debit Card", "Debit card"], ["Contactless Payment", "Contactless payment"], ["Cash Only", "Cash only"]) },
];

export const MAX_DESCRIPTION = 1000;
export const MAX_AVERAGE_SPEND = 1000;

// Must match the graph's Area names (MATCH (a:Area) RETURN a.name), snapshot from 2026-11-15.
export const AREAS = [
  "PJS 1 (Taman Petaling Utama)",
  "PJS 2 (Taman Dato Harun)",
  "PJS 3 (Taman Medan, Taman Sri Manja)",
  "PJS 4",
  "PJS 5 (Petaling Jaya Selatan, Taman Desa Ria)",
  "PJS 6 (Bandar Sunway, Desa Mentari, Kampung Lindungan)",
  "PJS 8 (Bandar Sunway, Taman Sri Subang)",
  "PJS 10 (Bandar Sunway, Taman Dato' Hormat, Taman Sri Subang, Taman Subang Indah)",
  "PJU 1 (Taman Bukit Mayang Mas)",
  "PJU 1A (Ara Damansara, Ara Putra, Seri Pilmoor Selatan, Seri Pilmoor Timur, Seri Pilmoor Utara, Taman Megah Emas)",
  "PJU 2",
  "PJU 3",
  "PJU 4",
  "PJU 5 (Kota Damansara, Sierra Damansara, Taman Sains Selangor 1, Villa Damansara)",
  "PJU 6 (Bandar Utama, Damansara Residensi)",
  "PJU 7 (Mutiara Damansara)",
  "PJU 8",
  "PJU 9 (Bandar Sri Damansara)",
  "PJU 10",
  "Seksyen 1 (PJ Old Town)",
  "Seksyen 1A (Kawasan Rukun Tetangga Jalan Carey)",
  "Seksyen 2 (PJ Old Town)",
  "Seksyen 3 (PJ Old Town)",
  "Seksyen 4 (PJ Old Town)",
  "Seksyen 5 (Bukit Gasing, Taman Petaling)",
  "Seksyen 6",
  "Seksyen 7 (PJ State)",
  "Seksyen 8",
  "Seksyen 9",
  "Seksyen 10",
  "Seksyen 11",
  "Seksyen 12",
  "Seksyen 13",
  "Seksyen 14",
  "Seksyen 16 (Seksyen 16 (Petaling Jaya))",
  "Seksyen 17 (Happy Garden)",
  "Seksyen 17A (Kampung Seri Damansara)",
  "Seksyen 18 (Taman Kanagapuram)",
  "Seksyen 19",
  "Seksyen 20 (Taman Paramount)",
  "Seksyen 21 (SEA Park)",
  "Seksyen 22 (Taman Lean Seng)",
  "Seksyen 51 (Zon Perindustrian Seksyen 51)",
  "Seksyen 51A",
  "Seksyen 52 (PJ State)",
  "SS 1 (Kampung Tunku)",
  "SS 2",
  "SS 3 (Seaport, Taman Subang, Taman Universiti)",
  "SS 4 (Kelana Jaya)",
  "SS 5 (Kelana Jaya, SS 5C)",
  "SS 6 (Kelana Jaya)",
  "SS 7 (Kelana Jaya)",
  "SS 8 (Sungai Way)",
  "SS 9 (Sungai Way)",
  "SS 9A (Sungai Way)",
  "SS 10 (Bandar Sunway, Sungai Way)",
  "SS 11",
  "SS 20 (Damansara Kim, Damansara Utama)",
  "SS 21 (Damansara Uptown, Damansara Utama)",
  "SS 22 (Damansara Jaya)",
  "SS 22A (Damansara Jaya)",
  "SS 23 (Taman SEA)",
  "SS 24 (Taman Megah)",
  "SS 25 (Taman Bukit Emas, Taman Desa Suria, Taman Mayang)",
  "SS 26 (Taman Mayang Jaya)",
];
export const CITY = "Petaling Jaya, Selangor";
export const DEFAULT_LOCATION = { latitude: 3.1189, longitude: 101.6187 };

export const MAX_FILE_BYTES = 10 * 1024 * 1024;
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
  required("area", "Choose the area.");
  if (!form.location) errors.location = "Place the pin on your entrance.";

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
