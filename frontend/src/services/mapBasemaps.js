// With an ArcGIS API key the map uses the Open (OpenStreetMap) basemap styles; without one, Esri's keyless
// raster services give the same grey and satellite looks.
const TILES = "https://services.arcgisonline.com/ArcGIS/rest/services/";
const KEYLESS = {
  light: { base: ["Canvas/World_Light_Gray_Base"], reference: ["Canvas/World_Light_Gray_Reference"] },
  dark: { base: ["Canvas/World_Dark_Gray_Base"], reference: ["Canvas/World_Dark_Gray_Reference"] },
  satellite: { base: ["World_Imagery"], reference: ["Reference/World_Boundaries_and_Places"] },
};
const STYLES = { light: "open/light-gray", dark: "open/dark-gray", satellite: "arcgis/imagery/standard" };

export function basemapSpec(basemap, darkMode, apiKey) {
  const look = basemap === "satellite" ? "satellite" : darkMode ? "dark" : "light";
  if (apiKey) return { id: look, style: STYLES[look] };
  const { base, reference } = KEYLESS[look];
  return { id: look, tiles: base.map((name) => `${TILES}${name}/MapServer`), references: reference.map((name) => `${TILES}${name}/MapServer`) };
}
