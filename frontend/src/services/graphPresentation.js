const DARK_TEXT = "#18181b";
const LIGHT_TEXT = "#ffffff";
// The node labels of the Neo4j graph. Warm FoodSight palette: brand orange for restaurants, then
// rust, navy, taupe, teal, peach, gold, plum, green, slate and olive (all text pairs checked at
// 4.5:1 or better).
export const NODE_TYPES = {
  Restaurant: { label: "Restaurant", color: "#ff6129", textColor: LIGHT_TEXT },
  Cuisine: { label: "Cuisine", color: "#8d4630", textColor: LIGHT_TEXT },
  Area: { label: "Area", color: "#253040", textColor: LIGHT_TEXT },
  City: { label: "City", color: "#9b8070", textColor: DARK_TEXT },
  Location: { label: "Location", color: "#2f6f6a", textColor: LIGHT_TEXT },
  PriceRange: { label: "Price range", color: "#f0a67a", textColor: DARK_TEXT },
  Rating: { label: "Rating", color: "#7a5c12", textColor: LIGHT_TEXT },
  BusinessProfile: { label: "Business profile", color: "#6d4c7d", textColor: LIGHT_TEXT },
  OperatingHours: { label: "Opening hours", color: "#2f6b3f", textColor: LIGHT_TEXT },
  Facility: { label: "Facility", color: "#5a6672", textColor: LIGHT_TEXT },
  Dish: { label: "Dish", color: "#43443c", textColor: LIGHT_TEXT },
};
const FALLBACK_TYPE = { label: "Other", color: "#e4e3df", textColor: DARK_TEXT };

// Every node is a circle with its name inside, as in Neo4j Browser; places are bigger, so each
// stands out as the centre of its "flower" of facts. Sizes are pixels at 100% zoom.
export const LABEL = { fontSize: 11, lineHeight: 13, maxLines: 3 };
const NODE_SIZES = { Restaurant: 96 };
const DEFAULT_NODE_SIZE = 80;
// Text only fits across the middle of a circle.
const TEXT_WIDTH_SHARE = 0.78;

export function nodeSize(label) {
  return NODE_SIZES[label] ?? DEFAULT_NODE_SIZE;
}

// Word-wrap `text` to lines no wider than maxWidth, breaking at spaces and after hyphens
// ("Budget-" / "friendly"). `measure(text)` returns a width in pixels.
export function wrapLines(text, measure, maxWidth) {
  const lines = [];
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    word.split(/(?<=-)(?=.)/).forEach((part, index) => {
      const last = lines.at(-1);
      // The parts of a hyphenated word join without a space.
      const joined = last === undefined ? part : `${last}${index > 0 ? "" : " "}${part}`;
      if (last !== undefined && measure(joined) <= maxWidth) lines[lines.length - 1] = joined;
      else lines.push(part);
    });
  }
  return lines.length ? lines : [""];
}

// The name as at most LABEL.maxLines lines that fit inside a circle of this size. What does
// not fit ends in "…".
export function circleLabel(name, measure, size) {
  const maxWidth = size * TEXT_WIDTH_SHARE;
  const lines = wrapLines(name, measure, maxWidth);
  const kept = lines.slice(0, LABEL.maxLines);
  if (lines.length > kept.length) kept[kept.length - 1] += "…";
  return kept.map((line) => fitWidth(line, measure, maxWidth)).join("\n");
}

function fitWidth(line, measure, maxWidth) {
  if (measure(line) <= maxWidth) return line;
  let cut = line.replace(/…$/, "");
  while (cut.length > 1 && measure(`${cut}…`) > maxWidth) cut = cut.slice(0, -1);
  return `${cut.trimEnd()}…`;
}

export function nodeType(label) {
  return NODE_TYPES[label] ?? FALLBACK_TYPE;
}

// "HAS_PRICE_RANGE" -> "has price range"
export function relationshipLabel(type) {
  return String(type || "related to").replaceAll("_", " ").toLowerCase();
}

// Rough text width for when no canvas is available (tests); the component measures real text.
const estimateWidth = (text) => String(text).length * LABEL.fontSize * 0.6;

// Starting positions for the force layout (pixels at 100% zoom).
const HUB_SPACING = 260; // room each place gets on the circle of places
const PETAL_DISTANCE = 110; // a fact only one place has starts this far from it
const SHARED_OFFSET = 25; // a shared fact starts this far from the middle of its places
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5)); // spreads petals evenly, in any number

