import {
  PanelLeft,
  SquarePen,
  Search,
  Settings,
} from "lucide-react";
import "../../styles/sidebar.css";
import { mockUser } from "../../../data/mockUser";
import defaultProfile from "../../assets/defaultProfile.jpg";

function ClosedSidebar({
  onOpenSidebar,
  onNewChat,
  onSearchOpen,
}) {
  const profileImage = mockUser.profileImage || defaultProfile;

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

        <button
          className="closed-sidebar-icon-btn"
          type="button"
          title="Settings"
        >
          <Settings />
        </button>
      </div>

      <button className="closed-sidebar-user" type="button" title="Profile">
        <img
          className="user-footer-card-profile"
          src={profileImage}
          alt="Profile"
        />
      </button>
    </aside>
  );
}

export default ClosedSidebar;
