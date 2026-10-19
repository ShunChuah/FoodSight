export function pointFeatures(mapData) {
  return (mapData?.feature_collection?.features ?? []).filter((feature) => {
    const coordinates = feature.geometry?.coordinates;
    return feature.geometry?.type === "Point" && Array.isArray(coordinates)
      && coordinates.length >= 2 && Number.isFinite(coordinates[0]) && Number.isFinite(coordinates[1])
      && Math.abs(coordinates[0]) <= 180 && Math.abs(coordinates[1]) <= 90;
  });
}

export function featurePosition(feature) {
  return [feature.geometry.coordinates[1], feature.geometry.coordinates[0]];
}

export function safeWebsite(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
