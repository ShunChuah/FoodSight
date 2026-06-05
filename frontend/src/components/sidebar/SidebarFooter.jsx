import { Settings, Moon } from "lucide-react";
import { mockUser } from "../../../data/mockUser";
import defaultProfile from "../../assets/defaultProfile.jpg";
import "../../styles/sidebar.css";

function SidebarFooter({ darkMode, setDarkMode }) {
  const profileImage = mockUser.profileImage || defaultProfile;

  return (
    <div className="sidebar-footer">
      <h3>Others</h3>

      <div className="footer-action-btn setting-footer-action">
        <Settings />
        <span>Settings</span>
      </div>

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

      <button className="user-footer-card" type="button">
        <img
          className="user-footer-card-profile"
          src={profileImage}
          alt="Profile"
        />
        <span>{mockUser.username}</span>
      </button>
    </div>
  );
}

export default SidebarFooter;
