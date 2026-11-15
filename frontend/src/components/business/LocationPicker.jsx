import { useEffect, useRef, useState } from "react";
import { LoaderCircle, LocateFixed, Map as MapIcon, Minus, Plus, Satellite, Search, X } from "lucide-react";
import esriConfig from "@arcgis/core/config.js";
import ArcGISMap from "@arcgis/core/Map.js";
import Basemap from "@arcgis/core/Basemap.js";
import Graphic from "@arcgis/core/Graphic.js";
import Circle from "@arcgis/core/geometry/Circle.js";
import Point from "@arcgis/core/geometry/Point.js";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer.js";
import TileLayer from "@arcgis/core/layers/TileLayer.js";
import MapView from "@arcgis/core/views/MapView.js";
import * as reactiveUtils from "@arcgis/core/core/reactiveUtils.js";
import AttributionViewModel from "@arcgis/core/widgets/Attribution/AttributionViewModel.js";
import { basemapSpec } from "../../services/mapBasemaps";
import { DEFAULT_LOCATION } from "../../services/businessForm";
import { RADIUS_COLOR } from "../../services/mapOverlays";
import { MIN_SEARCH_LENGTH, locatePlace, suggestPlaces } from "../../services/placeSearch";
import { MapCredits } from "../map/MapControls";
import "@arcgis/core/assets/esri/themes/light/main.css";
import "../../styles/map.css";

const API_KEY = import.meta.env.VITE_ARCGIS_API_KEY || "";
if (API_KEY) esriConfig.apiKey = API_KEY;

const PIN_ZOOM = 18;
const SEARCH_DELAY = 250;

function createBasemap(satellite, darkMode) {
  const spec = basemapSpec(satellite ? "satellite" : "default", darkMode, API_KEY);
  if (spec.style) return new Basemap({ style: { id: spec.style } });
  return new Basemap({
    baseLayers: spec.tiles.map((url) => new TileLayer({ url })),
    referenceLayers: spec.references.map((url) => new TileLayer({ url })),
  });
}

const round = (value) => Math.round(value * 1e6) / 1e6;

function ControlButton({ label, pressed, busy, onClick, children }) {
  return (
    <button type="button" className="map-control" title={label} aria-label={label} aria-pressed={pressed} aria-busy={busy || undefined} onClick={onClick}>
      {children}
    </button>
  );
}

