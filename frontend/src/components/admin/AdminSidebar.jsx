import { NavLink } from "react-router-dom";
import { FileCheck2, LayoutGrid, Moon, PanelLeft, Settings } from "lucide-react";
import { useAuth } from "../../context/AuthContext.jsx";
import ProfilePicture from "../sidebar/ProfilePicture";
import { PIPELINE_PAGES, pipelinePath, waitingCount } from "./pipelinePages.js";
import Logo from "../../assets/logo.svg";
import DarkModeLogo from "../../assets/logo-dark.svg";
import "../../styles/sidebar.css";

// Business submissions, with how many wait for a review (waiting or under review)
const reviewNav = (submissionsWaiting) => [
  { to: "/admin", end: true, label: "Overview", Icon: LayoutGrid },
  { to: "/admin/submissions", end: false, label: "Submissions", Icon: FileCheck2, count: submissionsWaiting },
];

// The pipeline review pages, with how many wait for a decision
const pipelineNav = (overview) => PIPELINE_PAGES.map((page) => ({
  to: pipelinePath(page.id), end: true, label: page.label, Icon: page.Icon, count: waitingCount(page, overview),
}));

const navClass = (base) => ({ isActive }) => `${base}${isActive ? " is-active" : ""}`;

function NavGroup({ title, items }) {
  return (
    <nav className="admin-nav" aria-label={title}>
      <h3>{title}</h3>
      {items.map(({ to, end, label, Icon, count }) => (
        <NavLink key={to} to={to} end={end} className={navClass("footer-action-btn setting-footer-action admin-nav-link")}>
          <Icon />
          <span>{label}</span>
          {count > 0 && <span className="admin-nav-count" aria-label={`${count} waiting for a decision`}>{count}</span>}
        </NavLink>
      ))}
    </nav>
  );
}

export function AdminSidebar({ darkMode, setDarkMode, overview, submissionsWaiting = 0, onClose, onSettingsOpen, onProfileOpen }) {
  const { user } = useAuth();

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

      <div className="admin-nav-groups">
        <NavGroup title="Review" items={reviewNav(submissionsWaiting)} />
        <NavGroup title="Pipeline" items={pipelineNav(overview)} />
      </div>

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
        <button className="user-footer-card" type="button" title="Profile" aria-haspopup="dialog" onClick={onProfileOpen}>
          <ProfilePicture className="user-footer-card-profile" />
          <span>{user?.username}</span>
        </button>
      </div>
    </aside>
  );
}

function ClosedNavIcons({ items }) {
  return items.map(({ to, end, label, Icon, count }) => {
    const title = count > 0 ? `${label} (${count} waiting)` : label;
    return (
      <NavLink key={to} to={to} end={end} title={title} aria-label={title} className={navClass("closed-sidebar-icon-btn")}>
        <Icon />
        {count > 0 && <span className="admin-nav-dot" aria-hidden="true" />}
      </NavLink>
    );
  });
}

export function AdminClosedSidebar({ overview, submissionsWaiting = 0, onOpen, onSettingsOpen, onProfileOpen }) {
  return (
    <aside className="closed-sidebar admin-closed-sidebar">
      <div className="closed-sidebar-top">
        <button className="closed-sidebar-icon-btn" type="button" onClick={onOpen} title="Open Sidebar" aria-label="Open sidebar">
          <PanelLeft />
        </button>
        <ClosedNavIcons items={reviewNav(submissionsWaiting)} />
        <span className="admin-closed-divider" aria-hidden="true" />
        <ClosedNavIcons items={pipelineNav(overview)} />
        <span className="admin-closed-divider" aria-hidden="true" />
        <button className="closed-sidebar-icon-btn" type="button" title="Settings" aria-label="Settings" aria-haspopup="dialog" onClick={onSettingsOpen}>
          <Settings />
        </button>
      </div>
      <button className="closed-sidebar-user" type="button" title="Profile" aria-label="Profile" aria-haspopup="dialog" onClick={onProfileOpen}>
        <ProfilePicture className="user-footer-card-profile" />
      </button>
    </aside>
  );
}
