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

export type SystemSection = "status" | "rootfolders" | "logs" | "tasks" | "backup" | "updates";

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
  plex_enabled: false,
  plex_url: "http://127.0.0.1:32400",
  plex_token: "",
  plex_video_section_id: "",
  plex_music_section_id: "",
  plex_refresh_debounce_seconds: 45,
  connect_webhook_url: "",
  connect_on_download: true,
  connect_on_failure: true,
  connect_on_grab: false,
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
  for (const w of health?.warnings || []) issues.push(w);

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
            Video (Home Videos / Local Assets):
          </p>
          <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: "0.8rem" }}>
            {`LibraryRoot/
  Channel Name/
    poster.jpg
    Season 01/
      Channel Name - S01E01 - Episode Title [youtubeId].ext
      Channel Name - S01E01 - Episode Title [youtubeId].nfo`}
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
            Nested playlists become Season 02+ under the same channel folder. Music files get
            MusicBrainz tags embedded when a match is found. YouTube ids stay in ytarr&apos;s
            database — and in video filenames as{" "}
            <span className="mono">[youtubeId]</span> for uniqueness under Home Videos (that is
            not a TVDB id). Missing upload dates no longer become{" "}
            <span className="mono">0000-00-00</span>.
          </p>
        </div>
      </>
    );
  }

  if (section === "tasks") {
    return <SystemTasksPanel />;
  }
  if (section === "backup") {
    return <SystemBackupPanel />;
  }
  if (section === "updates") {
    return <SystemUpdatesPanel />;
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

function SystemTasksPanel() {
  const [tasks, setTasks] = useState<
    { id: string; name: string; next_run_time: string | null; trigger: string }[]
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = async () => {
    const res = await api.systemTasks();
    setTasks(res.tasks);
  };

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : String(err)));
    const id = window.setInterval(() => void load().catch(() => undefined), 15000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Tasks</h1>
          <p>Scheduled jobs — monitor, downloads, yt-dlp/ffmpeg update.</p>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}
      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>Task</th>
              <th>Trigger</th>
              <th>Next run</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td className="mono muted">{t.trigger}</td>
                <td className="mono muted">
                  {t.next_run_time ? new Date(t.next_run_time).toLocaleString() : "—"}
                </td>
                <td>
                  <button
                    className="btn"
                    type="button"
                    disabled={busyId === t.id}
                    onClick={() => {
                      setBusyId(t.id);
                      setMessage(null);
                      void api
                        .runSystemTask(t.id)
                        .then(() => {
                          setMessage(`Ran ${t.name}.`);
                          return load();
                        })
                        .catch((err) =>
                          setError(err instanceof Error ? err.message : String(err)),
                        )
                        .finally(() => setBusyId(null));
                    }}
                  >
                    Run
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SystemBackupPanel() {
  const [backups, setBackups] = useState<
    { name: string; path: string; size: number; mtime: string }[]
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const res = await api.listBackups();
    setBackups(res.backups);
  };

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Backup</h1>
          <p>Zip config.yaml + database under data/backups (Arr-style).</p>
        </div>
        <button
          className="btn btn-primary"
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError(null);
            void api
              .createBackup()
              .then((r) => {
                setMessage(`Created ${r.name} (${Math.round(r.size / 1024)} KB).`);
                return load();
              })
              .catch((err) => setError(err instanceof Error ? err.message : String(err)))
              .finally(() => setBusy(false));
          }}
        >
          Backup now
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}
      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Size</th>
              <th>When</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {backups.map((b) => (
              <tr key={b.name}>
                <td className="mono">{b.name}</td>
                <td>{Math.round(b.size / 1024)} KB</td>
                <td className="mono muted">{new Date(b.mtime).toLocaleString()}</td>
                <td>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      if (
                        !window.confirm(
                          `Restore ${b.name}? This overwrites config/DB — restart ytarr after.`,
                        )
                      ) {
                        return;
                      }
                      setBusy(true);
                      void api
                        .restoreBackup(b.name)
                        .then((r) =>
                          setMessage(
                            `Restored ${r.restored.join(", ")}. Restart ytarr to apply.`,
                          ),
                        )
                        .catch((err) =>
                          setError(err instanceof Error ? err.message : String(err)),
                        )
                        .finally(() => setBusy(false));
                    }}
                  >
                    Restore
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!backups.length && <p className="muted">No backups yet.</p>}
      </div>
    </>
  );
}

function SystemUpdatesPanel() {
  const [info, setInfo] = useState<{
    app_version: string;
    ytdlp_ok: boolean;
    ytdlp_version: string | null;
    ytdlp_error: string | null;
    note?: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setInfo(await api.systemUpdates());
  };

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Updates</h1>
          <p>App and yt-dlp / ffmpeg tooling.</p>
        </div>
        <button
          className="btn btn-primary"
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError(null);
            void api
              .triggerYtdlpUpdate()
              .then((r) => {
                setMessage(`Update: ${JSON.stringify(r)}`);
                return load();
              })
              .catch((err) => setError(err instanceof Error ? err.message : String(err)))
              .finally(() => setBusy(false));
          }}
        >
          Run yt-dlp / ffmpeg update
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}
      <div className="panel">
        <p>
          ytarr version: <span className="mono">{info?.app_version || "—"}</span>
        </p>
        <p>
          yt-dlp:{" "}
          <span className="mono">
            {info?.ytdlp_ok ? info.ytdlp_version || "OK" : info?.ytdlp_error || "—"}
          </span>
        </p>
        <p className="muted">{info?.note}</p>
      </div>
    </>
  );
}
