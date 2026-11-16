import { NavLink } from "react-router-dom";
import { FileCheck2, LayoutGrid, Moon, PanelLeft, Settings } from "lucide-react";
import { mockUser } from "../../../data/mockUser";
import Logo from "../../assets/foodsightLogo.png";
import DarkModeLogo from "../../assets/foodsightLogoDarkMode.png";
import defaultProfile from "../../assets/defaultProfile.jpg";
import "../../styles/sidebar.css";

const NAV = [
  { to: "/admin", end: true, label: "Overview", Icon: LayoutGrid },
  { to: "/admin/submissions", end: false, label: "Submissions", Icon: FileCheck2 },
];

const navClass = (base) => ({ isActive }) => `${base}${isActive ? " is-active" : ""}`;

export function AdminSidebar({ darkMode, setDarkMode, onClose, onSettingsOpen }) {
  return (
    <aside className="sidebar admin-sidebar">
      <div className="sidebar-header">
        <div className="admin-brand">
          <img src={darkMode ? DarkModeLogo : Logo} alt="FoodSight" className="sidebar-logo" />
          <span className="admin-badge">ADMIN</span>
        </div>
        <button className="close-sidebar-btn" type="button" onClick={onClose} aria-label="Close sidebar">
          <PanelLeft />
        </button>
      </div>

      <nav className="admin-nav" aria-label="Admin">
        <h3>Review</h3>
        {NAV.map(({ to, end, label, Icon }) => (
          <NavLink key={to} to={to} end={end} className={navClass("footer-action-btn setting-footer-action admin-nav-link")}>
            <Icon />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <h3>Others</h3>
        <button className="footer-action-btn setting-footer-action" type="button" aria-haspopup="dialog" onClick={onSettingsOpen}>
          <Settings />
          <span>Settings</span>
        </button>
        <div className="footer-action-btn theme-footer-action">
          <Moon />
          <span>Dark Mode</span>
          <label className="dark-toggle">
            <input type="checkbox" checked={darkMode} onChange={() => setDarkMode(!darkMode)} aria-label="Dark mode" />
            <span className="dark-toggle-slider"></span>
          </label>
        </div>
        <button className="user-footer-card" type="button">
          <img className="user-footer-card-profile" src={mockUser.profileImage || defaultProfile} alt="" />
          <span>{mockUser.username}</span>
        </button>
      </div>
    </aside>
  );
}

export function AdminClosedSidebar({ onOpen, onSettingsOpen }) {
  return (
    <aside className="closed-sidebar">
      <div className="closed-sidebar-top">
        <button className="closed-sidebar-icon-btn" type="button" onClick={onOpen} title="Open Sidebar" aria-label="Open sidebar">
          <PanelLeft />
        </button>
        {NAV.map(({ to, end, label, Icon }) => (
          <NavLink key={to} to={to} end={end} title={label} aria-label={label} className={navClass("closed-sidebar-icon-btn")}>
            <Icon />
          </NavLink>
        ))}
        <button className="closed-sidebar-icon-btn" type="button" title="Settings" aria-label="Settings" aria-haspopup="dialog" onClick={onSettingsOpen}>
          <Settings />
        </button>
      </div>
      <button className="closed-sidebar-user" type="button" title="Profile">
        <img className="user-footer-card-profile" src={mockUser.profileImage || defaultProfile} alt="Profile" />
      </button>
    </aside>
  );
}