function PlaceSearch({ id, onFound }) {
  const [text, setText] = useState("");
  const [results, setResults] = useState([]);
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const rootRef = useRef(null);
  const timer = useRef(null);
  const request = useRef(null);
  const listId = `${id}-results`;

  useEffect(() => () => {
    clearTimeout(timer.current);
    request.current?.abort();
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const search = (query) => {
    clearTimeout(timer.current);
    request.current?.abort();
    setMessage(null);
    if (query.trim().length < MIN_SEARCH_LENGTH) {
      setResults([]);
      setBusy(false);
      return;
    }
    setBusy(true);
    timer.current = setTimeout(async () => {
      const controller = new AbortController();
      request.current = controller;
      try {
        const found = await suggestPlaces(query, { signal: controller.signal, apiKey: API_KEY });
        setResults(found);
        setActive(found.length ? 0 : -1);
        setOpen(true);
        if (!found.length) setMessage("No places in Petaling Jaya match that.");
      } catch (searchError) {
        if (controller.signal.aborted) return;
        console.error("Place search failed", searchError);
        setResults([]);
        setMessage("Search isn't working right now. Move the map instead.");
        setOpen(true);
      } finally {
        if (request.current === controller) setBusy(false);
      }
    }, SEARCH_DELAY);
  };

  const pick = async (result) => {
    setOpen(false);
    setText(result.text);
    setBusy(true);
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const place = await locatePlace(result, { signal: controller.signal, apiKey: API_KEY });
      if (place) onFound(place);
      else {
        setMessage("That place couldn't be found on the map.");
        setOpen(true);
      }
    } catch (searchError) {
      if (controller.signal.aborted) return;
      console.error("Place lookup failed", searchError);
      setMessage("Search isn't working right now. Move the map instead.");
      setOpen(true);
    } finally {
      if (request.current === controller) setBusy(false);
    }
  };

  const onKeyDown = (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!results.length) return;
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((previous) => (previous + step + results.length) % results.length);
    } else if (event.key === "Enter") {
      // Stop Enter from submitting the surrounding form.
      event.preventDefault();
      if (results[active]) pick(results[active]);
      else if (text.trim().length >= MIN_SEARCH_LENGTH) pick({ text });
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  const showList = open && (results.length > 0 || message);

  return (
    <div className="business-map-search" ref={rootRef}>
      <Search className="business-map-search-icon" aria-hidden="true" />
      <input
        id={id}
        type="search"
        role="combobox"
        className="business-map-search-input"
        placeholder="Search an address or place in PJ"
        autoComplete="off"
        value={text}
        aria-label="Search an address or place in Petaling Jaya"
        aria-expanded={Boolean(showList)}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
        onChange={(event) => {
          setText(event.target.value);
          search(event.target.value);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {busy && <LoaderCircle className="business-map-search-busy" aria-label="Searching" />}
      {!busy && text && (
        <button
          type="button"
          className="business-map-search-clear"
          aria-label="Clear search"
          onClick={() => {
            setText("");
            search("");
            setOpen(false);
          }}
        >
          <X aria-hidden="true" />
        </button>
      )}
      {showList && (
        <ul id={listId} className="business-options business-map-results" role="listbox" aria-label="Places found">
          {results.map((result, index) => (
            <li
              key={result.magicKey ?? result.text}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className={`business-option${index === active ? " is-active" : ""}`}
              onMouseEnter={() => setActive(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(result)}
            >
              <span>{result.text}</span>
            </li>
          ))}
          {message && <li className="business-map-results-note" role="presentation">{message}</li>}
        </ul>
      )}
    </div>
  );
}

function LocationPicker({ id, value, onChange, darkMode = false, error }) {
  const container = useRef(null);
  const viewRef = useRef(null);
  const youRef = useRef(null);
  const onChangeRef = useRef(onChange);
  const [start] = useState(value);
  // Once the owner moves the map, a late location fix must not pull it away.
  const movedByOwner = useRef(false);
  const locateRef = useRef(null);
  const [moving, setMoving] = useState(false);
  const [satellite, setSatellite] = useState(false);
  const [credits, setCredits] = useState("");
  const [failed, setFailed] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState(null);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    const you = new GraphicsLayer({ title: "Your location" });
    const view = new MapView({
      container: container.current,
      map: new ArcGISMap({ basemap: createBasemap(false, darkMode), layers: [you] }),
      center: [start.longitude, start.latitude],
      zoom: PIN_ZOOM - 1,
      spatialReference: { wkid: 3857 },
      constraints: { snapToZoom: false, minZoom: 11, rotationEnabled: false },
      popupEnabled: false,
      ui: { components: [] },
    });
    viewRef.current = view;
    youRef.current = you;
    const attribution = new AttributionViewModel({ view });

    const handles = [
      // Let the wheel scroll the form instead of zooming the map.
      view.on("mouse-wheel", (event) => event.stopPropagation()),
      view.on("click", (event) => view.goTo({ target: event.mapPoint }).catch(() => {})),
      reactiveUtils.watch(() => view.stationary, (stationary) => {
        setMoving(!stationary);
        if (stationary && view.center) {
          onChangeRef.current({ latitude: round(view.center.latitude), longitude: round(view.center.longitude) });
        }
      }),
      reactiveUtils.watch(
        () => attribution.items.toArray().map((item) => item.text).filter(Boolean).join(", "),
        (text) => setCredits([...new Set(text.split(/\s*,\s*/).filter(Boolean))].join(", ")),
        { initial: true },
      ),
    ];
    handles.push(view.on(["drag", "click", "double-click", "key-down"], () => {
      movedByOwner.current = true;
    }));
    // No pin placed yet: start at the device's location.
    const firstVisit = start.latitude === DEFAULT_LOCATION.latitude && start.longitude === DEFAULT_LOCATION.longitude;
    view.when(() => {
      if (firstVisit) locateRef.current?.({ automatic: true });
    }, (loadError) => {
      console.error("Failed to load the location map", loadError);
      setFailed(true);
    });

    return () => {
      handles.forEach((handle) => handle.remove());
      attribution.destroy();
      viewRef.current = null;
      youRef.current = null;
      view.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- built once; theme and basemap update in the effect below
  }, [start]);

  useEffect(() => {
    if (viewRef.current) viewRef.current.map.basemap = createBasemap(satellite, darkMode);
  }, [satellite, darkMode]);

  const moveTo = (latitude, longitude, zoom = PIN_ZOOM) => {
    const view = viewRef.current;
    view?.goTo({ center: new Point({ longitude, latitude }), zoom: Math.max(view.zoom, zoom) }).catch(() => {});
  };

  const zoom = (step) => viewRef.current?.goTo({ zoom: viewRef.current.zoom + step }).catch(() => {});

  // Quick fix first, then a precise one, as the chatbot map does. When the automatic first try fails, the message
  // says where the map starts instead of reporting an error.
  const locate = ({ automatic = false } = {}) => {
    if (locating) return;
    if (!navigator.geolocation) {
      setLocateError(automatic
        ? "Your browser can't share your location, so the map starts in Petaling Jaya. Search for your shop or move the map."
        : "Your browser can't share your location.");
      return;
    }
    setLocating(true);
    setLocateError(null);
    movedByOwner.current = false;
    const show = ({ coords }) => {
      const you = youRef.current;
      if (!you) return;
      const center = new Point({ longitude: coords.longitude, latitude: coords.latitude });
      you.removeAll();
      if (coords.accuracy > 20) {
        you.add(new Graphic({
          geometry: new Circle({ center, radius: coords.accuracy, radiusUnit: "meters", geodesic: true }),
          symbol: { type: "simple-fill", color: `${RADIUS_COLOR}1f`, outline: { color: `${RADIUS_COLOR}66`, width: 1 } },
        }));
      }
      you.add(new Graphic({ geometry: center, symbol: { type: "simple-marker", color: RADIUS_COLOR, size: 14, outline: { color: "white", width: 3 } } }));
      if (!movedByOwner.current) moveTo(coords.latitude, coords.longitude, coords.accuracy > 500 ? 15 : PIN_ZOOM);
    };
    navigator.geolocation.getCurrentPosition((position) => {
      setLocating(false);
      show(position);
      if (position.coords.accuracy > 50) {
        navigator.geolocation.getCurrentPosition(show, () => {}, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
      }
    }, (reason) => {
      setLocating(false);
      const blocked = reason?.code === 1;
      if (automatic) {
        setLocateError(blocked
          ? "Location isn't allowed, so the map starts in Petaling Jaya. To start at your shop, allow location from the icon at the left of the address bar, or search for it."
          : "Your location couldn't be found, so the map starts in Petaling Jaya. Search for your shop or move the map.");
      } else {
        setLocateError(blocked
          ? "Location is blocked. Allow it from the icon at the left of the address bar, then try again."
          : "I couldn't find your location. Check that location is turned on, then try again.");
      }
    }, { enableHighAccuracy: false, timeout: 30000, maximumAge: 60000 });
  };

  useEffect(() => {
    locateRef.current = locate;
  });

  const { latitude, longitude } = value ?? start;

  return (
    <div className={`business-map${error ? " has-error" : ""}`}>
      <div
        ref={container}
        id={id}
        className="business-map-view"
        role="application"
        aria-label="Business location map. Move the map, or use the arrow keys, until the pin is on your entrance."
        aria-describedby={error ? `${id}-error` : undefined}
      />
      {failed ? (
        <p className="business-map-failed">The map couldn't load. Check your connection and refresh.</p>
      ) : (
        <>
          <span className={`business-map-pin${moving ? " is-moving" : ""}`} aria-hidden="true">
            <svg viewBox="0 0 28 36" width="34" height="44">
              <path d="M14 35s12-11.3 12-21A12 12 0 0 0 2 14c0 9.7 12 21 12 21Z" fill="#ff6129" stroke="#ffffff" strokeWidth="2" />
              <circle cx="14" cy="14" r="5" fill="#ffffff" />
            </svg>
          </span>
          <span className="business-map-pin-shadow" aria-hidden="true" />

          <PlaceSearch
            id={`${id}-search`}
            onFound={(place) => {
              movedByOwner.current = true;
              moveTo(place.latitude, place.longitude);
            }}
          />

          <div className="map-controls is-left business-map-controls">
            <div className="map-control-group">
              <ControlButton label="Zoom in" onClick={() => zoom(1)}><Plus aria-hidden="true" /></ControlButton>
              <ControlButton label="Zoom out" onClick={() => zoom(-1)}><Minus aria-hidden="true" /></ControlButton>
            </div>
            <ControlButton label="Show my location" busy={locating} onClick={() => locate()}><LocateFixed aria-hidden="true" /></ControlButton>
          </div>
          <div className="map-controls is-right business-map-controls">
            <ControlButton label={satellite ? "Show map" : "Show satellite"} pressed={satellite} onClick={() => setSatellite((previous) => !previous)}>
              {satellite ? <MapIcon aria-hidden="true" /> : <Satellite aria-hidden="true" />}
            </ControlButton>
          </div>

          <p className="business-map-hint">{moving ? "Release to place the pin" : "Move the map to put the pin on your entrance"}</p>
          <span className="business-map-coords" aria-live="polite">
            {latitude.toFixed(4)}, {longitude.toFixed(4)}
          </span>
          {locateError && (
            <p className="map-toast business-map-toast" role="status">
              {locateError}
              <button type="button" className="map-close" onClick={() => setLocateError(null)} aria-label="Dismiss"><X aria-hidden="true" /></button>
            </p>
          )}
          <MapCredits credits={credits} />
        </>
      )}
    </div>
  );
}

export default LocationPicker;
