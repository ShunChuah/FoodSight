const DARK_TEXT = "#18181b";
const LIGHT_TEXT = "#ffffff";
// Warm FoodSight palette: brand orange for restaurants, then rust, navy, peach, slate,
// taupe and olive (all text pairs checked at 4.5:1 or better).
export const NODE_TYPES = {
  Restaurant: { label: "Restaurant", color: "#ff6129", textColor: LIGHT_TEXT, shape: "round-rectangle" },
  Cuisine: { label: "Cuisine", color: "#8d4630", textColor: LIGHT_TEXT, shape: "ellipse" },
  Area: { label: "Area", color: "#253040", textColor: LIGHT_TEXT, shape: "ellipse" },
  City: { label: "City", color: "#9b8070", textColor: DARK_TEXT, shape: "ellipse" },
  PriceRange: { label: "Price range", color: "#f0a67a", textColor: DARK_TEXT, shape: "ellipse" },
  Facility: { label: "Facility", color: "#5a6672", textColor: LIGHT_TEXT, shape: "ellipse" },
  Dish: { label: "Dish", color: "#43443c", textColor: LIGHT_TEXT, shape: "ellipse" },
};
const FALLBACK_TYPE = { label: "Other", color: "#e4e3df", textColor: DARK_TEXT, shape: "ellipse" };

// Text sizing inside the shapes (pixels at 100% zoom).
export const LABEL = { fontSize: 11, lineHeight: 14, maxWidth: 120, paddingX: 12, paddingY: 8 };

// Word-wrap `text` to lines no wider than maxWidth, the way Cytoscape's "text-wrap: wrap"
// does (breaking at spaces). `measure(text)` returns a width in pixels.
export function wrapLines(text, measure, maxWidth = LABEL.maxWidth) {
  const lines = [];
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const last = lines.at(-1);
    if (last !== undefined && measure(`${last} ${word}`) <= maxWidth) lines[lines.length - 1] = `${last} ${word}`;
    else lines.push(word);
  }
  return lines.length ? lines : [""];
}

// A shape just big enough for its wrapped text. Text inside an ellipse only fits in the
// middle, so ellipses get extra room.
export function labelBox(lines, measure, shape) {
  const textWidth = Math.max(...lines.map((line) => measure(line)));
  const width = textWidth + LABEL.paddingX * 2;
  const height = lines.length * LABEL.lineHeight + LABEL.paddingY * 2;
  const room = shape === "ellipse" ? 1.3 : 1;
  return { width: Math.ceil(width * room), height: Math.ceil(height * room) };
}

export function nodeType(label) {
  return NODE_TYPES[label] ?? FALLBACK_TYPE;
}

// Position of a node type in NODE_TYPES, so each row of the layout groups the same types
// together (all cuisines, then areas, then price ranges…). Unknown types go last.
const TYPE_ORDER = Object.keys(NODE_TYPES);
export function typeRank(label) {
  const index = TYPE_ORDER.indexOf(label);
  return index === -1 ? TYPE_ORDER.length : index;
}

// "HAS_PRICE_RANGE" -> "has price range"
export function relationshipLabel(type) {
  return String(type || "related to").replaceAll("_", " ").toLowerCase();
}

// Rough text width for when no canvas is available (tests); the component measures real text.
const estimateWidth = (text) => String(text).length * LABEL.fontSize * 0.6;

// The wrapped label (explicit line breaks) and the shape size that fits it.
function nodeLabel(name, shape, measure) {
  const lines = wrapLines(name, measure);
  return { label: lines.join("\n"), ...labelBox(lines, measure, shape) };
}

// graphData { nodes, edges } -> Cytoscape elements. Edges to unknown nodes are dropped
// (Cytoscape throws on them). `measure(text)` gives a text width in pixels.
export function toCytoscapeElements(graphData, measure = estimateWidth) {
  const nodes = (graphData?.nodes ?? []).filter((node) => node?.id);
  const ids = new Set(nodes.map((node) => node.id));
  return [
    ...nodes.map((node) => ({
      group: "nodes",
      data: {
        id: node.id,
        name: node.name || node.id,
        type: node.label,
        color: nodeType(node.label).color,
        textColor: nodeType(node.label).textColor,
        shape: nodeType(node.label).shape,
        properties: node.properties ?? {},
        ...nodeLabel(node.name || node.id, nodeType(node.label).shape, measure),
      },
    })),
    ...(graphData?.edges ?? [])
      .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
      .map((edge, index) => ({
        group: "edges",
        data: { id: `edge-${index}`, source: edge.source, target: edge.target, label: relationshipLabel(edge.type) },
      })),
  ];
}
