import { mapOverlays } from "./mapOverlays.js";
import { distanceLabel, mapPlaces, placeKind, priceLabel } from "./mapPlaces.js";

// Cinematic AI: a guided map tour built only from the answer's map data, so it costs no model calls.
// Each scene says where the map goes (focus), what it shows (title and caption), what the voice explains
// (narration) and whether the markers show yet.
export const MAX_TOUR_PLACES = 5;
export const SCENE_MS = 4200;

function radiusText(metres) {
  return metres >= 1000 ? `${Number((metres / 1000).toFixed(1))} km` : `${Math.round(metres)} m`;
}

function count(number, word) {
  return `${number} ${word}${number === 1 ? "" : "s"}`;
}

function placeCaption(place) {
  const parts = [];
  if (typeof place.average_rating === "number") {
    parts.push(typeof place.review_count === "number" && place.review_count > 0
      ? `Rated ${place.average_rating} from ${place.review_count.toLocaleString()} reviews`
      : `Rated ${place.average_rating}`);
  }
  const price = priceLabel(place);
  if (price) parts.push(price);
  const distance = distanceLabel(place.distance_m);
  if (distance) parts.push(distance);
  const text = parts.join(", ");
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}.` : "One of the places that matched your question.";
}

function areaCaption(area) {
  const { role, score, restaurants, competitors } = area.properties ?? {};
  const parts = [];
  if (role) parts.push(role);
  if (typeof score === "number") parts.push(`opportunity score ${score}/100`);
  if (typeof restaurants === "number") parts.push(count(restaurants, "restaurant"));
  if (typeof competitors === "number") parts.push(count(competitors, "direct competitor"));
  const text = parts.join(", ");
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}.` : `I looked at places in ${area.label}.`;
}

// Spoken words: "3 kilometres" and "15 ringgit" read better aloud than "3 km" and "RM15".
function spokenRadius(metres) {
  if (metres >= 1000) {
    const km = Number((metres / 1000).toFixed(1));
    return `${km} kilometre${km === 1 ? "" : "s"}`;
  }
  return `${Math.round(metres)} metres`;
}

