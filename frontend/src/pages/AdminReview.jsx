import { useEffect } from "react";
import { Navigate, useNavigate, useOutletContext, useParams, useSearchParams } from "react-router-dom";
import GoogleMatchesTab from "../components/admin/GoogleMatchesTab.jsx";
import HistoryTab from "../components/admin/HistoryTab.jsx";
import LogsTab from "../components/admin/LogsTab.jsx";
import NearbyTab from "../components/admin/NearbyTab.jsx";
import OverviewTab from "../components/admin/OverviewTab.jsx";
import RemovedTab from "../components/admin/RemovedTab.jsx";
import { PIPELINE_PAGES, pipelinePath } from "../components/admin/pipelinePages.js";

// The pipeline review pages (/admin/pipeline/<page>, admins only), inside the admin layout
// (AdminPage): the pipeline's review files and the decisions that go into src/reference/ for the
// next nightly update. The admin sidebar has one item per page; the page is in the path and the
// log day in ?day=, so Back and a reload keep them. The overview (also the sidebar's counts) is
// kept by AdminPage.

export default function AdminReview() {
  const { page: pageId = "overview" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { pipeline } = useOutletContext();
  const { overview, error, reload } = pipeline;

  // Read the overview again whenever the review pages are opened: the nightly update may have changed it
  useEffect(() => { reload(); }, [reload]);

  const page = PIPELINE_PAGES.find((p) => p.id === pageId);
  if (!page) return <Navigate to={pipelinePath("overview")} replace />;

  const openTab = (id, query = {}) => {
    const search = new URLSearchParams(query).toString();
    navigate(pipelinePath(id) + (search ? `?${search}` : ""));
  };

  return (
    // The submissions pages' card and title (styles/admin.css)
    <div className={`admin-card admin-panel admin-pipeline${page.split ? " is-split" : ""}`}>
      <h1>{page.title}</h1>
      {page.id === "overview" && <OverviewTab overview={overview} error={error} onRetry={reload} onOpenTab={openTab} />}
      {page.id === "google" && <GoogleMatchesTab onChanged={reload} />}
      {page.id === "removed" && <RemovedTab onChanged={reload} />}
      {page.id === "nearby" && <NearbyTab onChanged={reload} />}
      {page.id === "history" && <HistoryTab />}
      {page.id === "logs" && <LogsTab day={params.get("day")} onDay={(day) => openTab("logs", { day })} />}
    </div>
  );
}
