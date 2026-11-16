// Esri World Geocoding Service: works without an API key; the key is sent when there is one.
const GEOCODER = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer";
const PJ_EXTENT = { xmin: 101.54, ymin: 3.04, xmax: 101.68, ymax: 3.2, spatialReference: { wkid: 4326 } };
const PJ_CENTRE = "101.6187,3.1189";
export const MIN_SEARCH_LENGTH = 3;

function url(path, params, apiKey) {
  const query = new URLSearchParams({ f: "json", countryCode: "MYS", searchExtent: JSON.stringify(PJ_EXTENT), location: PJ_CENTRE, ...params });
  if (apiKey) query.set("token", apiKey);
  return `${GEOCODER}/${path}?${query}`;
}

async function getJson(address, signal) {
  const response = await fetch(address, { signal });
  if (!response.ok) throw new Error(`Search failed (${response.status})`);
  const body = await response.json();
  if (body.error) throw new Error(body.error.message || "Search failed");
  return body;
}

export async function suggestPlaces(text, { signal, apiKey } = {}) {
  const query = text.trim();
  if (query.length < MIN_SEARCH_LENGTH) return [];
  const body = await getJson(url("suggest", { text: query, maxSuggestions: "6" }, apiKey), signal);
  return parseSuggestions(body);
}

export function parseSuggestions(body) {
  return (body.suggestions ?? [])
    .filter((suggestion) => !suggestion.isCollection && suggestion.text)
    .map(({ text, magicKey }) => ({ text: text.replace(/, MYS$/, ""), magicKey }));
}

// Returns { latitude, longitude, label }, or null when nothing matches.
export async function locatePlace({ text, magicKey }, { signal, apiKey } = {}) {
  const params = { SingleLine: text, maxLocations: "1", outFields: "" };
  if (magicKey) params.magicKey = magicKey;
  const body = await getJson(url("findAddressCandidates", params, apiKey), signal);
  return parseCandidate(body);
}

export function parseCandidate(body) {
  const best = body.candidates?.[0];
  if (!best?.location) return null;
  return { latitude: best.location.y, longitude: best.location.x, label: best.address?.replace(/, MYS$/, "") ?? "" };
}
