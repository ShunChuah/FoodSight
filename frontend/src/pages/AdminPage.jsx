import { useCallback, useState } from "react";
import { Outlet } from "react-router-dom";
import { AdminClosedSidebar, AdminSidebar } from "../components/admin/AdminSidebar";
import Notice from "../components/Notice";
import Settings from "../components/modals/Settings";
import { useTheme } from "../context/ThemeContext.jsx";
import { MOCK_SUBMISSIONS } from "../../data/mockAdminSubmissions";
import "../styles/dashboard.css";
import "../styles/business.css";
import "../styles/admin.css";

// Submissions live in memory (mock data) until the admin API exists, so decisions reset on reload.
function AdminPage() {
  const { theme, setTheme } = useTheme();
  const darkMode = theme === "dark";
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [submissions, setSubmissions] = useState(MOCK_SUBMISSIONS);
  const [notice, setNotice] = useState("");
  const closeNotice = useCallback(() => setNotice(""), []);

  const updateSubmission = useCallback((id, change) => {
    setSubmissions((previous) => previous.map((submission) => (submission.id === id ? change(submission) : submission)));
  }, []);

  return (
    <div className="dashboard-page admin-page" data-theme={darkMode ? "dark" : "light"}>
      {sidebarOpen ? (
        <AdminSidebar
          darkMode={darkMode} setDarkMode={(next) => setTheme(next ? "dark" : "light")}
          onClose={() => setSidebarOpen(false)} onSettingsOpen={() => setSettingsOpen(true)}
        />
      ) : (
        <AdminClosedSidebar onOpen={() => setSidebarOpen(true)} onSettingsOpen={() => setSettingsOpen(true)} />
      )}
      <main className="admin-main">
        <Outlet context={{ submissions, updateSubmission, setNotice, darkMode }} />
      </main>
      {settingsOpen && (
        <Settings
          darkMode={darkMode} onToggleDarkMode={() => setTheme(darkMode ? "light" : "dark")}
          showChatOptions={false} onClose={() => setSettingsOpen(false)}
        />
      )}
      <Notice message={notice} onClose={closeNotice} />
    </div>
  );
}

export default AdminPage;
