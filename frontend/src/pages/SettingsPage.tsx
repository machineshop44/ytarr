import { type ChangeEvent, type FormEvent, useEffect, useState } from "react";
import { api, type Settings } from "../api";

const empty: Settings = {
  host: "127.0.0.1",
  port: 8199,
  data_dir: "",
  library_root: "",
  ytdlp_path: "yt-dlp",
  format: "bv*+ba/b",
  output_template: "",
  poll_interval_minutes: 30,
  concurrent_downloads: 1,
  nocheck_certificates: false,
};

export function SettingsPage() {
  const [form, setForm] = useState<Settings>(empty);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api
      .settings()
      .then(setForm)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await api.updateSettings(form);
      setForm(saved);
      setMessage("Settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const set =
    (key: keyof Settings) =>
    (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
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
          <h1>Settings</h1>
          <p>Library path, format, monitor interval, and optional yt-dlp override.</p>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      <form className="panel" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="library_root">Library root</label>
          <input id="library_root" value={form.library_root} onChange={set("library_root")} />
        </div>
        <div className="field">
          <label htmlFor="ytdlp_path">yt-dlp path</label>
          <input
            id="ytdlp_path"
            value={form.ytdlp_path}
            onChange={set("ytdlp_path")}
            placeholder="yt-dlp"
          />
          <p className="muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
            Leave as <span className="mono">yt-dlp</span> or empty to use the bundled Python module (
            <span className="mono">python -m yt_dlp</span>). Set an absolute path to{" "}
            <span className="mono">yt-dlp.exe</span> only for an external binary.
          </p>
        </div>
        <div className="field">
          <label htmlFor="format">Format selector</label>
          <input id="format" value={form.format} onChange={set("format")} />
        </div>
        <div className="field">
          <label htmlFor="output_template">Output template</label>
          <textarea
            id="output_template"
            rows={3}
            value={form.output_template}
            onChange={set("output_template")}
          />
        </div>
        <div className="row">
          <div className="field grow">
            <label htmlFor="poll">Poll interval (minutes)</label>
            <input
              id="poll"
              type="number"
              min={1}
              value={form.poll_interval_minutes}
              onChange={set("poll_interval_minutes")}
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
              Off by default (recommended). Only enable on broken guest/corporate Wi‑Fi with SSL
              inspection — prefer a VPN (e.g. Surfshark) instead when you can.
            </small>
          </span>
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save settings"}
        </button>
      </form>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Plex tip</h3>
        <p className="muted" style={{ marginBottom: 0 }}>
          Point a separate Plex library at your library root. Use Local Media Assets / Personal
          Media so each channel folder uses <span className="mono">poster.jpg</span> instead of
          TVDB matching. Keep YouTube out of Sonarr and your main TV library.
        </p>
      </div>
    </>
  );
}
