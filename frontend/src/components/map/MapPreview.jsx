import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { X } from "lucide-react";
import esriConfig from "@arcgis/core/config.js";
import ArcGISMap from "@arcgis/core/Map.js";
import Basemap from "@arcgis/core/Basemap.js";
import Graphic from "@arcgis/core/Graphic.js";
import Circle from "@arcgis/core/geometry/Circle.js";
import Extent from "@arcgis/core/geometry/Extent.js";
import Point from "@arcgis/core/geometry/Point.js";
import * as labelPointOperator from "@arcgis/core/geometry/operators/labelPointOperator.js";
import FeatureLayer from "@arcgis/core/layers/FeatureLayer.js";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer.js";
import TileLayer from "@arcgis/core/layers/TileLayer.js";
import MapView from "@arcgis/core/views/MapView.js";
import * as reactiveUtils from "@arcgis/core/core/reactiveUtils.js";
import AttributionViewModel from "@arcgis/core/widgets/Attribution/AttributionViewModel.js";
import { basemapSpec } from "../../services/mapBasemaps";
import { RADIUS_COLOR, areaColor, legendEntries, mapOverlays, overlayFacts, overlayGroups, polygonRings } from "../../services/mapOverlays";
import { mapPlaces } from "../../services/mapPlaces";
import { SCENE_MS, applyTourScript, cinematicScenes, shortOpening } from "../../services/cinematicScript";
import { saveVoicePreference, voicePreference } from "../../services/tourVoice";
import { tourVoice } from "../../services/narrator";
import { CinematicBar } from "./CinematicBar";
import { applyMapCommand, initialMapState } from "../../services/mapState";
import { InfoCard, MapControls, MapCredits } from "./MapControls";
import { PlaceCard, PlacePanel } from "./MapPlaces";
import "@arcgis/core/assets/esri/themes/light/main.css";
import "../../styles/map.css";

const API_KEY = import.meta.env.VITE_ARCGIS_API_KEY || "";
if (API_KEY) esriConfig.apiKey = API_KEY;

const NEUTRAL_CENTER = [101.6067, 3.1073];
const MARKER_COLOR = "#ff6129";
const SELECTED_COLOR = "#c2410c";
const MAX_FIT_ZOOM = 16;
const CARD_HIDE_DELAY = 250;
const HIT_TEST_MS = 400;
const WGS84 = { wkid: 4326 };
const TOUR_MOVE_MS = 1600;

function createBasemap(spec) {
  if (spec.style) return new Basemap({ style: { id: spec.style } });
  return new Basemap({ baseLayers: spec.tiles.map((url) => new TileLayer({ url })), referenceLayers: spec.references.map((url) => new TileLayer({ url })) });
}

function dotSymbol(selected) {
  return { type: "simple-marker", style: "circle", color: selected ? SELECTED_COLOR : MARKER_COLOR, size: selected ? 18 : 13, outline: { color: "white", width: 2 } };
}

function markerRenderer(selected) {
  return { type: "unique-value", field: "placeId", defaultSymbol: dotSymbol(false), uniqueValueInfos: selected ? [{ value: selected, symbol: dotSymbol(true) }] : [] };
}

function markerLayer(places) {
  return new FeatureLayer({
    title: "Restaurants", geometryType: "point", spatialReference: WGS84, objectIdField: "ObjectID", outFields: ["*"], popupEnabled: false,
    fields: [{ name: "ObjectID", type: "oid" }, { name: "placeId", type: "string" }],
    source: places.map((place, index) => new Graphic({ geometry: { type: "point", longitude: place.longitude, latitude: place.latitude },
      attributes: { ObjectID: index + 1, placeId: place.id } })),
    renderer: markerRenderer(null),
  });
}

function areaGraphics(overlays) {
  return overlays.filter((overlay) => overlay.kind === "area").flatMap((overlay) => {
    const color = areaColor(overlay);
    const polygon = { type: "polygon", rings: polygonRings(overlay.geometry), spatialReference: WGS84 };
    const outline = new Graphic({ geometry: polygon, attributes: { overlayId: overlay.id }, symbol: { type: "simple-fill", color: `${color}29`, outline: { color, width: 2 } } });
    const name = new Graphic({ geometry: labelPointOperator.execute(outline.geometry), attributes: { overlayId: overlay.id },
      symbol: { type: "text", text: overlay.label, color, haloColor: "white", haloSize: 1.5, font: { size: 11, weight: "bold" } } });
    return [outline, name];
  });
}

