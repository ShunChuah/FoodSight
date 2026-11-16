import { featurePosition, pointFeatures, safeWebsite } from "./mapGeometry.js";
import { cuisineText, priceText } from "./mapPresentation.js";

const DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const TIME_ZONE = "Asia/Kuala_Lumpur";

export function mapPlaces(mapData) {
  return pointFeatures(mapData).map((feature, index) => {
    const [latitude, longitude] = featurePosition(feature);
    return { id: `restaurant:${feature.id ?? index}`, rank: index + 1, latitude, longitude, ...(feature.properties ?? {}) };
  });
}

function words(value) {
  if (typeof value !== "string" || !value) return null;
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function placeKind(place) {
  return cuisineText(place.cuisines)?.split(", ")[0] || words(place.restaurant_type) || words(place.venue_type) || null;
}

export function priceLabel(place) {
  if (typeof place.average_price === "number") return `RM${Math.round(place.average_price)} per person on average`;
  return priceText({ ...place, currency: place.currency === "MYR" ? "RM" : place.currency });
}

export function distanceLabel(metres) {
  if (typeof metres !== "number") return null;
  return metres >= 1000 ? `${(metres / 1000).toFixed(1)} km away` : `${Math.round(metres)} m away`;
}

const SERVICES = [["Dine-in", "Dine-in"], ["Takeout", "Takeaway"], ["Delivery", "Delivery"], ["Curbside Pickup", "Curbside pickup"]];

// The facilities worth a line of their own; payment cards, meal times and drinks are left out.
export function placeHighlights(place) {
  const has = new Set(Array.isArray(place.facilities) ? place.facilities : []);
  const lines = [];
  if (place.halal_status === "halal") lines.push(["halal", "Halal"]);
  if (place.halal_status === "non-halal") lines.push(["halal", "Not halal"]);
  const services = SERVICES.filter(([name]) => has.has(name)).map(([, label]) => label);
  if (services.length) lines.push(["services", services.join(" · ")]);
  if (has.has("Reservations")) lines.push(["reservations", "Takes reservations"]);
  const free = [...has].some((name) => /^Free .*Parking/.test(name));
  const paid = [...has].some((name) => /^(Paid|Valet) .*Parking/.test(name));
  if (free || paid) lines.push(["parking", free && paid ? "Free and paid parking" : free ? "Free parking" : "Paid parking"]);
  const groups = ["Good for Children", "Good for Groups"].filter((name) => has.has(name)).map((name) => name.slice(9).toLowerCase());
  if (groups.length) lines.push(["groups", `Good for ${groups.join(" and ")}`]);
  if (has.has("Vegetarian Options")) lines.push(["vegetarian", "Vegetarian options"]);
  if (has.has("Wheelchair Accessible")) lines.push(["accessible", "Wheelchair accessible"]);
  if (has.has("Cash Only")) lines.push(["cash", "Cash only"]);
  return lines;
}

export function directionsUrl(place) {
  return `https://www.google.com/maps/dir/?api=1&destination=${place.latitude},${place.longitude}`;
}

export function phoneUrl(phone) {
  const digits = typeof phone === "string" ? phone.replace(/[^\d+]/g, "") : "";
  return digits.length >= 7 ? `tel:${digits}` : null;
}

export function websiteUrl(place) {
  return safeWebsite(place.website);
}

function minutes(text) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(text.trim());
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

function ranges(value) {
  if (typeof value !== "string") return [];
  return value.split(",").map((part) => part.split("-").map(minutes)).filter(([start, end]) => start !== null && end !== null && start !== undefined && end !== undefined);
}

export function clockLabel(total) {
  const hour = Math.floor(total / 60) % 24;
  const minute = String(total % 60).padStart(2, "0");
  return `${hour % 12 || 12}:${minute} ${hour < 12 ? "am" : "pm"}`;
}

function malaysiaNow(now) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, weekday: "long", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
    .formatToParts(now).map((part) => [part.type, part.value]));
  return { day: DAYS.indexOf(parts.weekday.toLowerCase()), minute: Number(parts.hour) * 60 + Number(parts.minute) };
}

// Worked out when the map is viewed, in Malaysian time, so a saved chat never shows a stale "Open".
export function openStatus(place, now = new Date()) {
  if (typeof place.hours_today === "string" && /24 hours/i.test(place.hours_today)) return { open: true, text: "Open 24 hours" };
  const week = place.weekly_hours;
  if (!week || typeof week !== "object") return null;
  const { day, minute } = malaysiaNow(now);
  const today = ranges(week[DAYS[day]]);
  const yesterday = ranges(week[DAYS[(day + 6) % 7]]);
  for (const [start, end] of yesterday) {
    if (end <= start && minute < end) return { open: true, text: `Open until ${clockLabel(end)}` };
  }
  for (const [start, end] of today) {
    const close = end <= start ? end + 1440 : end;
    if (minute >= start && minute < close) return { open: true, text: close >= 1440 && close - 1440 >= start ? "Open 24 hours" : `Open until ${clockLabel(close)}` };
  }
  const later = today.find(([start]) => start > minute);
  if (later) return { open: false, text: `Closed · Opens ${clockLabel(later[0])}` };
  for (let ahead = 1; ahead <= 7; ahead += 1) {
    const [next] = ranges(week[DAYS[(day + ahead) % 7]]);
    if (next) return { open: false, text: `Closed · Opens ${ahead === 1 ? "tomorrow" : words(DAYS[(day + ahead) % 7])} ${clockLabel(next[0])}` };
  }
  return { open: false, text: "Closed" };
}

export function weekLines(place) {
  const week = place.weekly_hours;
  if (!week || typeof week !== "object") return [];
  return [1, 2, 3, 4, 5, 6, 0].map((day) => {
    const spans = ranges(week[DAYS[day]]);
    const text = spans.length ? spans.map(([start, end]) => `${clockLabel(start)} – ${clockLabel(end)}`).join(", ") : "Closed";
    return [words(DAYS[day]), text];
  });
}
