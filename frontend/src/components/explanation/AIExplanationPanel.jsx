import { useEffect, useState } from "react";
import { Waypoints, Map, PlayCircle, X } from "lucide-react";
import KnowledgeGraphEvidence from "./KnowledgeGraphEvidence";
import ExplanationMapSkeleton from "./ExplanationMapSkeleton";
import "../../styles/explanation.css";

const SAMPLE_MAP_IMAGE_URL =
  "https://docs.maptiler.com/leaflet/examples/nextjs/map.png";

function AIExplanationPanel({ mapImage, onClose }) {
  const [activeTab, setActiveTab] = useState("map");
  const displayedMapImage = mapImage || SAMPLE_MAP_IMAGE_URL;
  const [isMapLoading, setIsMapLoading] = useState(true);

  useEffect(() => {
    setIsMapLoading(true);
  }, [displayedMapImage]);

  return (
    <aside className="ai-explanation-panel">
      <div className="explanation-header">
        <div className="explanation-tabs" role="tablist" aria-label="Explanation evidence">
          <button
            className={`explanation-tab ${activeTab === "map" ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === "map"}
            onClick={() => setActiveTab("map")}
          >
            <Map />
            <span>Map</span>
          </button>

          <button
            className={`explanation-tab ${activeTab === "knowledge" ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === "knowledge"}
            onClick={() => setActiveTab("knowledge")}
          >
            <Waypoints />
            <span>Knowledge Graph Evidence</span>
          </button>
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
            <div className="explanation-map-frame">
              {isMapLoading && <ExplanationMapSkeleton />}
              <img
                className={isMapLoading ? "is-loading" : ""}
                src={displayedMapImage}
                alt="Map evidence"
                onLoad={() => setIsMapLoading(false)}
                onError={() => setIsMapLoading(false)}
              />
            </div>

            <div className="cinematic-action-row">
              <button className="play-cinematic-panel-btn" title="Play Cinematic AI" type="button">
                <PlayCircle />
                <span>Play Cinematic AI</span>
              </button>
            </div>
          </section>
        ) : (
          <div role="tabpanel">
            <KnowledgeGraphEvidence />
          </div>
        )}
      </div>
    </aside>
  );
}

export default AIExplanationPanel;