function radiusGraphics(overlays) {
  return overlays.filter((overlay) => overlay.kind === "radius").flatMap((overlay) => {
    const [longitude, latitude] = overlay.geometry.coordinates;
    const center = { type: "point", longitude, latitude };
    const graphics = [new Graphic({ geometry: center, attributes: { overlayId: overlay.id }, symbol: { type: "simple-marker", color: RADIUS_COLOR, size: 12, outline: { color: "white", width: 2 } } })];
    const radius = overlay.properties?.radius_m;
    if (radius > 0) graphics.unshift(new Graphic({ geometry: new Circle({ center, radius, radiusUnit: "meters", geodesic: true }), attributes: { overlayId: overlay.id },
      symbol: { type: "simple-fill", color: `${RADIUS_COLOR}14`, outline: { color: RADIUS_COLOR, width: 1.5, style: "dash" } } }));
    return graphics;
  });
}

function densityLayer(overlays) {
  const points = overlays.filter((overlay) => overlay.kind === "density").flatMap((overlay) => overlay.geometry.coordinates);
  if (!points.length) return null;
  return new FeatureLayer({
    title: "Competitor density", geometryType: "point", spatialReference: WGS84, objectIdField: "ObjectID",
    fields: [{ name: "ObjectID", type: "oid" }], popupEnabled: false,
    source: points.map(([longitude, latitude], index) => new Graphic({ geometry: { type: "point", longitude, latitude }, attributes: { ObjectID: index + 1 } })),
    renderer: { type: "heatmap", radius: 24, maxDensity: 0.01, minDensity: 0,
      colorStops: [{ ratio: 0, color: "rgba(220, 38, 38, 0)" }, { ratio: 0.2, color: "rgba(250, 204, 21, 0.45)" },
        { ratio: 0.6, color: "rgba(249, 115, 22, 0.7)" }, { ratio: 1, color: "rgba(220, 38, 38, 0.85)" }] },
  });
}

function graphicsExtent(graphics) {
  return graphics.map((graphic) => graphic.geometry).filter(Boolean)
    .map((geometry) => geometry.extent ?? new Extent({ xmin: geometry.x, ymin: geometry.y, xmax: geometry.x, ymax: geometry.y, spatialReference: geometry.spatialReference }))
    .reduce((all, next) => (all ? all.union(next) : next), null);
}

async function fitToContent(view, layers, motion = { animate: false }) {
  const extent = graphicsExtent([layers.markers.source, layers.areas.graphics, layers.radius.graphics].flatMap((graphics) => graphics.toArray()));
  if (!extent) return;
  await view.goTo(extent.width || extent.height ? extent.expand(1.3) : { target: extent.center, zoom: MAX_FIT_ZOOM }, motion).catch(() => {});
  if (view.zoom > MAX_FIT_ZOOM) view.zoom = MAX_FIT_ZOOM;
}

// Where the map goes for a tour scene; null means the whole answer.
function sceneTarget(layers, focus) {
  const shapes = (layer, id) => layer.graphics.toArray().filter((graphic) => graphic.geometry?.type === "polygon" && (!id || graphic.attributes?.overlayId === id));
  const around = (graphics, factor) => {
    const extent = graphicsExtent(graphics);
    return extent ? extent.expand(factor) : null;
  };
  switch (focus.type) {
    case "areas": return around(shapes(layers.areas), 1.3);
    case "area": return around(shapes(layers.areas, focus.id), 1.6);
    case "radius": {
      const circle = around(shapes(layers.radius, focus.id), 1.25);
      const centre = layers.radius.graphics.toArray().find((graphic) => graphic.geometry?.type === "point");
      return circle ?? (centre ? { target: centre.geometry, zoom: 15 } : null);
    }
    case "place": {
      const marker = layers.markers.source.find((graphic) => graphic.attributes.placeId === focus.id);
      return marker ? { target: marker.geometry, zoom: 16 } : null;
    }
    default: return null;
  }
}

