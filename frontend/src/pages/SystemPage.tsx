import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type Dashboard,
  type Health,
  type PathMapping,
  type Settings,
  type SystemStatus,
} from "../api";

export type SystemSection = "status" | "rootfolders" | "logs";

type SystemPageProps = {
  section?: SystemSection;
};

const emptySettings = (): Settings => ({
  host: "0.0.0.0",
  port: 8199,
  data_dir: "",
  library_root: "",
  music_library_root: "",
  ytdlp_path: "yt-dlp",
  ffmpeg_path: "",
  default_quality: "best",
  default_music_quality: "best",
  format: "bv*+ba/b",
  music_format: "ba/b",
  output_template: "",
  music_output_template: "",
  poll_interval_minutes: 30,
  concurrent_downloads: 1,
  downloads_paused: false,
  nocheck_certificates: false,
  sponsorblock_remove: true,
  sponsorblock_categories_video: "sponsor,selfpromo,interaction,intro,outro",
  sponsorblock_categories_music:
    "music_offtopic,sponsor,selfpromo,interaction,intro,outro",
  path_mappings: [],
  api_key: "",
  api_auth_required: true,
  authentication_method: "forms",
  username: "",
  has_password: false,
});

export function SystemPage({ section = "status" }: SystemPageProps) {
  const [health, setHealth] = useState<Health | null>(null);
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [settings, setSettings] = useState<Settings>(emptySettings());
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [logText, setLogText] = useState("");
  const [logPath, setLogPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const [h, d, s, st] = await Promise.all([
      api.health(),
      api.dashboard(),
      api.settings(),
      api.systemStatus(),
    ]);
    setHealth(h);
    setDash(d);
    setSettings({ ...emptySettings(), ...s, path_mappings: s.path_mappings || [] });
    setSysStatus(st);
  };

  const loadLogs = async () => {
    const logs = await api.systemLogs();
    setLogText(logs.text);
    setLogPath(logs.path);
  };

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        if (section === "logs") {
          await loadLogs();
        } else {
          await load();
        }
        if (alive) setError(null);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      }
    };
    void tick();
    const id = window.setInterval(() => {
      if (section === "status" || section === "logs") void tick();
    }, section === "logs" ? 5000 : 8000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [section]);

  const issues: string[] = [];
  if (health && !health.ytdlp_ok) issues.push(health.ytdlp_error || "yt-dlp unavailable");
  if (health && !health.library_exists) issues.push("Library folder missing");
  if (settings.downloads_paused) issues.push("Downloads paused");

  const saveRoots = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await api.updateSettings({
        library_root: settings.library_root,
        music_library_root: settings.music_library_root,
        path_mappings: settings.path_mappings,
      });
      setSettings({ ...emptySettings(), ...saved, path_mappings: saved.path_mappings || [] });
      setMessage("Root folders and path mappings saved.");
      const h = await api.health();
      setHealth(h);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const setMapping = (index: number, key: keyof PathMapping, value: string) => {
    setSettings((prev) => {
      const next = [...(prev.path_mappings || [])];
      next[index] = { ...next[index], [key]: value };
      return { ...prev, path_mappings: next };
    });
  };

  const addMapping = () => {
    setSettings((prev) => ({
      ...prev,
      path_mappings: [...(prev.path_mappings || []), { host_path: "", plex_path: "" }],
    }));
  };

  const removeMapping = (index: number) => {
    setSettings((prev) => ({
      ...prev,
      path_mappings: (prev.path_mappings || []).filter((_, i) => i !== index),
    }));
  };

  if (section === "logs") {
    return (
      <>
        <div className="page-header">
          <div>
            <h1>Log</h1>
            <p>Application and tray events — copy and paste when reporting issues.</p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              className="btn"
              type="button"
              disabled={busy}
              onClick={() => {
                void (async () => {
                  setBusy(true);
                  try {
                    await loadLogs();
                    setMessage(null);
                  } catch (err) {
                    setError(err instanceof Error ? err.message : String(err));
                  } finally {
                    setBusy(false);
                  }
                })();
              }}
            >
              Refresh
            </button>
            <button
              className="btn"
              type="button"
              disabled={busy}
              onClick={() => {
                if (
                  !window.confirm(
                    "Clear the application and tray logs?\n\nThis only empties the log files — it does not change failed downloads.",
                  )
                ) {
                  return;
                }
                void (async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    await api.clearSystemLogs();
                    await loadLogs();
                    setMessage("Logs cleared.");
                  } catch (err) {
                    setError(err instanceof Error ? err.message : String(err));
                  } finally {
                    setBusy(false);
                  }
                })();
              }}
            >
              Clear log
            </button>
            <button
              className="btn btn-primary"
              type="button"
              disabled={!logText}
              onClick={() => {
                void (async () => {
                  try {
                    await navigator.clipboard.writeText(logText);
                    setMessage("Log copied to clipboard.");
                  } catch {
                    setError("Could not copy — select the log text and copy manually.");
                  }
                })();
              }}
            >
              Copy log
            </button>
          </div>
        </div>

        {error && <div className="error">{error}</div>}
        {message && <div className="success">{message}</div>}

        {logPath && (
          <p className="muted mono" style={{ marginBottom: "0.75rem" }}>
            {logPath}
          </p>
        )}

        <div className="panel">
          <pre
            className="mono"
            style={{
              margin: 0,
              maxHeight: "min(70vh, 640px)",
              overflow: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontSize: "0.8rem",
              lineHeight: 1.45,
            }}
          >
            {logText || "Loading…"}
          </pre>
        </div>
      </>
    );
  }

  if (section === "rootfolders") {
    return (
      <>
        <div className="page-header">
          <div>
            <h1>Root Folders</h1>
            <p>
              Where ytarr writes files — point these at the drive Plex reads (often a different
              disk than the app install).
            </p>
          </div>
        </div>

        {error && <div className="error">{error}</div>}
        {message && <div className="success">{message}</div>}

        <form className="panel" onSubmit={(e) => void saveRoots(e)}>
          <div className="field">
            <label htmlFor="library_root">Video library root</label>
            <input
              id="library_root"
              className="mono"
              value={settings.library_root}
              onChange={(e) => setSettings((p) => ({ ...p, library_root: e.target.value }))}
              placeholder="D:\Plex\YouTube"
            />
            <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
              Absolute path recommended on the Plex box (e.g.{" "}
              <span className="mono">E:\Media\YouTube</span>). Relative paths stay inside the app
              folder.
            </p>
          </div>
          <div className="field">
            <label htmlFor="music_library_root">Music library root</label>
            <input
              id="music_library_root"
              className="mono"
              value={settings.music_library_root}
              onChange={(e) => setSettings((p) => ({ ...p, music_library_root: e.target.value }))}
              placeholder="E:\Media\YouTubeMusic"
            />
          </div>

          <h3 style={{ marginTop: "1.25rem" }}>Remote path mappings</h3>
          <p className="muted" style={{ marginTop: 0 }}>
            Like Sonarr: map the path ytarr uses on this machine to the path Plex (or another host)
            sees. Example: host <span className="mono">D:\YouTube</span> → Plex{" "}
            <span className="mono">\\NAS\media\YouTube</span> or{" "}
            <span className="mono">/mnt/media/youtube</span>.
          </p>

          {(settings.path_mappings || []).map((m, i) => (
            <div className="row" key={i} style={{ marginBottom: "0.65rem", alignItems: "flex-end" }}>
              <div className="field grow" style={{ marginBottom: 0 }}>
                <label>Host path (ytarr)</label>
                <input
                  className="mono"
                  value={m.host_path}
                  onChange={(e) => setMapping(i, "host_path", e.target.value)}
                  placeholder="D:\YouTube"
                />
              </div>
              <div className="field grow" style={{ marginBottom: 0 }}>
                <label>Plex / remote path</label>
                <input
                  className="mono"
                  value={m.plex_path}
                  onChange={(e) => setMapping(i, "plex_path", e.target.value)}
                  placeholder="\\server\media\YouTube"
                />
              </div>
              <button className="btn btn-ghost" type="button" onClick={() => removeMapping(i)}>
                Remove
              </button>
            </div>
          ))}

          <div className="row" style={{ marginBottom: "1rem" }}>
            <button className="btn" type="button" onClick={addMapping}>
              Add mapping
            </button>
          </div>

          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save changes"}
          </button>
        </form>

        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Plex naming</h3>
          <p className="muted" style={{ marginBottom: "0.5rem" }}>
            Video (Personal Media / Local Assets):
          </p>
          <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: "0.8rem" }}>
            {`LibraryRoot/
  Channel Name/
    poster.jpg
    YYYY-MM-DD - Episode Title [youtubeId].ext`}
          </pre>
          <p className="muted" style={{ marginBottom: "0.5rem", marginTop: "0.75rem" }}>
            Music (organized automatically on download):
          </p>
          <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: "0.8rem" }}>
            {`MusicRoot/
  Artist Name/
    Track Title.ext`}
          </pre>
          <p className="muted" style={{ marginBottom: 0, marginTop: "0.75rem" }}>
            Music files get MusicBrainz tags embedded when a match is found (Plex reads tags, not
            bracket IDs in the name). YouTube ids stay in ytarr&apos;s database — and in a comment
            tag — so they do not confuse Plex agents. Video still uses{" "}
            <span className="mono">[youtubeId]</span> for uniqueness under Personal Media (that is
            not a TVDB id). Missing upload dates no longer become{" "}
            <span className="mono">0000-00-00</span>.
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Status</h1>
          <p>Health, paths, and download worker status.</p>
        </div>
        <Link className="btn" to="/system/rootfolders">
          Root Folders
        </Link>
      </div>

      {error && <div className="error">{error}</div>}

      {issues.length > 0 && (
        <div className="error">
          <strong>
            {issues.length} issue{issues.length === 1 ? "" : "s"}
          </strong>
          <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
            {issues.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        </div>
      )}

      {(dash?.failed ?? 0) > 0 && (
        <div className="panel" style={{ borderColor: "var(--danger, #c44)" }}>
          <h3 style={{ marginTop: 0 }}>Failed downloads</h3>
          <p className="muted">
            {dash?.failed} video{dash?.failed === 1 ? "" : "s"} failed (private, 403, etc.). This
            drives the red badge on System. Clear them to ignore permanently, or retry from Activity /
            Wanted.
          </p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Link className="btn" to="/wanted?status=failed">
              View failed
            </Link>
            <button
              className="btn btn-danger"
              type="button"
              disabled={busy}
              onClick={() => {
                if (
                  !window.confirm(
                    `Clear ${dash?.failed} failed video${dash?.failed === 1 ? "" : "s"}?\n\n` +
                      `They will be marked ignored and will not retry. The System badge will clear.`,
                  )
                ) {
                  return;
                }
                void (async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    const result = await api.clearFailedVideos();
                    await load();
                    setMessage(`Cleared ${result.cleared} failed video(s).`);
                  } catch (err) {
                    setError(err instanceof Error ? err.message : String(err));
                  } finally {
                    setBusy(false);
                  }
                })();
              }}
            >
              Clear failed
            </button>
          </div>
        </div>
      )}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>ytarr</h3>
        <p className="mono" style={{ marginBottom: 0 }}>
          Version {sysStatus?.version || "—"}
        </p>
      </div>

      <div className="stats">
        <div className="stat">
          <div className="stat-label">Status</div>
          <div className="stat-value" style={{ fontSize: "1.15rem" }}>
            {health?.status === "ok" && issues.length === 0 ? "Healthy" : "Attention"}
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Queue</div>
          <div className="stat-value">{dash?.queue_size ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Wanted</div>
          <div className="stat-value">{dash?.wanted ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Failed</div>
          <div className="stat-value">{dash?.failed ?? "—"}</div>
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>yt-dlp</h3>
        <p className={`mono ${health?.ytdlp_ok ? "muted" : ""}`} style={{ marginBottom: 0 }}>
          {health?.ytdlp_ok
            ? `OK — ${health.ytdlp_version || "unknown version"}`
            : health?.ytdlp_error || "Not available"}
        </p>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Library</h3>
        <p className="muted" style={{ marginBottom: "0.35rem" }}>
          Video root: <span className="mono">{health?.library_root || settings.library_root}</span>
          {health && !health.library_exists ? " (missing)" : ""}
        </p>
        {settings.music_library_root && (
          <p className="muted" style={{ marginBottom: "0.65rem" }}>
            Music root: <span className="mono">{settings.music_library_root}</span>
          </p>
        )}
        <Link className="btn" to="/system/rootfolders">
          Change paths / mappings
        </Link>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Downloads</h3>
        <p className="muted" style={{ marginBottom: 0 }}>
          {settings.downloads_paused ? "Paused" : "Running"}
          {` · ${settings.concurrent_downloads} concurrent · poll every ${settings.poll_interval_minutes}m`}
        </p>
      </div>
    </>
  );
}
