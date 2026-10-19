import { hasMapView } from "./mapPresentation.js";

const GRAPH_EVIDENCE_KEY = "foodsight.showKnowledgeGraphEvidence";

export function hasGraphView(graphData) {
  return Array.isArray(graphData?.nodes) && graphData.nodes.length > 0;
}

// Tabs the View Details panel can show for one response, in display order.
// An empty list means there is nothing to show, so the button is hidden.
export function detailTabs(message, { showKnowledgeGraph = true } = {}) {
  const tabs = [];
  if (hasMapView(message?.mapData, message?.mapImage)) tabs.push("map");
  if (showKnowledgeGraph && hasGraphView(message?.graphData)) tabs.push("knowledge");
  return tabs;
}

// Per-browser preference; storage can be unavailable (private mode), so default to shown.
export function loadShowGraphEvidence(storage = globalThis.localStorage) {
  try {
    return storage?.getItem(GRAPH_EVIDENCE_KEY) !== "false";
  } catch {
    return true;
  }
}

export function saveShowGraphEvidence(value, storage = globalThis.localStorage) {
  try {
    storage?.setItem(GRAPH_EVIDENCE_KEY, String(Boolean(value)));
  } catch {
    // The setting still applies for this session.
  }
}
