import {
  ClipboardCheck,
  PanelLeft,
  SquarePen,
  Search,
  Settings,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext.jsx";
import "../../styles/sidebar.css";
import ProfilePicture from "./ProfilePicture";

function ClosedSidebar({
  onOpenSidebar,
  onNewChat,
  onSearchOpen,
  onSettingsOpen,
  onProfileOpen,
}) {
  const { user } = useAuth();
  const navigate = useNavigate();

  return (
    <aside className="closed-sidebar">
      <div className="closed-sidebar-top">
        <button
          className="closed-sidebar-icon-btn"
          type="button"
          onClick={onOpenSidebar}
          title="Open Sidebar"
        >
          <PanelLeft />
        </button>

        <button
          className="closed-sidebar-icon-btn"
          type="button"
          title="New Chat"
          onClick={onNewChat}
        >
          <SquarePen />
        </button>

        <button
          className="closed-sidebar-icon-btn"
          type="button"
          title="Search Chats"
          onClick={onSearchOpen}
        >
          <Search />
        </button>

        {user?.is_superuser && (
          <button
            className="closed-sidebar-icon-btn"
            type="button"
            title="Review"
            aria-label="Review"
            onClick={() => navigate("/admin")}
          >
            <ClipboardCheck />
          </button>
        )}

        <button
          className="closed-sidebar-icon-btn"
          type="button"
          title="Settings"
          aria-label="Settings"
          aria-haspopup="dialog"
          onClick={onSettingsOpen}
        >
          <Settings />
        </button>
      </div>

      <button
        className="closed-sidebar-user"
        type="button"
        title="Profile"
        aria-label="Profile"
        aria-haspopup="dialog"
        onClick={onProfileOpen}
      >
        <ProfilePicture className="user-footer-card-profile" />
      </button>
    </aside>
  );
}

export default ClosedSidebar;
