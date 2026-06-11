import "../../styles/explanation.css";

const SAMPLE_KG_IMAGE_URL =
  "https://dist.neo4j.com/wp-content/uploads/20210210101155/1Rf98vgvcLle1SZvLmmIwaQ.png";

function KnowledgeGraphEvidence() {
  return (
    <section className="kg-evidence-section">
      <h3>Knowledge Graph Evidence</h3>

      <div className="kg-graph-box">
        <img src={SAMPLE_KG_IMAGE_URL} alt="Knowledge graph visualization" />
      </div>
    </section>
  );
}

export default KnowledgeGraphEvidence;
