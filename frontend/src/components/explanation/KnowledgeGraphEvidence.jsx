import { useEffect, useRef, useState } from "react";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { LABEL, toCytoscapeElements, typeRank } from "../../services/graphPresentation";
import "../../styles/explanation.css";

const ZOOM_STEP = 1.25;

// Cytoscape style sheet. Each node's colour, shape, wrapped label and size come from
// its data (graphPresentation.js); the name is written inside the shape.
function graphStyle(darkMode, fontFamily) {
  const line = darkMode ? "#52525b" : "#d4d4d8";
  return [
    {
      selector: "node",
      style: {
        "background-color": "data(color)",
        shape: "data(shape)",
        label: "data(label)",
        color: "data(textColor)",
        "font-family": fontFamily,
        "font-size": LABEL.fontSize,
        "font-weight": 600,
        "line-height": LABEL.lineHeight / LABEL.fontSize,
        "text-valign": "center",
        "text-halign": "center",
        "text-wrap": "wrap",
        width: "data(width)",
        height: "data(height)",
        "border-width": 2,
        "border-color": darkMode ? "#181818" : "#ffffff",
      },
    },
    {
      selector: "edge",
      style: {
        width: 1.5,
        "line-color": line,
        "target-arrow-color": line,
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        label: "data(label)",
        "font-size": 9,
        color: darkMode ? "#a1a1a1" : "#71717a",
        "text-rotation": "autorotate",
        "text-background-color": darkMode ? "#1f1f1f" : "#ffffff",
        "text-background-opacity": 1,
        "text-background-padding": 2,
      },
    },
  ];
}

const GRAPH_PADDING = 30;
const MIN_ZOOM_FACTOR = 0.25; // zoom out to a quarter of the fitted size
const MAX_ZOOM_FACTOR = 4;

// graphData: { nodes: [{ id, label, name, properties }], edges: [{ source, target, type }] }.
function KnowledgeGraphEvidence({ graphData, darkMode = false }) {
  const containerRef = useRef(null);
  const cyRef = useRef(null);
  const resetRef = useRef(null); // puts nodes back where the layout placed them
  const fontFamilyRef = useRef("sans-serif");
  const [status, setStatus] = useState("loading");

  // 1. Create the graph once per graphData; load Cytoscape only when this tab is opened.
  useEffect(() => {
    let cancelled = false;
    let cy = null;
    // Wait for the web font too, so the text is measured in the font it is drawn in.
    Promise.all([import("cytoscape"), document.fonts?.ready])
      .then(([{ default: cytoscape }]) => {
        if (cancelled || !containerRef.current) return;
        fontFamilyRef.current = getComputedStyle(containerRef.current).fontFamily;
        const context = document.createElement("canvas").getContext("2d");
        context.font = `600 ${LABEL.fontSize}px ${fontFamilyRef.current}`;
        cy = cytoscape({
          container: containerRef.current,
          elements: toCytoscapeElements(graphData, (text) => context.measureText(text).width),
          // Sizes must be known before the layout runs; colours follow the theme below.
          style: graphStyle(false, fontFamilyRef.current),
          // Layered layout: restaurants (or compared areas) in the top row, the cuisines,
          // areas and price ranges they connect to in the row below, grouped by type.
          layout: {
            name: "breadthfirst",
            directed: true,
            roots: (node) => node.indegree() === 0,
            depthSort: (a, b) => typeRank(a.data("type")) - typeRank(b.data("type")) || a.data("name").localeCompare(b.data("name")),
            spacingFactor: 1.1,
            padding: GRAPH_PADDING,
            animate: false,
          },
          // Drag nodes, drag the background to move the view, wheel or pinch to zoom.
          autounselectify: true,
          boxSelectionEnabled: false,
        });
        // Where the layout put each node, so Reset view can undo the user's dragging.
        const layoutPositions = Object.fromEntries(cy.nodes().map((node) => [node.id(), { ...node.position() }]));
        // Fit the whole graph, then allow zooming out to a quarter of that size and in to 4x.
        const fitGraph = () => {
          cy.minZoom(0.01);
          cy.maxZoom(10);
          cy.fit(undefined, GRAPH_PADDING);
          const fitted = cy.zoom();
          cy.minZoom(fitted * MIN_ZOOM_FACTOR);
          cy.maxZoom(Math.max(fitted * MAX_ZOOM_FACTOR, 1.5));
        };
        resetRef.current = () => {
          cy.nodes().positions((node) => ({ ...layoutPositions[node.id()] }));
          fitGraph();
        };
        fitGraph();
        cyRef.current = cy;
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
      cy?.destroy();
      cyRef.current = null;
      resetRef.current = null;
    };
  }, [graphData]);

  // 2. Follow the theme without redrawing the layout (keeps the user's zoom and position).
  useEffect(() => {
    if (status === "ready") cyRef.current?.style(graphStyle(darkMode, fontFamilyRef.current));
  }, [darkMode, status]);

  // 3. Buttons: zoom around the middle of the graph box, or reset nodes and zoom.
  const zoomBy = (factor) => {
    const cy = cyRef.current;
    if (cy) cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  };
  const resetView = () => resetRef.current?.();

  return (
    <section className="kg-evidence-section">
      <h3>Knowledge Graph Evidence</h3>

      <div className="kg-graph-box">
        <div className="kg-graph-canvas" ref={containerRef} aria-label="Knowledge graph of this answer" role="img" />
        {status === "loading" && <p className="kg-graph-status">Drawing the graph…</p>}
        {status === "error" && <p className="kg-graph-status">The graph couldn’t be drawn.</p>}
        {status === "ready" && (
          <div className="kg-zoom-controls">
            <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => zoomBy(ZOOM_STEP)}><Plus /></button>
            <button type="button" title="Zoom out" aria-label="Zoom out" onClick={() => zoomBy(1 / ZOOM_STEP)}><Minus /></button>
            <button type="button" title="Reset view" aria-label="Reset view" onClick={resetView}><RotateCcw /></button>
          </div>
        )}
      </div>

    </section>
  );
}

export default KnowledgeGraphEvidence;
