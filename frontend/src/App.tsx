import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { SourcesPage } from "./pages/SourcesPage";
import { LibraryPage } from "./pages/LibraryPage";
import { ActivityPage } from "./pages/ActivityPage";
import { SettingsPage } from "./pages/SettingsPage";
import { RenamePage } from "./pages/RenamePage";
import { AddNewPage } from "./pages/AddNewPage";
import { ChannelDetailPage } from "./pages/ChannelDetailPage";
import {
  BrandMark,
  IconActivity,
  IconAdd,
  IconDashboard,
  IconLibrary,
  IconRename,
  IconSettings,
  IconSources,
} from "./icons";

const NAV = [
  { to: "/", label: "Library", end: true as boolean | undefined, Icon: IconDashboard },
  { to: "/add", label: "Add New", end: undefined, Icon: IconAdd },
  { to: "/sources", label: "Sources", end: undefined, Icon: IconSources },
  { to: "/library", label: "Videos", end: undefined, Icon: IconLibrary },
  { to: "/rename", label: "Rename", end: undefined, Icon: IconRename },
  { to: "/activity", label: "Activity", end: undefined, Icon: IconActivity },
  { to: "/settings", label: "Settings", end: undefined, Icon: IconSettings },
];

export default function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <BrandMark size={40} />
          <div className="brand-text">
            <div className="brand-name">ytarr</div>
            <div className="brand-sub">YouTube Arr</div>
          </div>
        </div>
        <nav className="nav">
          {NAV.map(({ to, label, Icon, end }) => (
            <NavLink key={to} to={to} end={end}>
              <span className="nav-icon">
                <Icon />
              </span>
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/channel/:sourceId" element={<ChannelDetailPage />} />
          <Route path="/add" element={<AddNewPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/rename" element={<RenamePage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/queue" element={<Navigate to="/activity" replace />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
