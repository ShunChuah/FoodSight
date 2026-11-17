import { Activity, Building2, History, MapPinOff, MapPinned, ScrollText } from "lucide-react";

// The pipeline review pages (/admin/pipeline/...), one admin sidebar item each. `count` reads how many
// wait for a decision from GET /admin/overview; the sidebar shows it beside the item. `split`: a list
// on the left and the chosen item on the right, each scrolling on its own.
export const PIPELINE_PAGES = [
  { id: "overview", label: "Overview", title: "Pipeline overview", Icon: Activity },
  {
    id: "google", label: "Google matches", title: "Google matches", Icon: MapPinned, split: true,
    count: (overview) => overview.google_matches.waiting_decision,
  },
  {
    id: "removed", label: "Removed restaurants", title: "Removed restaurants", Icon: MapPinOff, split: true,
    count: (overview) => overview.removed_restaurants.waiting_decision,
  },
  { id: "nearby", label: "Nearby places", title: "Nearby places", Icon: Building2, split: true },
  { id: "history", label: "Update history", title: "Update history", Icon: History },
  { id: "logs", label: "Logs", title: "Logs", Icon: ScrollText, split: true },
];

export const pipelinePath = (id) => (id === "overview" ? "/admin/pipeline" : `/admin/pipeline/${id}`);

// How many wait for a decision on a page (0 while the overview is not loaded)
export const waitingCount = (page, overview) => (overview && page.count ? page.count(overview) || 0 : 0);
