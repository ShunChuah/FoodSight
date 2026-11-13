import { useState } from "react";
import { Accessibility, BadgeCheck, Banknote, CalendarCheck, Car, ChevronDown, ChevronLeft, Clock, Globe, Leaf, MapPin, Navigation, Phone, Route,
  ShoppingBag, Star, Users, UtensilsCrossed, Wallet, X } from "lucide-react";
import { directionsUrl, distanceLabel, openStatus, phoneUrl, placeHighlights, placeKind, priceLabel, websiteUrl, weekLines } from "../../services/mapPlaces";
import { cuisineText } from "../../services/mapPresentation";

const HIGHLIGHT_ICONS = { halal: BadgeCheck, services: ShoppingBag, reservations: CalendarCheck, parking: Car, groups: Users,
  vegetarian: Leaf, accessible: Accessibility, cash: Banknote };

// The graph has no photos, so each place gets the same food tile.
function PlaceTile({ large = false }) {
  return <span className={`map-place-tile${large ? " is-large" : ""}`} aria-hidden="true"><UtensilsCrossed /></span>;
}

function Rating({ place }) {
  if (place.average_rating == null) return null;
  return <span className="map-place-rating"><Star aria-hidden="true" />{place.average_rating}
    {place.review_count ? <span className="map-place-muted"> ({place.review_count.toLocaleString()})</span> : null}</span>;
}

// Rating and kind of place only; the price and the rest wait for the details.
function Summary({ place }) {
  const kind = placeKind(place);
  if (place.average_rating == null && !kind) return null;
  return <span className="map-place-line"><Rating place={place} />{kind && <span>{kind}</span>}</span>;
}

function Fact({ icon: Icon, children }) {
  return <li><Icon aria-hidden="true" /><span>{children}</span></li>;
}

function Status({ place }) {
  const status = openStatus(place);
  return status ? <span className={status.open ? "map-place-open" : "map-place-closed"}>{status.text}</span> : null;
}

function Actions({ place }) {
  const website = websiteUrl(place);
  const phone = phoneUrl(place.phone);
  return <div className="map-place-actions">
    <a className="map-place-action is-primary" href={directionsUrl(place)} target="_blank" rel="noopener noreferrer"><Navigation aria-hidden="true" />Directions</a>
    {website && <a className="map-place-action" href={website} target="_blank" rel="noopener noreferrer"><Globe aria-hidden="true" />Website</a>}
    {phone && <a className="map-place-action" href={phone}><Phone aria-hidden="true" />Call</a>}
  </div>;
}

// Shown while the pointer is on a marker: only what decides whether to look closer.
export function PlaceCard({ place, position, onEnter, onLeave, onOpen }) {
  const below = position.y < 170;
  return <div className={`map-place-card${below ? " is-below" : ""}`} style={{ left: position.x, top: position.y }}
    onMouseEnter={onEnter} onMouseLeave={onLeave} role="dialog" aria-label={place.label}>
    <button type="button" className="map-place-card-main" onClick={onOpen}>
      <PlaceTile />
      <span className="map-place-text">
        <strong>{place.label}</strong>
        <Summary place={place} />
        <Status place={place} />
      </span>
    </button>
    <Actions place={place} />
  </div>;
}

function PlaceList({ places, title, onSelect }) {
  return <>
    <header className="map-panel-header">
      <div><h3>{title}</h3><p className="map-place-muted">{places.length} {places.length === 1 ? "place" : "places"}</p></div>
    </header>
    <ol className="map-place-list">
      {places.map((place) => (
        <li key={place.id}>
          <button type="button" onClick={() => onSelect(place.id)}>
            <PlaceTile />
            <span className="map-place-text">
              <strong>{place.label}</strong>
              <Summary place={place} />
              <Status place={place} />
            </span>
          </button>
        </li>
      ))}
    </ol>
  </>;
}

function PlaceDetails({ place, onBack }) {
  const [showWeek, setShowWeek] = useState(false);
  const week = weekLines(place);
  const status = openStatus(place);
  const website = websiteUrl(place);
  return <article className="map-place-details">
    <div className="map-panel-nav">
      <button type="button" className="map-close" onClick={onBack} aria-label="Back to the list"><ChevronLeft aria-hidden="true" /></button>
    </div>
    <div className="map-place-hero"><PlaceTile large /></div>
    <h3>{place.label}</h3>
    <Summary place={place} />
    <Actions place={place} />
    <div className="map-place-scroll">
      <ul className="map-place-facts">
        {status && <li>
          <Clock aria-hidden="true" />
          <div>
            <button type="button" className="map-place-hours" onClick={() => setShowWeek(!showWeek)} aria-expanded={showWeek} disabled={!week.length}>
              <span className={status.open ? "map-place-open" : "map-place-closed"}>{status.text}</span>
              {week.length > 0 && <ChevronDown aria-hidden="true" />}
            </button>
            {showWeek && <table className="map-place-week"><tbody>{week.map(([day, text]) => <tr key={day}><th scope="row">{day}</th><td>{text}</td></tr>)}</tbody></table>}
          </div>
        </li>}
        {priceLabel(place) && <Fact icon={Wallet}>{priceLabel(place)}</Fact>}
        {cuisineText(place.cuisines) && cuisineText(place.cuisines) !== placeKind(place) && <Fact icon={UtensilsCrossed}>{cuisineText(place.cuisines)}</Fact>}
        {place.address && <Fact icon={MapPin}>{place.address}</Fact>}
        {distanceLabel(place.distance_m) && <Fact icon={Route}>{distanceLabel(place.distance_m)}</Fact>}
        {place.phone && <Fact icon={Phone}>{place.phone}</Fact>}
        {website && <Fact icon={Globe}><a href={website} target="_blank" rel="noopener noreferrer">{new URL(website).hostname.replace(/^www\./, "")}</a></Fact>}
        {placeHighlights(place).map(([key, text]) => <Fact key={key} icon={HIGHLIGHT_ICONS[key]}>{text}</Fact>)}
      </ul>
      {place.summary && <p className="map-place-summary">{place.summary}</p>}
    </div>
  </article>;
}

export function PlacePanel({ places, selected, title, onSelect, onBack, onClose }) {
  const place = places.find((item) => item.id === selected);
  return <aside className="map-panel" aria-label="Places on the map">
    <button type="button" className="map-close map-panel-close" onClick={onClose} aria-label="Close the expanded map"><X aria-hidden="true" /></button>
    {place ? <PlaceDetails key={place.id} place={place} onBack={onBack} /> : <PlaceList places={places} title={title} onSelect={onSelect} />}
  </aside>;
}
