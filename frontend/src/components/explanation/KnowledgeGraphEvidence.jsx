import "../../styles/explanation.css";
import { mockNodes, mockEdges } from "../../../data/mockKnowledgeGraph";

function KnowledgeGraphEvidence() {
  return (
    <section className="kg-evidence-section">
      <h3>Knowledge Graph Evidence</h3>

      <div className="kg-graph-box">
        <svg className="kg-network-svg" viewBox="0 0 900 430" role="img" aria-label="Knowledge graph visualization">
          <g className="kg-network-lines">
            <path d="M160 115 C220 75 285 90 330 145" />
            <path d="M160 115 C210 160 270 175 330 145" />
            <path d="M330 145 C410 90 495 105 545 180" />
            <path d="M330 145 C405 220 470 235 545 180" />
            <path d="M545 180 C620 120 705 125 760 200" />
            <path d="M545 180 C625 250 705 260 760 200" />
            <path d="M330 145 C360 255 435 315 520 305" />
            <path d="M520 305 C600 280 690 285 760 200" />
            <path d="M190 300 C275 250 400 255 520 305" />
            <path d="M190 300 C260 340 405 355 520 305" />
          </g>

          {[
            [160, 115, 28, "#60a5fa", "George Town"],
            [330, 145, 34, "#8b5cf6", "Cafe"],
            [545, 180, 36, "#f59e0b", "Affordable"],
            [760, 200, 30, "#22c55e", "Location"],
            [520, 305, 32, "#ef4444", "Menu"],
            [190, 300, 25, "#ec4899", "Student"],
            [255, 70, 16, "#60a5fa", "Brew"],
            [420, 80, 16, "#8b5cf6", "Kopi"],
            [665, 95, 16, "#22c55e", "Heritage"],
            [690, 325, 16, "#f59e0b", "Promo"],
            [345, 350, 16, "#ef4444", "Snacks"],
            [105, 245, 16, "#ec4899", "Quiet"],
          ].map(([x, y, r, color, label]) => (
            <g className="kg-network-node" key={label}>
              <circle cx={x} cy={y} r={r} fill={color} />
              <text x={x} y={y + r + 20}>{label}</text>
            </g>
          ))}
        </svg>
      </div>

      <div className="kg-details-grid">
        <div className="kg-detail-card nodes-card">
          <h4>Nodes</h4>

          <div className="kg-chip-list">
            {mockNodes.map((node, index) => (
              <div className="kg-chip" key={index}>
                {node}
              </div>
            ))}
          </div>
        </div>

        <div className="kg-detail-card edges-card">
          <h4>Edges</h4>

          <div className="kg-chip-list">
            {mockEdges.map((edge, index) => (
              <div className="kg-chip edge-chip" key={index}>
                {edge}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export default KnowledgeGraphEvidence;
