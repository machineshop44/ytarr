import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Source } from "../api";
import { MEDIA_TYPE_OPTIONS, coerceQualityForMedia, qualityOptionsFor } from "../qualityOptions";

type AddMode = "new" | "all" | "video";

function detectUrlKind(url: string): "video" | "playlist" | "channel" | "unknown" {
  const u = url.trim().toLowerCase();
  if (!u) return "unknown";
  if (u.includes("youtu.be/") || u.includes("watch?") || u.includes("/shorts/") || u.includes("/live/")) {
    if (u.includes("list=") && u.includes("watch")) return "playlist";
    return "video";
  }
  if (u.includes("playlist") || u.includes("list=")) return "playlist";
  if (u.includes("/@") || u.includes("/channel/") || u.includes("/c/") || u.includes("/user/")) {
    return "channel";
  }
  return "unknown";
}

export function SourcesPage() {
  const navigate = useNavigate();
  const [sources, setSources] = useState<Source[]>([]);
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<AddMode>("all");
  const [quality, setQuality] = useState("");
  const [mediaType, setMediaType] = useState<"video" | "audio">("video");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<number | null>(null);

  const urlKind = useMemo(() => detectUrlKind(url), [url]);

  useEffect(() => {
    if (urlKind === "video") setMode("video");
    else if (mode === "video") setMode("all");
  }, [urlKind]); // eslint-disable-line react-hooks/exhaustive-deps

  const load = async () => {
    setSources(await api.sources());
  };

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const onAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const source = await api.addSource(url.trim(), mode, { quality, media_type: mediaType });
      setUrl("");
      setMode("all");
      setQuality("");
      setMediaType("video");
      try {
        await api.processQueue();
      } catch {
        /* ignore */
      }
      navigate(api.sourceDetailPath(source.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (id: number, fn: () => Promise<unknown>, okMsg: string) => {
    setActionId(id);
    setError(null);
    setMessage(null);
    try {
      await fn();
      setMessage(okMsg);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionId(null);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Sources</h1>
          <p>
            Add or manage monitored URLs. For day-to-day browsing use the{" "}
            <Link to="/">Library</Link>; to import orphan files from disk use{" "}
            <Link to="/import">Manual Import</Link>.
          </p>
        </div>
        <Link className="btn btn-primary" to="/add">
          Add New
        </Link>
      </div>

      <form className="panel" onSubmit={onAdd}>
        <div className="field">
          <label htmlFor="source-url">YouTube URL</label>
          <input
            id="source-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/@channel · playlist · or watch?v=…"
            disabled={busy}
          />
        </div>

        <fieldset className="mode-fieldset">
          <legend>Monitor</legend>
          <label className={`mode-option ${mode === "all" ? "selected" : ""}`}>
            <input
              type="radio"
              name="add-mode"
              checked={mode === "all"}
              disabled={busy || urlKind === "video"}
              onChange={() => setMode("all")}
            />
            <span>
              <strong>All</strong>
              <small>Download the full catalog now, then keep grabbing new uploads (default).</small>
            </span>
          </label>
          <label className={`mode-option ${mode === "new" ? "selected" : ""}`}>
            <input
              type="radio"
              name="add-mode"
              checked={mode === "new"}
              disabled={busy || urlKind === "video"}
              onChange={() => setMode("new")}
            />
            <span>
              <strong>Future</strong>
              <small>Remember what’s already there; download future videos only.</small>
            </span>
          </label>
          <label className={`mode-option ${mode === "video" ? "selected" : ""}`}>
            <input
              type="radio"
              name="add-mode"
              checked={mode === "video"}
              disabled={busy || (urlKind !== "video" && urlKind !== "unknown")}
              onChange={() => setMode("video")}
            />
            <span>
              <strong>This video only</strong>
              <small>One-shot download from a watch / youtu.be / Shorts link.</small>
            </span>
          </label>
        </fieldset>

        <p className="muted hint">
          A channel link does <strong>not</strong> pull every playlist — only the uploads feed. Open
          the channel in the Library to pick playlists.
        </p>

        <div className="row" style={{ gap: "0.75rem" }}>
          <div className="field grow">
            <label htmlFor="src-quality">{mediaType === "audio" ? "Music quality" : "Video quality"}</label>
            <select
              id="src-quality"
              value={quality}
              disabled={busy}
              onChange={(e) => setQuality(e.target.value)}
            >
              {qualityOptionsFor(mediaType).map((o) => (
                <option key={o.value || "default"} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field grow">
            <label htmlFor="src-media">Media type</label>
            <select
              id="src-media"
              value={mediaType}
              disabled={busy}
              onChange={(e) => {
                const next = e.target.value as "video" | "audio";
                setMediaType(next);
                setQuality((q) => coerceQualityForMedia(q, next));
              }}
            >
              {MEDIA_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={busy || !url.trim()}>
            {busy ? "Adding…" : "Add"}
          </button>
        </div>
      </form>

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      <div className="source-grid">
        {sources.map((source) => (
          <article key={source.id} className="source-card">
            <Link to={api.sourceDetailPath(source.id)} className="source-card-link">
              {source.poster_path ? (
                <img
                  className="source-poster"
                  src={api.posterUrl(source.id)}
                  alt={`${source.title} poster`}
                />
              ) : (
                <div className="source-poster placeholder">No poster yet</div>
              )}
            </Link>
            <div className="source-body">
              <div>
                <h3>
                  <Link to={api.sourceDetailPath(source.id)}>{source.title}</Link>
                </h3>
                <div className="source-meta">
                  <span className="badge">{source.source_type}</span>
                  <span className="badge">{source.monitor_mode}</span>
                  <span className="badge">{source.enabled ? "enabled" : "disabled"}</span>
                  <span>{source.downloaded_count} downloaded</span>
                  <span>{source.wanted_count} pending</span>
                </div>
              </div>
              <div className="muted mono" style={{ fontSize: "0.75rem", wordBreak: "break-all" }}>
                {source.url}
              </div>
              <div className="row">
                <button
                  className="btn"
                  type="button"
                  disabled={actionId === source.id || source.monitor_mode === "video"}
                  onClick={() =>
                    void runAction(source.id, () => api.checkSource(source.id), "Check complete")
                  }
                >
                  Check now
                </button>
                {source.monitor_mode !== "video" && (
                  <button
                    className="btn"
                    type="button"
                    disabled={actionId === source.id}
                    onClick={() => {
                      if (
                        !window.confirm(
                          `Queue the entire catalog for ${source.title}? This can be a lot of downloads.`,
                        )
                      ) {
                        return;
                      }
                      void runAction(
                        source.id,
                        () => api.backfillSource(source.id),
                        "Backfill queued",
                      );
                    }}
                  >
                    Download all
                  </button>
                )}
                <button
                  className="btn"
                  type="button"
                  disabled={actionId === source.id}
                  onClick={() =>
                    void runAction(
                      source.id,
                      () => api.refreshArtwork(source.id),
                      "Artwork refreshed",
                    )
                  }
                >
                  Refresh art
                </button>
                <button
                  className="btn"
                  type="button"
                  disabled={actionId === source.id}
                  onClick={() =>
                    void runAction(
                      source.id,
                      () => api.patchSource(source.id, { enabled: !source.enabled }),
                      source.enabled ? "Disabled" : "Enabled",
                    )
                  }
                >
                  {source.enabled ? "Disable" : "Enable"}
                </button>
                <button
                  className="btn btn-danger"
                  type="button"
                  disabled={actionId === source.id}
                  onClick={() => {
                    if (!window.confirm(`Remove “${source.title}” from the library?`)) return;
                    const wipe = window.confirm(
                      `Also delete files for “${source.title}” from disk?\n\n` +
                        `OK = delete folder/files\nCancel = keep files on disk`,
                    );
                    void runAction(
                      source.id,
                      () => api.deleteSource(source.id, { deleteFiles: wipe }),
                      wipe ? "Removed (files deleted)" : "Removed (files kept)",
                    );
                  }}
                >
                  Remove
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>

      {!sources.length && !error && (
        <p className="muted">No sources yet. Use Add New or paste a URL above.</p>
      )}
    </>
  );
}