// Where each node starts before the force layout spreads the graph out, so the same answer
// always settles into the same picture. Places (nodes with no relationships coming in) sit on a
// circle. The nodes linked to them start around them, one ring out at a time (a place's
// Location, then the Area beyond it): beside the one node they are linked to, or between several.
export function seedPositions(graphData) {
  const nodes = (graphData?.nodes ?? []).filter((node) => node?.id);
  const ids = new Set(nodes.map((node) => node.id));
  const edges = (graphData?.edges ?? []).filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  const targets = new Set(edges.map((edge) => edge.target));
  const hubs = nodes.filter((node) => !targets.has(node.id));
  const neighbours = new Map(nodes.map((node) => [node.id, []]));
  for (const edge of edges) {
    neighbours.get(edge.source).push(edge.target);
    neighbours.get(edge.target).push(edge.source);
  }

  const positions = new Map();
  const ring = hubs.length > 1 ? (HUB_SPACING * hubs.length) / (2 * Math.PI) : 0;
  hubs.forEach((hub, index) => {
    const angle = (2 * Math.PI * index) / hubs.length - Math.PI / 2;
    positions.set(hub.id, { x: ring * Math.cos(angle), y: ring * Math.sin(angle) });
  });

  const petals = new Map(); // node (or group of nodes) -> petals placed around it so far
  let unplaced = nodes.filter((node) => !positions.has(node.id));
  while (unplaced.length) {
    // The next ring: nodes linked to one already placed (or, if none are, whatever is left).
    const ownersOf = new Map(unplaced.map((node) => [node.id, neighbours.get(node.id).filter((id) => positions.has(id))]));
    const nextRing = unplaced.some((node) => ownersOf.get(node.id).length)
      ? unplaced.filter((node) => ownersOf.get(node.id).length)
      : unplaced;
    for (const node of nextRing) {
      const owners = ownersOf.get(node.id);
      const centre = owners.length
        ? {
          x: owners.reduce((sum, id) => sum + positions.get(id).x, 0) / owners.length,
          y: owners.reduce((sum, id) => sum + positions.get(id).y, 0) / owners.length,
        }
        : { x: 0, y: 0 };
      const key = owners.join("|");
      const petal = petals.get(key) ?? 0;
      petals.set(key, petal + 1);
      const distance = owners.length === 1 ? PETAL_DISTANCE : SHARED_OFFSET * (1 + petal);
      positions.set(node.id, {
        x: centre.x + distance * Math.cos(petal * GOLDEN_ANGLE),
        y: centre.y + distance * Math.sin(petal * GOLDEN_ANGLE),
      });
    }
    unplaced = unplaced.filter((node) => !positions.has(node.id));
  }
  return positions;
}

// The force layout keeps circles apart only approximately; this pushes any two that still
// touch away from each other along the line between them until none do (or `rounds` run out).
// points: [{ id, x, y, r }] -> Map id -> { x, y }.
export function spreadOverlaps(points, { gap = 6, rounds = 80 } = {}) {
  const placed = points.map((point) => ({ ...point }));
  for (let round = 0; round < rounds; round += 1) {
    let moved = false;
    for (let i = 0; i < placed.length; i += 1) {
      for (let j = i + 1; j < placed.length; j += 1) {
        const a = placed[i];
        const b = placed[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let distance = Math.hypot(dx, dy);
        const overlap = a.r + b.r + gap - distance;
        if (overlap <= 0) continue;
        if (distance === 0) {
          // Same spot: part them in a direction that depends only on their order.
          [dx, dy, distance] = [Math.cos(i + j), Math.sin(i + j), 1];
        }
        const push = overlap / 2 / distance;
        a.x -= dx * push;
        a.y -= dy * push;
        b.x += dx * push;
        b.y += dy * push;
        moved = true;
      }
    }
    if (!moved) break;
  }
  return new Map(placed.map(({ id, x, y }) => [id, { x, y }]));
}

// graphData { nodes, edges } -> Cytoscape elements. Edges to unknown nodes are dropped
// (Cytoscape throws on them). `measure(text)` gives a text width in pixels.
export function toCytoscapeElements(graphData, measure = estimateWidth) {
  const nodes = (graphData?.nodes ?? []).filter((node) => node?.id);
  const ids = new Set(nodes.map((node) => node.id));
  const edges = (graphData?.edges ?? []).filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  const positions = seedPositions({ nodes, edges });
  return [
    ...nodes.map((node) => {
      const name = node.name || node.id;
      const size = nodeSize(node.label);
      return {
        group: "nodes",
        position: { ...positions.get(node.id) },
        data: {
          id: node.id,
          name,
          type: node.label,
          color: nodeType(node.label).color,
          textColor: nodeType(node.label).textColor,
          properties: node.properties ?? {},
          size,
          label: circleLabel(name, measure, size),
        },
      };
    }),
    ...edges.map((edge, index) => ({
      group: "edges",
      data: { id: `edge-${index}`, source: edge.source, target: edge.target, label: relationshipLabel(edge.type) },
    })),
  ];
}
