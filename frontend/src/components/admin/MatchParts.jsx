import { Check, X } from "lucide-react";
import { GOOGLE_COLOR, OSM_COLOR, WEEKDAYS, capitalise } from "../../services/adminFormat.js";
import { Badge, Card, ExternalLinkText } from "./AdminUi.jsx";

// Parts shared by the two Google match pages: one restaurant (GoogleMatchesTab) and a shared
// Google place with all its restaurants (SharedPlaceDetail).

// A restaurant's letter in a shared Google place (A, B, ...): on its button (white circle on
// orange), in its table heading and inside its pin (green, the OpenStreetMap colour)
export function LetterChip({ letter, onOrange = false }) {
  return (
    <span
      className={`inline-flex size-[1.125rem] shrink-0 items-center justify-center rounded-full text-[0.6875rem] font-bold leading-none ${
        onOrange ? "bg-white text-brand" : "text-white"
      }`}
      style={onOrange ? undefined : { backgroundColor: OSM_COLOR }}
    >
      {letter}
    </span>
  );
}

export function DecisionBadge({ decision }) {
  if (!decision) return null;
  if (decision.kind === "same") {
    return <Badge tone="green"><Check className="size-[0.75rem]" /> Same place{decision.pin === "google" ? " · Google pin" : ""}</Badge>;
  }
  if (decision.kind === "not_same") return <Badge tone="gray"><X className="size-[0.75rem]" /> Not the same</Badge>;
  return <Badge tone="blue">Another Google place (by hand)</Badge>;
}

// Latitude, longitude to 6 decimals (about 10 cm)
function pinText(latitude, longitude) {
  if (latitude == null || longitude == null || latitude === "" || longitude === "") return null;
  return `${Number(latitude).toFixed(6)}, ${Number(longitude).toFixed(6)}`;
}

function osmHours(osm) {
  const days = WEEKDAYS.filter((day) => osm[day]);
  if (!days.length) return osm.hours_raw ? [osm.hours_raw] : [];
  return days.map((day) => `${capitalise(day).slice(0, 3)}: ${osm[day]}`);
}

function Lines({ lines }) {
  if (!lines?.length) return <span className="text-gray-400">—</span>;
  return lines.map((line) => <span key={line} className="block">{line}</span>);
}

function Value({ children }) {
  return children ? <span className="break-words">{children}</span> : <span className="text-gray-400">—</span>;
}

function Link({ href }) {
  if (!href) return <span className="text-gray-400">—</span>;
  return <a href={href} target="_blank" rel="noreferrer" className="break-all text-brand hover:underline">{href}</a>;
}

// Each row: its label, the OpenStreetMap cell (from one OSM row), the Google cell (from Place Details)
const ROWS = [
  ["Name", (o) => <Value>{o.name}</Value>, (g) => <Value>{g.displayName?.text}</Value>],
  ["Address", (o) => <Value>{o.full_address}</Value>, (g) => <Value>{g.formattedAddress}</Value>],
  ["Pin", (o) => <Value>{pinText(o.latitude, o.longitude)}</Value>, (g) => <Value>{pinText(g.location?.latitude, g.location?.longitude)}</Value>],
  ["Phone", (o) => <Value>{o.phone}</Value>, (g) => <Value>{g.nationalPhoneNumber || g.internationalPhoneNumber}</Value>],
  ["Website", (o) => <Link href={o.website} />, (g) => <Link href={g.websiteUri} />],
  ["Type", (o) => <Value>{[o.amenity_type && capitalise(o.amenity_type), o.cuisine_raw, o.brand && `brand: ${o.brand}`].filter(Boolean).join(" · ")}</Value>,
    (g) => <Value>{[g.googleMapsTypeLabel?.text, g.primaryType].filter(Boolean).join(" · ")}</Value>],
  ["Opening hours", (o) => <Lines lines={osmHours(o)} />, (g) => <Lines lines={g.regularOpeningHours?.weekdayDescriptions} />],
  ["Status", () => <Value />, (g) => <Value>{g.businessStatus && capitalise(g.businessStatus.toLowerCase())}</Value>],
  ["Rating", () => <Value />, (g) => <Value>{g.rating && `${g.rating} ★ (${g.userRatingCount} reviews)`}</Value>],
];

