import { type ChangeEvent, type FormEvent, useEffect, useState } from "react";
import { api, setApiKey, type Settings } from "../api";
import { DEFAULT_QUALITY_OPTIONS } from "../qualityOptions";

const empty: Settings = {
  host: "127.0.0.1",
  port: 8199,
  data_dir: "",
  library_root: "",
  music_library_root: "",
  ytdlp_path: "yt-dlp",
  ffmpeg_path: "",
  default_quality: "best",
  format: "bv*+ba/b",
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
};

export type SettingsSection = "mediamanagement" | "quality" | "downloadclients" | "general";

const SECTION_TITLES: Record<SettingsSection, { title: string; blurb: string }> = {
  mediamanagement: {
    title: "Media Management",
    blurb: "Library folders and naming templates — Sonarr/Lidarr Media Management for YouTube.",
  },
  quality: {
    title: "Quality",
    blurb: "Default resolution / format profile applied to new channels.",
  },
  downloadclients: {
    title: "Download Clients",
    blurb: "Built-in yt-dlp client (no SABnzbd/qBittorrent) — paths and concurrency.",
  },
  general: {
    title: "General",
    blurb: "Host, API key for mobile hubs, poll interval, and network options.",
  },
};

type SettingsPageProps = {
  section?: SettingsSection;
};

