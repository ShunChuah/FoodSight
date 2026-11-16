import { useCallback, useState } from "react";
import { Outlet } from "react-router-dom";
import { AdminClosedSidebar, AdminSidebar } from "../components/admin/AdminSidebar";
import Notice from "../components/Notice";
import ChangePassword from "../components/modals/ChangePassword";
import Profile from "../components/modals/Profile";
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
  // The open account dialog, as on the chat dashboard: "settings", "profile", "password" or null.
  const [openDialog, setOpenDialog] = useState(null);
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
          onClose={() => setSidebarOpen(false)} onSettingsOpen={() => setOpenDialog("settings")}
          onProfileOpen={() => setOpenDialog("profile")}
        />
      ) : (
        <AdminClosedSidebar
          onOpen={() => setSidebarOpen(true)} onSettingsOpen={() => setOpenDialog("settings")}
          onProfileOpen={() => setOpenDialog("profile")}
        />
      )}
      <main className="admin-main">
        <Outlet context={{ submissions, updateSubmission, setNotice, darkMode }} />
      </main>
      {openDialog === "settings" && (
        <Settings
          darkMode={darkMode} onToggleDarkMode={() => setTheme(darkMode ? "light" : "dark")}
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