function spokenList(items) {
  return items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items.at(-1)}` : items[0] ?? "";
}

function spokenPrice(place) {
  if (typeof place.average_price === "number") return `costs about ${Math.round(place.average_price)} ringgit per person`;
  if (place.min_price != null && place.max_price != null) return `costs ${place.min_price} to ${place.max_price} ringgit per person`;
  return null;
}

// "a cafe" for a kind of venue, "a Japanese place" for a cuisine.
const VENUE_WORDS = /\b(cafe|café|bakery|bar|restaurant|shop|stall|kopitiam|bistro|pub|food court|hawker)\b/i;

function spokenKind(kind) {
  const words = VENUE_WORDS.test(kind) ? kind.toLowerCase() : `${kind} place`;
  return `${/^[aeiou]/i.test(words) ? "an" : "a"} ${words}`;
}

function placeNarration(place, kind, top) {
  const name = place.label || "this place";
  const what = kind ? `, ${spokenKind(kind)}` : "";
  const opening = top ? `My top pick is ${name}${what}.` : `Number ${place.rank}, ${name}${what}.`;
  const facts = [];
  if (typeof place.average_rating === "number") {
    facts.push(typeof place.review_count === "number" && place.review_count > 0
      ? `is rated ${place.average_rating} from ${place.review_count.toLocaleString()} reviews` : `is rated ${place.average_rating}`);
  }
  const price = spokenPrice(place);
  if (price) facts.push(price);
  if (typeof place.distance_m === "number") facts.push(`is ${spokenRadius(place.distance_m)} away`);
  const detail = facts.length ? ` It ${spokenList(facts)}.` : " The data doesn't include its rating or price, so open it on the map for more.";
  return opening + detail;
}

function areaNarration(area, ranked) {
  const { role, score, restaurants, competitors } = area.properties ?? {};
  const opening = ranked ? (area.properties.rank === 1 ? `The best choice is ${area.label}.` : `Number ${area.properties.rank}, ${area.label}.`)
    : `I searched only inside ${area.label}, outlined on the map.`;
  const facts = [];
  if (role && !(ranked && area.properties.rank === 1 && /^Best/.test(role))) facts.push(`It is the ${role.toLowerCase()}.`);
  const figures = [];
  if (typeof score === "number") figures.push(`an opportunity score of ${score} out of 100`);
  if (typeof restaurants === "number") figures.push(count(restaurants, "restaurant"));
  if (typeof competitors === "number") figures.push(count(competitors, "direct competitor"));
  if (figures.length) facts.push(`It has ${spokenList(figures)}.`);
  return [opening, ...facts].join(" ");
}

export function cinematicScenes(mapData) {
  const overlays = mapOverlays(mapData);
  const places = mapPlaces(mapData).filter((place) => Number.isFinite(place.latitude) && Number.isFinite(place.longitude));
  const areas = overlays.filter((overlay) => overlay.kind === "area");
  const radius = overlays.find((overlay) => overlay.kind === "radius");
  const ranked = areas.filter((area) => Number.isInteger(area.properties?.rank));
  const scenes = [];

  if (!places.length && !areas.length) return scenes;

  // The tour opens on the search itself (the areas or the circle), not a restatement of the question.
  // Compared areas count down to the best one; a searched area is a single step.
  if (ranked.length > 1) {
    scenes.push({ id: "areas", focus: { type: "areas" }, title: `I compared ${count(ranked.length, "area")}`,
      caption: ranked.map((area) => area.label).join(", ") + ".",
      narration: `I compared ${count(ranked.length, "area")}: ${spokenList(ranked.map((area) => area.label))}. I'll go from the last one up to the best.`,
      places: false });
    for (const area of [...ranked].sort((a, b) => b.properties.rank - a.properties.rank)) {
      scenes.push({ id: `area:${area.id}`, focus: { type: "area", id: area.id }, title: `#${area.properties.rank} ${area.label}`,
        caption: areaCaption(area), narration: areaNarration(area, true), places: false });
    }
  } else {
    for (const area of areas.slice(0, 2)) {
      scenes.push({ id: `area:${area.id}`, focus: { type: "area", id: area.id }, title: `I searched in ${area.label}`,
        caption: areaCaption(area), narration: areaNarration(area, false), places: false });
    }
  }

  if (radius) {
    const metres = radius.properties?.radius_m;
    const centre = radius.label === "Your location" ? "your location" : radius.label;
    scenes.push({ id: "radius", focus: { type: "radius", id: radius.id },
      title: metres > 0 ? `I searched within ${radiusText(metres)}` : "I searched around this point",
      caption: metres > 0 ? `The circle is ${radiusText(metres)} around ${radius.label.toLowerCase() === "your location" ? "your location" : radius.label}.`
        : `The search started from ${radius.label === "Your location" ? "your location" : radius.label}.`,
      narration: metres > 0 ? `I searched within ${spokenRadius(metres)} of ${centre}. Only places inside this circle were considered.`
        : `I searched around ${centre}, the blue point on the map.`,
      places: false });
  }

  if (places.length) {
    const shown = places.slice(0, MAX_TOUR_PLACES);
    scenes.push({ id: "places", focus: { type: "all" }, title: places.length === 1 ? "I found 1 place" : `I picked ${places.length} places`,
      caption: places.length > shown.length ? `Here are the top ${shown.length}, from #${shown.length} up to #1.`
        : shown.length > 1 ? `Here they are, from #${shown.length} up to #1.` : "Here it is.",
      narration: places.length === 1 ? "One place matched what you asked for."
        : places.length > shown.length ? `${places.length} places matched. I'll show you the top ${shown.length}, from number ${shown.length} up to my top pick.`
          : `${places.length} places matched what you asked for. I'll go from number ${shown.length} up to my top pick.`,
      places: true });
    for (const place of [...shown].reverse()) {
      const kind = placeKind(place);
      scenes.push({ id: `place:${place.id}`, focus: { type: "place", id: place.id },
        title: `#${place.rank} ${place.label || "Unnamed place"}${kind ? ` · ${kind}` : ""}`, caption: placeCaption(place),
        narration: placeNarration(place, kind, place.rank === 1 && shown.length > 1), places: true });
    }
  }

  scenes.push({ id: "finish", focus: { type: "all" }, title: "That's the full picture",
    caption: places.length ? "Drag the map or open any place for its details." : "Click any area for its figures.",
    narration: places.length ? "That's the full picture. Open any place on the map to see its hours, address and directions."
      : "That's the full comparison. Click any area on the map to see its figures.", places: true });
  return scenes;
}

// The model's words for each step (see the backend's tour_script.py) replace the app's own, one step at a time,
// so a step the model left out still reads well.
export function applyTourScript(scenes, script) {
  if (!script || typeof script !== "object") return scenes;
  return scenes.map((scene) => {
    const written = script[scene.id];
    if (!written || typeof written !== "object") return scene;
    const lines = Object.fromEntries(["title", "caption", "narration"]
      .filter((key) => typeof written[key] === "string" && written[key].trim()).map((key) => [key, written[key].trim()]));
    return { ...scene, ...lines };
  });
}

function firstSentence(text) {
  // A full stop ends a sentence only before a space or the end, never in "4.6".
  const found = /^(.*?[.!?])(\s|$)/.exec(text?.trim() ?? "");
  return found ? found[1] : text;
}

// The tour's first step keeps one sentence, so it reaches the places quickly.
export function shortOpening(scenes) {
  if (!scenes.length) return scenes;
  const [first, ...rest] = scenes;
  return [{ ...first, narration: firstSentence(first.narration), caption: firstSentence(first.caption) }, ...rest];
}

// The tour is worth offering only when it has more to show than the closing view.
export function hasCinematic(mapData) {
  return cinematicScenes(mapData).length > 1;
}
