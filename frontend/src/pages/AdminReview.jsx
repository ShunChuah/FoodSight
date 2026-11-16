import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, Moon } from "lucide-react";
import { getOverview } from "../api/adminApi.js";
import { saveThemePreference } from "../api/preferencesApi";
import Logo from "../components/Logo.jsx";
import { useTheme } from "../context/ThemeContext.jsx";
import GoogleMatchesTab from "../components/admin/GoogleMatchesTab.jsx";
import HistoryTab from "../components/admin/HistoryTab.jsx";
import LogsTab from "../components/admin/LogsTab.jsx";
import NearbyTab from "../components/admin/NearbyTab.jsx";
import OverviewTab from "../components/admin/OverviewTab.jsx";
import RemovedTab from "../components/admin/RemovedTab.jsx";

// The admin review page (/admin, admins only): the pipeline's review files and the
// decisions that go into src/reference/ for the next nightly update. Opened from "Review"
// in the chat sidebar; kept on its own route so it can move to a separate admin interface.

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "google", label: "Google matches", count: (o) => o.google_matches.waiting_decision },
  { id: "removed", label: "Removed restaurants", count: (o) => o.removed_restaurants.waiting_decision },
  { id: "nearby", label: "Nearby places" },
  { id: "history", label: "Update history" },
  { id: "logs", label: "Logs" },
];

// The same switch as the chat sidebar's: saved in this browser and to the account (/preferences).
function DarkModeSwitch() {
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  const toggle = () => {
    const next = dark ? "light" : "dark";
    setTheme(next);
    saveThemePreference(next).catch((error) => console.error("Failed to save theme", error));
  };
  return (
    <div className="ml-auto flex h-[2.5rem] items-center gap-3 rounded-[0.625rem] border border-gray-200 bg-white pl-3 pr-2 text-ink dark:border-line-dark dark:bg-surface-dark dark:text-white">
      <Moon className="size-[1rem]" />
      <span className="text-[0.8125rem]">Dark Mode</span>
      <button
        type="button"
        role="switch"
        aria-checked={dark}
        aria-label="Dark mode"
        onClick={toggle}
        className={`relative ml-1 h-[1.625rem] w-[3.25rem] cursor-pointer rounded-full transition-colors ${dark ? "bg-[#5a321f]" : "bg-gray-200"}`}
      >
        <span className={`absolute top-1 left-1 size-[1.125rem] rounded-full bg-white transition-transform ${dark ? "translate-x-[1.625rem]" : ""}`} />
      </button>
    </div>
  );
}

export default function AdminReview() {
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab") : "overview";
  const [overview, setOverview] = useState(null);
  const [overviewError, setOverviewError] = useState(null);
  const [version, setVersion] = useState(0);

  // The overview also gives the tab counts, so it is read again after every decision
  useEffect(() => {
    let alive = true;
    getOverview().then(
      (data) => { if (alive) { setOverview(data); setOverviewError(null); } },
      (error) => { if (alive) setOverviewError(error); },
    );
    return () => { alive = false; };
  }, [version]);

  const reload = () => setVersion((v) => v + 1);
  // The tab (and the log day) live in the address, so Back and a reload keep them
  const openTab = (id, extra = {}) => setParams(id === "overview" ? {} : { tab: id, ...extra });

  return (
    <div className="flex h-screen flex-col bg-zinc-50 text-ink dark:bg-page-dark dark:text-white">
      <header className="flex h-[4.25rem] shrink-0 items-center gap-6 border-b border-gray-200 bg-white px-6 dark:border-line-dark dark:bg-surface-dark">
        <Link to="/chat" className="inline-flex items-center gap-1.5 text-[0.8125rem] font-medium text-gray-500 hover:text-brand dark:text-muted-dark">
          <ArrowLeft className="size-[1rem]" /> Back to chat
        </Link>
        <Logo className="h-[2rem] w-auto" />
        <h1 className="text-[1.0625rem] font-bold">Review</h1>
        <nav className="ml-4 flex h-full items-stretch gap-1">
          {TABS.map((t) => {
            const count = overview && t.count ? t.count(overview) : 0;
            const active = t.id === tab;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => openTab(t.id)}
                className={`inline-flex cursor-pointer items-center gap-2 border-b-[0.1875rem] px-3 text-[0.875rem] font-semibold transition-colors ${
                  active ? "border-brand text-ink dark:text-white" : "border-transparent text-gray-500 hover:text-ink dark:text-muted-dark dark:hover:text-white"
                }`}
              >
                {t.label}
                {count > 0 && <span className="rounded-full bg-brand px-1.5 py-[0.0625rem] text-[0.6875rem] text-white">{count}</span>}
              </button>
            );
          })}
        </nav>
        <DarkModeSwitch />
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        {tab === "overview" && <OverviewTab overview={overview} error={overviewError} onRetry={reload} onOpenTab={openTab} />}
        {tab === "google" && <GoogleMatchesTab onChanged={reload} />}
        {tab === "removed" && <RemovedTab onChanged={reload} />}
        {tab === "nearby" && <NearbyTab onChanged={reload} />}
        {tab === "history" && <HistoryTab />}
        {tab === "logs" && <LogsTab day={params.get("day")} onDay={(day) => openTab("logs", { day })} />}
      </main>
    </div>
  );
}
