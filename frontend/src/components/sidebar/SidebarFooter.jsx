import { ClipboardCheck, FileCheck2, Settings, Moon, Store } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext.jsx";
import ProfilePicture from "./ProfilePicture";
import "../../styles/sidebar.css";

function SidebarFooter({
  darkMode, setDarkMode, onSettingsOpen, onProfileOpen,
  onRegisterBusiness, registerBusinessActive = false, onSubmissions, submissionsActive = false,
}) {
  const { user } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="sidebar-footer">
      <h3>Others</h3>

      {/* Admins only (is_superuser): the review page, until it moves to its own admin interface */}
      {user?.is_superuser && (
        <button
          className="footer-action-btn setting-footer-action"
          type="button"
          onClick={() => navigate("/admin/pipeline")}
        >
          <ClipboardCheck />
          <span>Review</span>
        </button>
      )}

      <button
        className={`footer-action-btn setting-footer-action register-business-action${registerBusinessActive ? " is-active" : ""}`}
        type="button"
        aria-current={registerBusinessActive ? "page" : undefined}
        onClick={onRegisterBusiness}
      >
        <Store />
        <span>Register Business</span>
      </button>

      <button
        className={`footer-action-btn setting-footer-action register-business-action${submissionsActive ? " is-active" : ""}`}
        type="button"
        aria-current={submissionsActive ? "page" : undefined}
        onClick={onSubmissions}
      >
        <FileCheck2 />
        <span>Submissions</span>
      </button>

      <button
        className="footer-action-btn setting-footer-action"
        type="button"
        aria-haspopup="dialog"
        onClick={onSettingsOpen}
      >
        <Settings />
        <span>Settings</span>
      </button>

      <div className="footer-action-btn theme-footer-action">
        <Moon />
        <span>Dark Mode</span>

        <label className="dark-toggle">
          <input
            type="checkbox"
            checked={darkMode}
            onChange={() => setDarkMode(!darkMode)}
          />
          <span className="dark-toggle-slider"></span>
        </label>
      </div>

      <button
        className="user-footer-card"
        type="button"
        title="Profile"
        aria-haspopup="dialog"
        onClick={onProfileOpen}
      >
        <ProfilePicture className="user-footer-card-profile" />
        <span>{user?.username}</span>
      </button>
    </div>
  );
}

export default SidebarFooter;