// OpenStreetMap and Google side by side. osmSides: [{ key, title, subtitle?, letter?, osm }], one column each
// (one for a single restaurant, two or more for a shared Google place); google: the
// review item's google object (place ID, map link and Place Details).
export function Comparison({ osmSides, google }) {
  const details = google?.details || {};
  return (
    <Card className="p-0">
      <table className="w-full table-fixed text-left text-[0.8125rem]">
        <thead>
          <tr className="border-b border-gray-200 dark:border-line-dark">
            <th className="w-[9rem] px-4 py-3" />
            {osmSides.map((side) => (
              <th key={side.key} className="px-4 py-3">
                {side.letter
                  ? <span className="inline-flex items-center gap-1.5 font-bold" style={{ color: OSM_COLOR }}><LetterChip letter={side.letter} /> {side.title}</span>
                  : <span className="font-bold" style={{ color: OSM_COLOR }}>● {side.title}</span>}
                {side.subtitle && <span className="block text-[0.75rem] font-normal text-gray-500 dark:text-muted-dark">{side.subtitle}</span>}
              </th>
            ))}
            <th className="px-4 py-3"><span className="font-bold" style={{ color: GOOGLE_COLOR }}>● Google</span></th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([label, osmCell, googleCell]) => (
            <tr key={label} className="border-b border-gray-100 align-top last:border-b-0 dark:border-line-dark">
              <th className="px-4 py-2.5 font-semibold text-gray-500 dark:text-muted-dark">{label}</th>
              {osmSides.map((side) => <td key={side.key} className="px-4 py-2.5">{osmCell(side.osm || {})}</td>)}
              <td className="px-4 py-2.5">{googleCell(details)}</td>
            </tr>
          ))}
          <tr>
            <th className="px-4 py-2.5 font-semibold text-gray-500 dark:text-muted-dark">Open in</th>
            {osmSides.map((side) => (
              <td key={side.key} className="px-4 py-2.5"><ExternalLinkText href={side.osm?.map}>OpenStreetMap</ExternalLinkText></td>
            ))}
            <td className="px-4 py-2.5"><ExternalLinkText href={google?.map}>Google Maps</ExternalLinkText></td>
          </tr>
        </tbody>
      </table>
    </Card>
  );
}

const PIN_OPTIONS = [["osm", "OpenStreetMap pin", OSM_COLOR], ["google", "Google pin", GOOGLE_COLOR]];

// A two-option toggle: the chosen pin is the raised one; the dots match the map's pins
export function PinChoice({ pin, onPin, hint = "(used with Same place)" }) {
  return (
    <div className="flex items-center gap-3 text-[0.8125rem]">
      <span className="whitespace-nowrap">
        <span className="font-semibold">Pin to save</span>{" "}
        <span className="text-[0.75rem] text-gray-500 dark:text-muted-dark">{hint}</span>
      </span>
      <div role="radiogroup" aria-label="Pin to save"
        className="inline-flex rounded-[0.625rem] border border-gray-200 bg-zinc-100 p-[0.1875rem] dark:border-line-dark dark:bg-[#1e1e1e]">
        {PIN_OPTIONS.map(([value, label, color]) => {
          const active = pin === value;
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onPin(value)}
              className={`inline-flex h-[1.875rem] cursor-pointer items-center gap-2 whitespace-nowrap rounded-[0.5rem] px-3 font-medium transition-colors ${
                active
                  ? "bg-white text-ink shadow-sm dark:bg-[#2e2e2e] dark:text-white"
                  : "text-gray-500 hover:text-ink dark:text-muted-dark dark:hover:text-white"
              }`}
            >
              <span className="size-[0.5625rem] shrink-0 rounded-full" style={{ backgroundColor: color }} />
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
