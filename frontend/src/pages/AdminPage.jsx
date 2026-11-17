import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet } from "react-router-dom";
import { getOverview } from "../api/adminApi.js";
import { fetchThemePreference, saveThemePreference } from "../api/preferencesApi";
import { AdminClosedSidebar, AdminSidebar } from "../components/admin/AdminSidebar";
import Notice from "../components/Notice";
import ChangePassword from "../components/modals/ChangePassword";
import Profile from "../components/modals/Profile";
import Settings from "../components/modals/Settings";
import { useTheme } from "../context/ThemeContext.jsx";
import { getAdminSubmissions } from "../api/businessApi";
import { loadBusinessOptions } from "../services/businessForm";
import "../styles/dashboard.css";
import "../styles/business.css";
import "../styles/admin.css";

// The admin layout (/admin, admins only; where an admin lands after login): the sidebar, and the
// business submissions (GET /admin/submissions) or the pipeline review pages beside it.
function AdminPage() {
  const { theme, setTheme } = useTheme();
  const darkMode = theme === "dark";
  const themeChangedRef = useRef(false);
  // Saved in this browser and to the account (/preferences), as on the chat dashboard
  const setDarkMode = (next) => {
    const nextTheme = next ? "dark" : "light";
    themeChangedRef.current = true;
    setTheme(nextTheme);
    saveThemePreference(nextTheme).catch((error) => console.error("Failed to save theme", error));
  };
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // The open account dialog, as on the chat dashboard: "settings", "profile", "password" or null.
  const [openDialog, setOpenDialog] = useState(null);
  // Every business submission, and how many restaurants FoodSight has; read again after a decision
  const [submissions, setSubmissions] = useState([]);
  const [submissionsInfo, setSubmissionsInfo] = useState({ state: "loading", restaurants: null });
  const [submissionsVersion, setSubmissionsVersion] = useState(0);
  const reloadSubmissions = useCallback(() => setSubmissionsVersion((version) => version + 1), []);
  const [notice, setNotice] = useState("");
  const closeNotice = useCallback(() => setNotice(""), []);

  // The pipeline overview (GET /admin/overview): the sidebar's counts and the pipeline Overview page.
  // Read again when the review pages open and after each decision there.
  const [overview, setOverview] = useState(null);
  const [overviewError, setOverviewError] = useState(null);
  const [overviewVersion, setOverviewVersion] = useState(0);
  const reloadOverview = useCallback(() => setOverviewVersion((version) => version + 1), []);

  useEffect(() => {
    let alive = true;
    getOverview().then(
      (data) => { if (alive) { setOverview(data); setOverviewError(null); } },
      (error) => { if (alive) setOverviewError(error); },
    );
    return () => { alive = false; };
  }, [overviewVersion]);

  // Apply the account's saved theme after login, unless it was already switched on this page.
  useEffect(() => {
    let ignore = false;
    fetchThemePreference()
      .then((savedTheme) => {
        if (!ignore && savedTheme && !themeChangedRef.current) setTheme(savedTheme);
      })
      .catch((error) => console.error("Failed to load theme", error));
    return () => { ignore = true; };
  }, [setTheme]);

  useEffect(() => {
    let alive = true;
    // The lists give the submissions' labels (restaurant type, facility groups)
    Promise.all([getAdminSubmissions(), loadBusinessOptions().catch(() => null)]).then(
      ([data]) => {
        if (!alive) return;
        setSubmissions(data.submissions);
        setSubmissionsInfo({ state: "ready", restaurants: data.restaurants, submittedRestaurants: data.submittedRestaurants });
      },
      () => { if (alive) setSubmissionsInfo((previous) => ({ ...previous, state: "error" })); },
    );
    return () => { alive = false; };
  }, [submissionsVersion]);
  const submissionsWaiting = submissions.filter((submission) => ["waiting", "under_review"].includes(submission.status)).length;

  const pipeline = { overview, error: overviewError, reload: reloadOverview };

  return (
    <div className="dashboard-page admin-page" data-theme={darkMode ? "dark" : "light"}>
      {sidebarOpen ? (
        <AdminSidebar
          darkMode={darkMode} setDarkMode={setDarkMode} overview={overview} submissionsWaiting={submissionsWaiting}
          onClose={() => setSidebarOpen(false)} onSettingsOpen={() => setOpenDialog("settings")}
          onProfileOpen={() => setOpenDialog("profile")}
        />
      ) : (
        <AdminClosedSidebar
          overview={overview} submissionsWaiting={submissionsWaiting}
          onOpen={() => setSidebarOpen(true)} onSettingsOpen={() => setOpenDialog("settings")}
          onProfileOpen={() => setOpenDialog("profile")}
        />
      )}
      <main className="admin-main">
        <Outlet context={{ submissions, submissionsInfo, reloadSubmissions, setNotice, darkMode, pipeline }} />
      </main>
      {openDialog === "settings" && (
        <Settings
          darkMode={darkMode} onToggleDarkMode={() => setDarkMode(!darkMode)}
          showChatOptions={false} onClose={() => setOpenDialog(null)}
          onEditProfile={() => setOpenDialog("profile")}
          onChangePassword={() => setOpenDialog("password")}
        />
      )}
      {openDialog === "profile" && (
        <Profile onBack={() => setOpenDialog("settings")} onClose={() => setOpenDialog(null)} />
      )}
      {openDialog === "password" && (
        <ChangePassword onBack={() => setOpenDialog("settings")} onClose={() => setOpenDialog(null)} />
      )}
      <Notice message={notice} onClose={closeNotice} />
    </div>
  );
}

export default AdminPage;
