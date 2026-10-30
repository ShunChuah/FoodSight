import "../../styles/explanation.css";

function KnowledgeGraphSkeleton() {
  return (
    <section className="kg-evidence-section" aria-busy="true">
      <h3>Knowledge Graph Evidence</h3>
      <div className="kg-graph-box kg-graph-skeleton" role="status">
        <span className="explanation-map-loading-text">Building the knowledge graph...</span>
      </div>
    </section>
  );
}

export default KnowledgeGraphSkeleton;
