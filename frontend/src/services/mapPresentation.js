import { pointFeatures } from "./mapGeometry.js";

export function hasMapView(data, legacyImage = null) {
  if (data?.map_mode === "none") return false;
  return Boolean(legacyImage || pointFeatures(data).length);
}

export function cuisineText(value) {
  return Array.isArray(value) ? value.map((item) => typeof item === "string" ? item : item?.name).filter(Boolean).join(", ") : value;
}

export function priceText(data) {
  const currency = data.currency || "Currency unavailable: ";
  if (data.min_price != null && data.max_price != null) return `${currency}${data.min_price}–${data.max_price}`;
  if (data.average_price != null) return `${currency}${data.average_price} average`;
  return data.price_tier || null;
}
