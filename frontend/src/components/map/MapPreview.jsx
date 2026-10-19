import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Marker, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import { divIcon, latLngBounds } from "leaflet";
import { featurePosition, pointFeatures, safeWebsite } from "../../services/mapGeometry";
import { cuisineText, priceText } from "../../services/mapPresentation";
import "leaflet/dist/leaflet.css";
import "../../styles/map.css";

const tileUrl = import.meta.env.VITE_MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const attribution = import.meta.env.VITE_MAP_TILE_ATTRIBUTION || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const NEUTRAL_CENTER = [3.1073, 101.6067];

// Show every restaurant marker, and keep the map sized to its panel.
function FitToRestaurants({ positions }) {
  const map = useMap();
  useEffect(() => {
    if (positions.length) map.fitBounds(latLngBounds(positions), { padding: [32, 32], maxZoom: 16 });
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map, positions]);
  return null;
}

function RestaurantDetails({ data }) {
  const price = priceText(data);
  const website = safeWebsite(data.website);
  return <div className="business-map-popup">
    <strong>{data.label}</strong>
    {cuisineText(data.cuisines) && <p>{cuisineText(data.cuisines)}</p>}
    {data.average_rating != null && <p>Rating: {data.average_rating}</p>}
    {price && <p>Price: {price}</p>}
    {data.address && <p>{data.address}</p>}
    {website && <p><a href={website} target="_blank" rel="noopener noreferrer">Restaurant website</a></p>}
  </div>;
}

function MapPreview({ mapData }) {
  const features = useMemo(() => pointFeatures(mapData), [mapData]);
  const positions = useMemo(() => features.map(featurePosition), [features]);

  return <div className="interactive-map">
    <MapContainer className="restaurant-map" center={positions[0] ?? NEUTRAL_CENTER} zoom={14} scrollWheelZoom>
      <TileLayer url={tileUrl} attribution={attribution} maxZoom={19} />
      <FitToRestaurants positions={positions} />
      {features.map((feature, index) => {
        const data = feature.properties ?? {};
        // Answers saved before markers stopped being numbered keep their 1, 2, 3… labels; names stay React text.
        const rank = typeof data.marker_label === "string" && /^[0-9]{1,3}$/.test(data.marker_label) ? data.marker_label : null;
        const details = <><Tooltip>{data.label}</Tooltip><Popup><RestaurantDetails data={data} /></Popup></>;
        return rank
          ? <Marker key={`${feature.id}-${index}`} position={positions[index]} title={data.label} alt={data.label}
            icon={divIcon({ className: "ranked-map-marker", html: `<span>${rank}</span>`, iconSize: [30, 30], iconAnchor: [15, 15] })}>{details}</Marker>
          : <CircleMarker key={`${feature.id}-${index}`} center={positions[index]} radius={8}
            pathOptions={{ color: "#ffffff", fillColor: "#ff6129", fillOpacity: 1, weight: 2 }}>{details}</CircleMarker>;
      })}
    </MapContainer>
  </div>;
}

export default MapPreview;
