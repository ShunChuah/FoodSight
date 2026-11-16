const GEOMETRY_TYPES = { area: ["Polygon", "MultiPolygon"], radius: ["Point"], density: ["MultiPoint"] };

export const OVERLAY_GROUPS = [
  { id: "areas", kind: "area", label: "Area boundaries" },
  { id: "radius", kind: "radius", label: "Search radius" },
  { id: "density", kind: "density", label: "Competitor density" },
];

const FIRST_ROLES = /^(Best Overall Opportunity|Best Fit|Strongest Existing Market|Area Assessment)$/;
const RANK_COLORS = ["#16a34a", "#2563eb", "#9333ea", "#0891b2", "#ca8a04"];
export const SEARCHED_AREA_COLOR = "#ff6129";
export const RADIUS_COLOR = "#2563eb";

const FACTS = {
  role: ["Role", (value) => value],
  score: ["Opportunity score", (value) => `${value}/100`],
  restaurants: ["Restaurants", (value) => value.toLocaleString()],
  competitors: ["Direct competitors", (value) => value.toLocaleString()],
  competitor_share: ["Competitor share", (value) => `${value}%`],
  area_price: ["Average price", (value) => `RM${value}`],
  radius_m: ["Search radius", (value) => (value >= 1000 ? `${value / 1000} km` : `${value} m`)],
  places: ["Places", (value) => value.toLocaleString()],
};

function validGeometry(overlay) {
  const types = GEOMETRY_TYPES[overlay?.kind];
  return Boolean(types?.includes(overlay.geometry?.type) && Array.isArray(overlay.geometry.coordinates));
}

export function mapOverlays(mapData) {
  return (Array.isArray(mapData?.overlays) ? mapData.overlays : [])
    .filter((overlay) => typeof overlay?.id === "string" && validGeometry(overlay));
}

export function overlayGroups(mapData) {
  const kinds = new Set(mapOverlays(mapData).map((overlay) => overlay.kind));
  return OVERLAY_GROUPS.filter((group) => kinds.has(group.kind));
}

// The first choice is green, the other compared areas follow by rank, and a searched area takes the marker colour.
export function areaColor(overlay) {
  const { role, rank } = overlay?.properties ?? {};
  if (role && FIRST_ROLES.test(role)) return RANK_COLORS[0];
  if (Number.isInteger(rank) && rank >= 1) return RANK_COLORS[(rank - 1) % RANK_COLORS.length];
  return SEARCHED_AREA_COLOR;
}

function humanise(key) {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function overlayFacts(properties = {}) {
  return Object.entries(properties)
    .filter(([key, value]) => key !== "rank" && value !== null && value !== undefined && value !== "")
    .map(([key, value]) => {
      const [label, format] = FACTS[key] ?? [humanise(key), (item) => (typeof item === "number" ? item.toLocaleString() : String(item))];
      return [label, format(value)];
    });
}

export function legendEntries(mapData) {
  const entries = [];
  for (const overlay of mapOverlays(mapData)) {
    if (overlay.kind === "area") entries.push({ id: overlay.id, color: areaColor(overlay), label: overlay.properties?.role ? `${overlay.label}: ${overlay.properties.role}` : overlay.label });
    if (overlay.kind === "radius") entries.push({ id: overlay.id, color: RADIUS_COLOR, label: overlay.properties?.radius_m ? `${overlay.label} (${FACTS.radius_m[1](overlay.properties.radius_m)})` : overlay.label });
    if (overlay.kind === "density") entries.push({ id: overlay.id, color: "#dc2626", label: overlay.label });
  }
  return entries;
}

export function polygonRings(geometry) {
  return geometry.type === "MultiPolygon" ? geometry.coordinates.flat() : geometry.coordinates;
}