export function SettingsPage({ section = "mediamanagement" }: SettingsPageProps) {
  const [form, setForm] = useState<Settings>(empty);
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const meta = SECTION_TITLES[section];

  useEffect(() => {
    void api
      .settings()
      .then((s) => {
        setForm(s);
        if (s.api_key) setApiKey(s.api_key);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const onRegenerateKey = async () => {
    if (
      !window.confirm(
        "Generate a new API key? Mobile hubs using the old key will stop working until you update them.",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await api.regenerateApiKey();
      setForm(saved);
      setApiKey(saved.api_key);
      setMessage("New API key generated — update your mobile hub.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onCopyKey = async () => {
    try {
      await navigator.clipboard.writeText(form.api_key || "");
      setMessage("API key copied.");
    } catch {
      setError("Could not copy — select the key and copy manually.");
    }
  };
  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const payload: Partial<Settings> & { password?: string } = { ...form };
      if (newPassword.trim()) payload.password = newPassword.trim();
      const saved = await api.updateSettings(payload);
      setForm(saved);
      setNewPassword("");
      if (saved.api_key) setApiKey(saved.api_key);
      setMessage("Settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const set =
    (key: keyof Settings) =>
    (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
      const value = e.target.value;
      setForm((prev) => ({
        ...prev,
        [key]:
          key === "port" || key === "poll_interval_minutes" || key === "concurrent_downloads"
            ? Number(value)
            : value,
      }));
    };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{meta.title}</h1>
          <p>{meta.blurb}</p>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      <form className="panel" onSubmit={onSubmit}>
        {section === "mediamanagement" && (
          <>
            <div className="field">
              <label htmlFor="library_root">Video library root</label>
              <input id="library_root" value={form.library_root} onChange={set("library_root")} />
            </div>
            <div className="field">
              <label htmlFor="music_library_root">Music library root</label>
              <input
                id="music_library_root"
                value={form.music_library_root}
                onChange={set("music_library_root")}
                placeholder="music"
              />
              <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
                Used when Media type is <strong>Music (audio)</strong> — extracts audio (m4a).
              </p>
            </div>
            <div className="field">
              <label htmlFor="output_template">Video output template</label>
              <textarea
                id="output_template"
                rows={3}
                value={form.output_template}
                onChange={set("output_template")}
              />
            </div>
            <div className="field">
              <label htmlFor="music_output_template">Music output template</label>
              <textarea
                id="music_output_template"
                rows={2}
                value={form.music_output_template}
                onChange={set("music_output_template")}
              />
            </div>
            <div className="panel" style={{ margin: "0 0 1rem", background: "var(--bg)" }}>
              <h3 style={{ marginTop: 0 }}>Plex tip</h3>
              <p className="muted" style={{ marginBottom: "0.5rem" }}>
                Point a separate Plex library at your video library root. Use Local Media Assets /
                Personal Media so each channel folder uses <span className="mono">poster.jpg</span>.
                Keep YouTube out of Sonarr and your main TV library.
              </p>
              <p className="muted" style={{ marginBottom: 0 }}>
                Video series use date-based files:{" "}
                <span className="mono">Channel/YYYY-MM-DD - Title [youtubeId].ext</span>. Music uses{" "}
                <span className="mono">Artist/Title.ext</span> with MusicBrainz tags embedded on
                download (no YouTube id in the filename). Change the disk under{" "}
                <strong>System → Root Folders</strong> if the library lives on another drive.
              </p>
            </div>
          </>
        )}

        {section === "quality" && (
          <>
            <div className="field">
              <label htmlFor="default_quality">Default quality</label>
              <select
                id="default_quality"
                value={form.default_quality || "best"}
                onChange={set("default_quality")}
              >
                {DEFAULT_QUALITY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            {(form.default_quality || "best") === "custom" && (
              <div className="field">
                <label htmlFor="format">Custom format selector</label>
                <input id="format" value={form.format} onChange={set("format")} />
                <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
                  yt-dlp <span className="mono">-f</span> string when Default quality is Custom.
                </p>
              </div>
            )}
          </>
        )}

        {section === "downloadclients" && (
          <>
            <div className="field">
              <label htmlFor="ytdlp_path">yt-dlp path</label>
              <input
                id="ytdlp_path"
                value={form.ytdlp_path}
                onChange={set("ytdlp_path")}
                placeholder="yt-dlp"
              />
              <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
                Leave as <span className="mono">yt-dlp</span> to use the bundled Python module.
              </p>
            </div>
            <div className="field">
              <label htmlFor="ffmpeg_path">ffmpeg path</label>
              <input
                id="ffmpeg_path"
                value={form.ffmpeg_path || ""}
                onChange={set("ffmpeg_path")}
                placeholder="tools/ffmpeg/ffmpeg.exe (bundled)"
              />
            </div>
            <div className="field grow">
              <label htmlFor="concurrent">Concurrent downloads</label>
              <input
                id="concurrent"
                type="number"
                min={1}
                max={4}
                value={form.concurrent_downloads}
                onChange={set("concurrent_downloads")}
              />
            </div>

            <h3 style={{ marginTop: "1.25rem" }}>SponsorBlock</h3>
            <p className="muted" style={{ marginTop: 0 }}>
              Cuts community-marked ads, intros, and non-music talk from the file (needs ffmpeg).
              Unmarked videos download unchanged.
            </p>
            <label className="mode-option" style={{ marginBottom: "1rem" }}>
              <input
                type="checkbox"
                checked={form.sponsorblock_remove}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, sponsorblock_remove: e.target.checked }))
                }
              />
              <span>
                <strong>Remove SponsorBlock segments</strong>
                <small>Applies to both Video and Music downloads.</small>
              </span>
            </label>
            {form.sponsorblock_remove && (
              <>
                <div className="field">
                  <label htmlFor="sb_video">Video categories</label>
                  <input
                    id="sb_video"
                    className="mono"
                    value={form.sponsorblock_categories_video}
                    onChange={set("sponsorblock_categories_video")}
                  />
                </div>
                <div className="field">
                  <label htmlFor="sb_music">Music categories</label>
                  <input
                    id="sb_music"
                    className="mono"
                    value={form.sponsorblock_categories_music}
                    onChange={set("sponsorblock_categories_music")}
                  />
                  <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
                    <span className="mono">music_offtopic</span> targets talking / theme around the
                    track. Others: sponsor, intro, outro, selfpromo, interaction, preview, filler.
                  </p>
                </div>
              </>
            )}
          </>
        )}

        {section === "general" && (
          <>
            <div className="panel" style={{ margin: "0 0 1rem", background: "var(--bg)" }}>
              <h3 style={{ marginTop: 0 }}>Security — Authentication</h3>
              <p className="muted" style={{ marginTop: 0 }}>
                Forms login for the web UI (like Sonarr). Mobile hubs still use the API key below.
              </p>
              <div className="field">
                <label htmlFor="auth_method">Authentication</label>
                <select
                  id="auth_method"
                  value={form.authentication_method}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      authentication_method: e.target.value as "none" | "forms",
                    }))
                  }
                >
                  <option value="forms">Forms (username / password)</option>
                  <option value="none">None (API key only)</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="auth_user">Username</label>
                <input
                  id="auth_user"
                  value={form.username}
                  onChange={(e) => setForm((prev) => ({ ...prev, username: e.target.value }))}
                  autoComplete="username"
                />
              </div>
              <div className="field">
                <label htmlFor="auth_pass">
                  Password {form.has_password ? "(leave blank to keep current)" : ""}
                </label>
                <input
                  id="auth_pass"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoComplete="new-password"
                  placeholder={form.has_password ? "••••••••" : "Set a password"}
                />
              </div>
            </div>

            <div className="panel" style={{ margin: "0 0 1rem", background: "var(--bg)" }}>
              <h3 style={{ marginTop: 0 }}>Security — API Key</h3>
              <p className="muted" style={{ marginTop: 0 }}>
                Same idea as Sonarr/Radarr. Paste this into your mobile Arrs hub with host{" "}
                <span className="mono">http://&lt;this-pc-lan-ip&gt;:{form.port || 8199}</span> and
                header <span className="mono">X-Api-Key</span>.
              </p>
              <div className="field">
                <label htmlFor="api_key">API key</label>
                <input
                  id="api_key"
                  className="mono"
                  value={form.api_key}
                  readOnly
                  onFocus={(e) => e.target.select()}
                />
              </div>
              <div className="row" style={{ gap: "0.5rem", marginBottom: "0.75rem" }}>
                <button className="btn" type="button" disabled={busy || !form.api_key} onClick={() => void onCopyKey()}>
                  Copy
                </button>
                <button
                  className="btn"
                  type="button"
                  disabled={busy}
                  onClick={() => void onRegenerateKey()}
                >
                  Regenerate
                </button>
              </div>
              <label className="mode-option" style={{ marginBottom: 0 }}>
                <input
                  type="checkbox"
                  checked={form.api_auth_required}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, api_auth_required: e.target.checked }))
                  }
                />
                <span>
                  <strong>Require API key for /api</strong>
                  <small>
                    Keep on when exposing ytarr on your LAN. Logged-in browsers use a session
                    cookie; hubs use the API key.
                  </small>
                </span>
              </label>
            </div>

            <div className="row">
              <div className="field grow">
                <label htmlFor="host">Bind address</label>
                <input id="host" value={form.host} onChange={set("host")} />
                <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
                  Use <span className="mono">0.0.0.0</span> so phones on your Wi‑Fi can reach ytarr
                  (then restart the tray app). <span className="mono">127.0.0.1</span> is
                  this-PC-only.
                </p>
              </div>
              <div className="field grow">
                <label htmlFor="port">Port</label>
                <input id="port" type="number" value={form.port} onChange={set("port")} />
              </div>
            </div>
            <div className="field">
              <label htmlFor="poll">Poll interval (minutes)</label>
              <input
                id="poll"
                type="number"
                min={1}
                value={form.poll_interval_minutes}
                onChange={set("poll_interval_minutes")}
              />
            </div>
            <label className="mode-option" style={{ marginBottom: "1rem" }}>
              <input
                type="checkbox"
                checked={form.nocheck_certificates}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, nocheck_certificates: e.target.checked }))
                }
              />
              <span>
                <strong>Skip HTTPS certificate checks</strong>
                <small>
                  Off by default. Prefer a VPN on broken guest Wi‑Fi instead of disabling certs.
                </small>
              </span>
            </label>
          </>
        )}

        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save changes"}
        </button>
      </form>
    </>
  );
}