function prefersStillMotion() {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

// A hit test that has not answered within HIT_TEST_MS counts as a miss, so a slow frame never freezes the hover.
async function hitAt(view, layer, event, key) {
  const late = new Promise((resolve) => setTimeout(() => resolve(null), HIT_TEST_MS));
  const hit = await Promise.race([view.hitTest(event, { include: [layer] }).catch(() => null), late]);
  return hit?.results.find((result) => result.graphic?.attributes?.[key])?.graphic ?? null;
}

function MapPreview({ mapData, darkMode = false, playRequest = 0, script = null }) {
  const container = useRef(null);
  const viewRef = useRef(null);
  const layersRef = useRef(null);
  const hideTimer = useRef(null);
  const [state, dispatch] = useReducer(applyMapCommand, mapData, initialMapState);
  const [failure, setFailure] = useState(null);
  const [hover, setHover] = useState(null);
  const [info, setInfo] = useState(null);
  const [credits, setCredits] = useState("");
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState(null);
  const places = useMemo(() => mapPlaces(mapData), [mapData]);
  const overlays = useMemo(() => mapOverlays(mapData), [mapData]);
  const groups = useMemo(() => overlayGroups(mapData), [mapData]);
  const scenes = useMemo(() => shortOpening(applyTourScript(cinematicScenes(mapData), script)), [mapData, script]);
  const handledPlay = useRef(playRequest);
  const [voiceOn, setVoiceOn] = useState(voicePreference);
  const voiceWorks = tourVoice.isSupported();
  const legend = useMemo(() => [...(places.length ? [{ id: "restaurants", color: MARKER_COLOR, label: "Restaurants" }] : []),
    ...legendEntries(mapData)], [places, mapData]);
  // A failure belongs to the result it happened on; the next result gets a fresh try.
  const error = failure?.places === places ? failure.message : null;
  const hovered = hover && places.find((place) => place.id === hover.id);
  const scene = state.tour ? scenes[state.tour.scene] : null;
  const tourPlace = scene?.focus.type === "place" ? scene.focus.id : null;
  // The tour opens each place's details tab; "back" hides it for that place only.
  const [hiddenTourPlace, setHiddenTourPlace] = useState(null);
  const tourPanel = Boolean(tourPlace) && hiddenTourPlace !== tourPlace;
  const title = overlays.some((overlay) => overlay.properties?.role) ? "Main competitors" : "Places on this map";

  useEffect(() => dispatch({ type: "load", mapData }), [mapData]);

  useEffect(() => {
    let view = null;
    let attribution = null;
    const keepCard = () => clearTimeout(hideTimer.current);
    const dropCard = () => {
      clearTimeout(hideTimer.current);
      hideTimer.current = setTimeout(() => setHover(null), CARD_HIDE_DELAY);
    };
    try {
      const layers = {
        areas: new GraphicsLayer({ title: "Area boundaries", graphics: areaGraphics(overlays) }),
        radius: new GraphicsLayer({ title: "Search radius", graphics: radiusGraphics(overlays) }),
        density: densityLayer(overlays),
        markers: markerLayer(places),
        you: new GraphicsLayer({ title: "Your location" }),
      };
      const map = new ArcGISMap({ layers: [layers.areas, layers.density, layers.radius, layers.markers, layers.you].filter(Boolean) });
      // Web Mercator is set up front because the basemap arrives in a later effect, and the view would otherwise
      // take its projection from the WGS84 overlays and leave the basemap tiles blank.
      view = new MapView({ container: container.current, map, center: NEUTRAL_CENTER, zoom: 13, spatialReference: { wkid: 3857 },
        constraints: { snapToZoom: false, minZoom: 10 }, popupEnabled: false, ui: { components: [] } });
      attribution = new AttributionViewModel({ view });
      reactiveUtils.watch(() => attribution.items.toArray().map((item) => item.text).filter(Boolean).join(", "),
        (text) => setCredits([...new Set(text.split(/\s*,\s*/).filter(Boolean))].join(", ")), { initial: true });

      // Hovering a dot shows its card; the card stays while the pointer moves onto it. Only the latest pointer
      // position is checked, once per frame, so a quick move never leaves an old card behind.
      let latest = null;
      let busy = false;
      const checkHover = async () => {
        while (latest) {
          const event = latest;
          latest = null;
          const graphic = await hitAt(view, layers.markers, event, "placeId");
          if (latest) continue;
          if (!graphic) {
            dropCard();
          } else {
            keepCard();
            const point = view.toScreen(graphic.geometry);
            setHover({ id: graphic.attributes.placeId, x: point.x, y: point.y });
          }
        }
        busy = false;
      };
      view.on("pointer-move", (event) => {
        latest = event;
        if (busy) return;
        busy = true;
        requestAnimationFrame(checkHover);
      });
      view.on(["drag", "mouse-wheel"], () => {
        dispatch({ type: "pause_tour" });
        setHover(null);
        setInfo(null);
      });
      view.on("pointer-leave", dropCard);
      view.on("click", async (event) => {
        const place = await hitAt(view, layers.markers, event, "placeId");
        if (place) {
          setHover(null);
          setInfo(null);
          return dispatch({ type: "select_place", id: place.attributes.placeId });
        }
        const shape = await hitAt(view, layers.radius, event, "overlayId") ?? await hitAt(view, layers.areas, event, "overlayId");
        const overlay = shape && overlays.find((item) => item.id === shape.attributes.overlayId);
        setInfo(overlay ? { title: overlay.label, facts: overlayFacts(overlay.properties), x: event.x, y: event.y } : null);
      });

      viewRef.current = view;
      layersRef.current = layers;
      view.when(() => fitToContent(view, layers), (reason) => {
        console.error("Map view failed to start", reason);
        setFailure({ places, message: "The map couldn't load. Check your internet connection and try again." });
      });
    } catch (reason) {
      console.error("Map overlays could not be drawn", reason);
      queueMicrotask(() => setFailure({ places, message: "The map couldn't draw this result." }));
    }
    return () => {
      clearTimeout(hideTimer.current);
      attribution?.destroy();
      view?.destroy();
      viewRef.current = null;
      layersRef.current = null;
    };
  }, [places, overlays]);

  useEffect(() => {
    if (viewRef.current) viewRef.current.map.basemap = createBasemap(basemapSpec(state.basemap, darkMode, API_KEY));
  }, [state.basemap, darkMode, places, overlays]);

  // A tour scene shows the shape it talks about even when its layer is off, and the markers appear only once
  // the tour reaches the places.
  useEffect(() => {
    const layers = layersRef.current;
    if (!layers) return;
    const shown = { radius: scene?.focus.type === "radius", areas: ["area", "areas"].includes(scene?.focus.type) };
    for (const group of ["areas", "radius", "density"]) {
      if (layers[group]) layers[group].visible = state.visible[group] !== false || Boolean(shown[group]);
    }
    layers.markers.visible = !scene || scene.places;
  }, [state.visible, scene, places, overlays]);

  useEffect(() => {
    if (playRequest === handledPlay.current) return;
    handledPlay.current = playRequest;
    setHiddenTourPlace(null);
    setHover(null);
    setInfo(null);
    dispatch({ type: "start_tour", scenes: scenes.length });
  }, [playRequest, scenes]);

  useEffect(() => {
    const view = viewRef.current;
    const layers = layersRef.current;
    if (!scene || !view || !layers) return undefined;
    const controller = new AbortController();
    const motion = prefersStillMotion() ? { animate: false } : { duration: TOUR_MOVE_MS, easing: "in-out-cubic", signal: controller.signal };
    const target = sceneTarget(layers, scene.focus);
    if (target) view.goTo(target, motion).catch(() => {});
    else fitToContent(view, layers, motion);
    return () => controller.abort();
  }, [scene, places, overlays]);

  // While playing, each scene is explained aloud and the tour moves on when the voice finishes, after the map
  // has had time to arrive. Muted, or without a browser voice, each scene shows for SCENE_MS.
  const playingScene = state.tour?.playing ? scene : null;
  useEffect(() => {
    if (!playingScene) return undefined;
    let timer = null;
    let cancelled = false;
    const startedAt = Date.now();
    const next = () => {
      if (cancelled) return;
      timer = setTimeout(() => dispatch({ type: "scene_done" }), Math.max(700, TOUR_MOVE_MS + 400 - (Date.now() - startedAt)));
    };
    if (!(voiceOn && voiceWorks && tourVoice.speak(playingScene.narration, next))) {
      timer = setTimeout(() => dispatch({ type: "scene_done" }), SCENE_MS);
    }
    return () => {
      cancelled = true;
      clearTimeout(timer);
      tourVoice.stop();
    };
  }, [playingScene, voiceOn, voiceWorks]);

  // The next line is fetched while the current one plays, so there is no gap between steps.
  const tourScene = state.tour?.scene;
  useEffect(() => {
    if (tourScene == null || !voiceOn) return;
    tourVoice.prepare(scenes[tourScene]?.narration);
    tourVoice.prepare(scenes[tourScene + 1]?.narration);
  }, [tourScene, voiceOn, scenes]);

  useEffect(() => () => tourVoice.stop(), []);

  const toggleVoice = () => {
    saveVoicePreference(!voiceOn);
    setVoiceOn(!voiceOn);
  };

  useEffect(() => {
    if (state.fitRequest && viewRef.current && layersRef.current) fitToContent(viewRef.current, layersRef.current);
  }, [state.fitRequest]);

  useEffect(() => {
    if (!state.expanded) return undefined;
    const close = (event) => {
      if (event.key === "Escape") dispatch(state.tour ? { type: "stop_tour" } : state.selected ? { type: "close_place" } : { type: "expand_map", expanded: false });
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [state.expanded, state.selected, state.tour]);

  useEffect(() => {
    const view = viewRef.current;
    const layers = layersRef.current;
    if (!view || !layers) return;
    const target = layers.markers.source.find((graphic) => graphic.attributes.placeId === state.selected);
    if (target) view.goTo({ target: target.geometry, zoom: Math.max(view.zoom, 15) }).catch(() => {});
  }, [state.selected, places, overlays]);

  useEffect(() => {
    if (layersRef.current) layersRef.current.markers.renderer = markerRenderer(tourPlace ?? state.selected);
  }, [tourPlace, state.selected, places, overlays]);

  const zoom = (step) => viewRef.current?.goTo({ zoom: viewRef.current.zoom + step }).catch(() => {});
  // A quick fix first, since most laptops have no GPS and a precise-only request times out; a precise fix
  // replaces it when available. The faint circle shows the fix's accuracy.
  const locate = () => {
    if (locating) return;
    if (!navigator.geolocation) return setLocateError("Your browser can't share your location.");
    setLocating(true);
    setLocateError(null);
    const show = ({ coords }) => {
      const layers = layersRef.current;
      const view = viewRef.current;
      if (!layers || !view) return;
      const center = new Point({ longitude: coords.longitude, latitude: coords.latitude });
      layers.you.removeAll();
      if (coords.accuracy > 20) layers.you.add(new Graphic({ geometry: new Circle({ center, radius: coords.accuracy, radiusUnit: "meters", geodesic: true }),
        symbol: { type: "simple-fill", color: `${RADIUS_COLOR}1f`, outline: { color: `${RADIUS_COLOR}66`, width: 1 } } }));
      layers.you.add(new Graphic({ geometry: center, symbol: { type: "simple-marker", color: RADIUS_COLOR, size: 14, outline: { color: "white", width: 3 } } }));
      view.goTo({ center, zoom: Math.max(view.zoom, coords.accuracy > 500 ? 14 : 16) }).catch(() => {});
    };
    navigator.geolocation.getCurrentPosition((position) => {
      setLocating(false);
      show(position);
      if (position.coords.accuracy > 50) {
        navigator.geolocation.getCurrentPosition(show, () => {}, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
      }
    }, (reason) => {
      setLocating(false);
      setLocateError(reason?.code === 1
        ? "Location is blocked. Allow it from the icon at the left of the address bar, then try again."
        : "I couldn't find your location. Check that location is turned on, then try again.");
    }, { enableHighAccuracy: false, timeout: 30000, maximumAge: 60000 });
  };

  return <div className={`interactive-map${state.expanded ? " is-expanded" : ""}`}>
    <div className="map-stage">
      {error ? <div className="restaurant-map map-error" role="alert">{error}</div>
        : <div ref={container} className="restaurant-map" />}
      {!error && <MapControls state={state} groups={groups} legend={legend} locating={locating} onZoom={zoom} onLocate={locate} dispatch={dispatch} />}
      {hovered && <PlaceCard place={hovered} position={hover}
        onEnter={() => clearTimeout(hideTimer.current)} onLeave={() => setHover(null)}
        onOpen={() => { setHover(null); dispatch({ type: "select_place", id: hovered.id }); }} />}
      {info && <InfoCard info={info} onClose={() => setInfo(null)} />}
      {locateError && <p className="map-toast" role="status">{locateError}
        <button type="button" className="map-close" onClick={() => setLocateError(null)} aria-label="Dismiss"><X aria-hidden="true" /></button></p>}
      {!error && <MapCredits credits={credits} />}
      {!error && scene && <CinematicBar scene={scene} index={state.tour.scene} total={state.tour.scenes} playing={state.tour.playing}
        voice={voiceWorks ? voiceOn : null} onVoice={toggleVoice}
        onToggle={() => dispatch({ type: state.tour.playing ? "pause_tour" : "resume_tour" })}
        onReplay={() => dispatch({ type: "start_tour", scenes: scenes.length })}
        onStep={(step) => dispatch({ type: "tour_step", step })} onClose={() => dispatch({ type: "stop_tour" })} />}
    </div>
    {state.expanded && (!state.tour || tourPanel) && places.length > 0 && <PlacePanel places={places}
      selected={state.tour ? tourPlace : state.selected} title={title}
      onSelect={(id) => dispatch({ type: "select_place", id })}
      onBack={() => (state.tour ? setHiddenTourPlace(tourPlace) : dispatch({ type: "close_place" }))}
      onClose={() => dispatch({ type: "expand_map", expanded: false })} />}
    {mapData?.message && <p className="map-note">{mapData.message}</p>}
  </div>;
}

export default MapPreview;
