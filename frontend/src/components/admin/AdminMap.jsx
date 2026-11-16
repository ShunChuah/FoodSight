import { useEffect, useRef, useState } from "react";
import esriConfig from "@arcgis/core/config.js";
import ArcGISMap from "@arcgis/core/Map.js";
import Basemap from "@arcgis/core/Basemap.js";
import Graphic from "@arcgis/core/Graphic.js";
import Circle from "@arcgis/core/geometry/Circle.js";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer.js";
import TileLayer from "@arcgis/core/layers/TileLayer.js";
import TileInfo from "@arcgis/core/layers/support/TileInfo.js";
import MapView from "@arcgis/core/views/MapView.js";
import { basemapSpec } from "../../services/mapBasemaps";
import { useTheme } from "../../context/ThemeContext.jsx";
import "@arcgis/core/assets/esri/themes/light/main.css";

// A small ArcGIS map for the admin review page: a few pins, circles and lines (a line may
// carry a label at its middle, such as "56 m"), fitted to the view. The same basemaps as the
// chat map (services/mapBasemaps.js): keyless grey and satellite tiles unless
// VITE_ARCGIS_API_KEY is set. The satellite view shows which building a pin is on, which is
// what a Google match decision needs. The mouse wheel scrolls the page, not the map (it
// used to zoom the map out and move it away as the page was scrolled past it); zoom with
// the + and - buttons, and the fit button brings the pins back.

const API_KEY = import.meta.env.VITE_ARCGIS_API_KEY || "";
if (API_KEY) esriConfig.apiKey = API_KEY;

const PJ_CENTER = [101.6067, 3.1073];
const MAX_ZOOM = 19;
// Zoom levels to 20 for any basemap: the keyless grey tiles stop at 16 and are enlarged beyond it
const LODS = TileInfo.create({ spatialReference: { wkid: 3857 }, numLODs: 21 }).lods;

function createBasemap(spec) {
  if (spec.style) return new Basemap({ style: { id: spec.style } });
  return new Basemap({
    baseLayers: spec.tiles.map((url) => new TileLayer({ url })),
    referenceLayers: spec.references.map((url) => new TileLayer({ url })),
  });
}

// Where a pin's label sits, as text symbol offsets in points
const LABEL_PLACES = {
  above: { yoffset: 14 },
  below: { yoffset: -20 },
  left: { horizontalAlignment: "right", verticalAlignment: "middle", xoffset: -11 },
  right: { horizontalAlignment: "left", verticalAlignment: "middle", xoffset: 11 },
};

function point({ longitude, latitude }) {
  return { type: "point", longitude, latitude };
}

function graphicsFor({ points, circles, lines }) {
  const graphics = [];
  for (const circle of circles) {
    graphics.push(new Graphic({
      geometry: new Circle({ center: point(circle), radius: circle.radius, radiusUnit: "meters", geodesic: true }),
      symbol: { type: "simple-fill", color: [255, 97, 41, 0.06], outline: { color: circle.color || "#ff6129", width: 1.5, style: "dash" } },
    }));
  }
  for (const line of lines) {
    graphics.push(new Graphic({
      geometry: { type: "polyline", paths: [[line.from, line.to]], spatialReference: { wkid: 4326 } },
      symbol: { type: "simple-line", color: line.color || "#52525b", width: 2, style: "short-dash" },
    }));
    if (line.label) {
      const middle = { longitude: (line.from[0] + line.to[0]) / 2, latitude: (line.from[1] + line.to[1]) / 2 };
      graphics.push(new Graphic({
        geometry: point(middle),
        symbol: { type: "text", text: line.label, color: "#18181b", haloColor: "white", haloSize: 2, yoffset: -16, font: { size: 12, weight: "bold" } },
      }));
    }
  }
  for (const pin of points) {
    graphics.push(new Graphic({
      geometry: point(pin),
      symbol: { type: "simple-marker", style: "circle", color: pin.color, size: pin.size || 14, outline: { color: "white", width: 2 } },
    }));
    if (pin.glyph) {
      // A letter inside the pin (a shared Google place's A, B, ...)
      graphics.push(new Graphic({
        geometry: point(pin),
        symbol: { type: "text", text: pin.glyph, color: "white", verticalAlignment: "middle", font: { size: 10, weight: "bold" } },
      }));
    }
    if (pin.label) {
      // Above the pin, or (labelSide) left, right or below it, where pins close together
      // would crowd their labels
      graphics.push(new Graphic({
        geometry: point(pin),
        symbol: { type: "text", text: pin.label, color: pin.color, haloColor: "white", haloSize: 1.5,
          font: { size: 11, weight: "bold" }, ...LABEL_PLACES[pin.labelSide || "above"] },
      }));
    }
  }
  return graphics;
}

