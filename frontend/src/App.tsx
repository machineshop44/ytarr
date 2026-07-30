import { type FormEvent, useEffect, useState } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { SourcesPage } from "./pages/SourcesPage";
import { LibraryPage } from "./pages/LibraryPage";
import { ActivityPage } from "./pages/ActivityPage";
import { SettingsPage } from "./pages/SettingsPage";
import { AddNewPage } from "./pages/AddNewPage";
import { ChannelDetailPage } from "./pages/ChannelDetailPage";
import { SystemPage } from "./pages/SystemPage";
import { DiscoverPage } from "./pages/DiscoverPage";
import { LoginPage } from "./pages/LoginPage";
import { api, clearApiKey, type Dashboard } from "./api";
import {
  BrandMark,
  IconActivity,
  IconAdd,
  IconDashboard,
  IconDiscover,
  IconSettings,
  IconSources,
  IconSystem,
  IconWanted,
} from "./icons";

function navClass({ isActive }: { isActive: boolean }) {
  return isActive ? "active" : undefined;
}

function childClass({ isActive }: { isActive: boolean }) {
  return `nav-child${isActive ? " active" : ""}`;
}

export default function App() {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [search, setSearch] = useState("");
  const [authChecking, setAuthChecking] = useState(true);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [authUser, setAuthUser] = useState<string | null>(null);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const status = await api.authStatus();
        if (!alive) return;
        if (status.forms_required && !status.authenticated) {
          setNeedsLogin(true);
          setAuthUser(null);
        } else {
          setNeedsLogin(false);
          setAuthUser(status.username);
        }
      } catch {
        if (alive) setNeedsLogin(false);
      } finally {
        if (alive) setAuthChecking(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (needsLogin || authChecking) return;
    let alive = true;
    const load = async () => {
      try {
        const d = await api.dashboard();
        if (alive) setDash(d);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        if (/unauthorized/i.test(msg)) {
          setNeedsLogin(true);
          setAuthUser(null);
        }
      }
    };
    void load();
    const id = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [needsLogin, authChecking]);

  const queueBadge = dash && dash.queue_size > 0 ? dash.queue_size : null;
  const wantedBadge = dash && dash.wanted > 0 ? dash.wanted : null;
  const systemBadge =
    dash && (!dash.ytdlp_ok || dash.failed > 0)
      ? Math.max(1, (dash.ytdlp_ok ? 0 : 1) + (dash.failed > 0 ? 1 : 0))
      : null;

  const path = location.pathname;
  const libraryOpen =
    path === "/" || path.startsWith("/add") || path.startsWith("/sources") || path.startsWith("/channel");
  const discoverOpen = path.startsWith("/discover");
  const activityOpen = path.startsWith("/activity");
  const wantedOpen = path.startsWith("/wanted");
  const settingsOpen = path.startsWith("/settings");
  const systemOpen = path.startsWith("/system");

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    const q = search.trim();
    if (!q) {
      navigate("/add");
      return;
    }
    const kind = /\s[-–—:]\s/.test(q) ? "video" : "channel";
    navigate(`/add?q=${encodeURIComponent(q)}&kind=${kind}`);
  };

  const onLogout = async () => {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    clearApiKey();
    setNeedsLogin(true);
    setAuthUser(null);
    setDash(null);
  };

  if (authChecking) {
    return (
      <div className="login-shell">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  if (needsLogin) {
    return (
      <LoginPage
        onLoggedIn={(username) => {
          setAuthUser(username);
          setNeedsLogin(false);
        }}
      />
    );
  }

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
          <NavLink to="/" end className={navClass}>
            <span className="nav-icon">
              <IconDashboard />
            </span>
            <span>Library</span>
          </NavLink>
          {libraryOpen && (
            <>
              <NavLink to="/add" className={childClass}>
                <span className="nav-icon">
                  <IconAdd />
                </span>
                <span>Add New</span>
              </NavLink>
              <NavLink to="/sources" className={childClass}>
                <span className="nav-icon">
                  <IconSources />
                </span>
                <span>Library Import</span>
              </NavLink>
            </>
          )}

          <NavLink to="/discover" className={navClass}>
            <span className="nav-icon">
              <IconDiscover />
            </span>
            <span>Discover</span>
          </NavLink>
          {discoverOpen && (
            <NavLink to="/discover" end className={childClass}>
              <span>Similar</span>
            </NavLink>
          )}

          <NavLink to="/activity/queue" className={() => (activityOpen ? "active" : undefined)}>
            <span className="nav-icon">
              <IconActivity />
            </span>
            <span>Activity</span>
            {queueBadge != null && <span className="nav-badge nav-badge-info">{queueBadge}</span>}
          </NavLink>
          {activityOpen && (
            <>
              <NavLink to="/activity/queue" className={childClass}>
                <span>Queue</span>
              </NavLink>
              <NavLink to="/activity/history" className={childClass}>
                <span>History</span>
              </NavLink>
            </>
          )}

          <NavLink to="/wanted" className={navClass}>
            <span className="nav-icon">
              <IconWanted />
            </span>
            <span>Wanted</span>
            {wantedBadge != null && <span className="nav-badge">{wantedBadge}</span>}
          </NavLink>
          {wantedOpen && (
            <NavLink to="/wanted" end className={childClass}>
              <span>Missing</span>
            </NavLink>
          )}

          <NavLink to="/settings/mediamanagement" className={() => (settingsOpen ? "active" : undefined)}>
            <span className="nav-icon">
              <IconSettings />
            </span>
            <span>Settings</span>
          </NavLink>
          {settingsOpen && (
            <>
              <NavLink to="/settings/mediamanagement" className={childClass}>
                <span>Media Management</span>
              </NavLink>
              <NavLink to="/settings/quality" className={childClass}>
                <span>Quality</span>
              </NavLink>
              <NavLink to="/settings/downloadclients" className={childClass}>
                <span>Download Clients</span>
              </NavLink>
              <NavLink to="/settings/general" className={childClass}>
                <span>General</span>
              </NavLink>
            </>
          )}

          <NavLink to="/system" className={() => (systemOpen ? "active" : undefined)}>
            <span className="nav-icon">
              <IconSystem />
            </span>
            <span>System</span>
            {systemBadge != null && (
              <span className="nav-badge nav-badge-danger">{systemBadge}</span>
            )}
          </NavLink>
          {systemOpen && (
            <>
              <NavLink to="/system" end className={childClass}>
                <span>Status</span>
                {systemBadge != null && (
                  <span className="nav-badge nav-badge-danger">{systemBadge}</span>
                )}
              </NavLink>
              <NavLink to="/system/rootfolders" className={childClass}>
                <span>Root Folders</span>
              </NavLink>
            </>
          )}
        </nav>
        <div className="sidebar-footer">
          {authUser && <div className="muted sidebar-user">{authUser}</div>}
          <button className="btn btn-ghost" type="button" onClick={() => void onLogout()}>
            Log out
          </button>
        </div>
      </aside>

      <div className="app-body">
        <header className="topbar">
          <form className="topbar-search" onSubmit={onSearch}>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search channel or Artist - Song"
              aria-label="Search YouTube to add"
            />
          </form>
        </header>
        <main className="main">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/channel/:sourceId" element={<ChannelDetailPage />} />
            <Route path="/add" element={<AddNewPage />} />
            <Route path="/discover" element={<DiscoverPage />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="/rename" element={<Navigate to="/" replace />} />
            <Route path="/wanted" element={<LibraryPage defaultStatus="wanted" />} />
            <Route path="/library" element={<Navigate to="/wanted" replace />} />
            <Route path="/activity" element={<Navigate to="/activity/queue" replace />} />
            <Route path="/activity/queue" element={<ActivityPage tab="queue" />} />
            <Route path="/activity/history" element={<ActivityPage tab="history" />} />
            <Route path="/queue" element={<Navigate to="/activity/queue" replace />} />
            <Route path="/settings" element={<Navigate to="/settings/mediamanagement" replace />} />
            <Route
              path="/settings/mediamanagement"
              element={<SettingsPage section="mediamanagement" />}
            />
            <Route path="/settings/quality" element={<SettingsPage section="quality" />} />
            <Route
              path="/settings/downloadclients"
              element={<SettingsPage section="downloadclients" />}
            />
            <Route path="/settings/general" element={<SettingsPage section="general" />} />
            <Route path="/system" element={<SystemPage section="status" />} />
            <Route path="/system/rootfolders" element={<SystemPage section="rootfolders" />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
