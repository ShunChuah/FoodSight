import { useState } from "react";
import { Waypoints, Map, PlayCircle, X } from "lucide-react";
import KnowledgeGraphEvidence from "./KnowledgeGraphEvidence";
import ExplanationMapSkeleton from "./ExplanationMapSkeleton";
import MapPreview from "../map/MapPreview";
import { hasMapView } from "../../services/mapPresentation";
import "../../styles/explanation.css";

// `tabs` lists only the tabs with something to show (see detailTabs).
function AIExplanationPanel({ tabs, mapImage, mapData, graphData, darkMode = false, onClose }) {
  const showMap = tabs.includes("map");
  const showKnowledge = tabs.includes("knowledge");
  const [selectedTab, setSelectedTab] = useState(tabs[0]);
  // A tab can disappear while open (graph evidence turned off in Settings).
  const activeTab = tabs.includes(selectedTab) ? selectedTab : tabs[0];
  const displayedMapImage = mapImage;
  const [settledMapImage, setSettledMapImage] = useState(null);
  const isMapLoading = Boolean(displayedMapImage) && settledMapImage !== displayedMapImage;

  return (
    <aside className="ai-explanation-panel">
      <div className="explanation-header">
        <div className="explanation-tabs" role="tablist" aria-label="Explanation evidence">
          {showMap && <button
            className={`explanation-tab ${activeTab === "map" ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === "map"}
            onClick={() => setSelectedTab("map")}
          >
            <Map />
            <span>Map</span>
          </button>}

          {showKnowledge && <button
            className={`explanation-tab ${activeTab === "knowledge" ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === "knowledge"}
            onClick={() => setSelectedTab("knowledge")}
          >
            <Waypoints />
            <span>Knowledge Graph Evidence</span>
          </button>}
        </div>

        <button
          className="close-explanation-btn"
          type="button"
          onClick={onClose}
          title="Close explanation"
        >
          <X />
        </button>
      </div>

      <div className="explanation-content">
        {activeTab === "map" ? (
          <section className="map-evidence-section" role="tabpanel">
            {hasMapView(mapData) ? <MapPreview mapData={mapData} /> : (
            <div className={`explanation-map-frame${displayedMapImage ? "" : " is-empty"}`}>
              {displayedMapImage && isMapLoading && <ExplanationMapSkeleton />}
              {displayedMapImage ? (
                <img
                  key={displayedMapImage}
                  className={isMapLoading ? "is-loading" : ""}
                  src={displayedMapImage}
                  alt="Map evidence"
                  onLoad={() => setSettledMapImage(displayedMapImage)}
                  onError={() => setSettledMapImage(displayedMapImage)}
                />
              ) : (
                <p>{mapData?.message || "No map is available for this response."}</p>
              )}
            </div>
            )}

            <div className="cinematic-action-row">
              <button className="play-cinematic-panel-btn" title="Cinematic playback isn’t available yet" type="button" disabled>
                <PlayCircle />
                <span>Play Cinematic AI</span>
              </button>
            </div>
          </section>
        ) : (
          <div className="kg-evidence-panel" role="tabpanel">
            <KnowledgeGraphEvidence graphData={graphData} darkMode={darkMode} />
          </div>
        )}
      </div>
    </aside>
  );
}

export default AIExplanationPanel;