// The default for a list a page leaves out. One shared array, not a new [] each render: a
// new one would redraw and refit the map on every render (every keystroke in a note box)
const NONE = [];

// One pin alone is shown at street level; anything else is fitted with all its graphics.
// A jump, not an animation: the same call for the first view and for the fit button
function fitView(mapView, target) {
  if (!mapView || !target) return;
  mapView.when(() => {
    mapView.goTo(target, { animate: false }).then(() => {
      if (mapView.zoom > MAX_ZOOM - 0.5) mapView.zoom = MAX_ZOOM - 0.5;
    }).catch(() => {});
  });
}

export default function AdminMap({
  points = NONE, circles = NONE, lines = NONE, satellite: startSatellite = false, fitLabel = "Show the pins", className = "",
}) {
  const container = useRef(null);
  const view = useRef(null);
  const layer = useRef(null);
  const fitTarget = useRef(null);
  const { theme } = useTheme();
  const [satellite, setSatellite] = useState(startSatellite);
  const dark = theme === "dark";

  useEffect(() => {
    const graphicsLayer = new GraphicsLayer();
    const map = new ArcGISMap({ layers: [graphicsLayer] });
    const mapView = new MapView({
      container: container.current, map, center: PJ_CENTER, zoom: 15, spatialReference: { wkid: 3857 },
      constraints: { lods: LODS, snapToZoom: false, minZoom: 10, maxZoom: MAX_ZOOM, rotationEnabled: false },
      popupEnabled: false, ui: { components: ["attribution", "zoom"] },
    });
    // The wheel scrolls the page: with "none" the map neither zooms nor blocks the scroll
    mapView.navigation.actionMap.mouseWheel = "none";
    view.current = mapView;
    layer.current = graphicsLayer;
    return () => {
      mapView.destroy();
      view.current = null;
      layer.current = null;
    };
  }, []);

  useEffect(() => {
    if (view.current) view.current.map.basemap = createBasemap(basemapSpec(satellite ? "satellite" : "streets", dark, API_KEY));
  }, [satellite, dark]);

  useEffect(() => {
    const mapView = view.current;
    const graphicsLayer = layer.current;
    if (!mapView || !graphicsLayer) return;
    graphicsLayer.removeAll();
    const graphics = graphicsFor({ points, circles, lines });
    graphicsLayer.addMany(graphics);
    fitTarget.current = !graphics.length ? null
      : points.length === 1 && !circles.length ? { target: graphics[0], zoom: 17 } : graphics;
    fitView(mapView, fitTarget.current);
  }, [points, circles, lines]);

  const mapButton = "cursor-pointer rounded-[0.5rem] bg-white/95 px-3 py-1.5 text-[0.75rem] font-semibold text-ink shadow hover:text-brand";
  return (
    <div className={`relative overflow-hidden rounded-[0.75rem] border border-gray-200 dark:border-line-dark ${className}`}>
      <div ref={container} className="size-full" />
      <div className="absolute top-3 right-3 flex gap-2">
        <button type="button" onClick={() => fitView(view.current, fitTarget.current)} className={mapButton}>
          {fitLabel}
        </button>
        <button type="button" onClick={() => setSatellite((on) => !on)} className={mapButton}>
          {satellite ? "Map" : "Satellite"}
        </button>
      </div>
    </div>
  );
}
