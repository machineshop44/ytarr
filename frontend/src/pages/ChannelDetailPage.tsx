import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  type DownloadJob,
  type RenameItem,
  type SearchHit,
  type Source,
  type Video,
} from "../api";
import {
  AlbumMonitorRow,
  TrackMonitorRow,
  albumSubtitle,
  trackIsMonitored,
} from "../components/AlbumMonitor";
import { findExistingPlaylist } from "../components/playlistMatch";

type SeriesTab = "episodes" | "history" | "rename";

async function kickQueue() {
  try {
    await api.processQueue();
  } catch {
    /* scheduler */
  }
}

export function ChannelDetailPage() {
  const { sourceId } = useParams();
  const navigate = useNavigate();
  const id = Number(sourceId);

  const [source, setSource] = useState<Source | null>(null);
  const [allSources, setAllSources] = useState<Source[]>([]);
  const [playlists, setPlaylists] = useState<SearchHit[]>([]);
  const [uploadVideos, setUploadVideos] = useState<Video[]>([]);
  const [albumTracks, setAlbumTracks] = useState<Record<number, Video[]>>({});
  const [expandedKey, setExpandedKey] = useState<string | null>("uploads");
  const [loading, setLoading] = useState(true);
  const [loadingPlaylists, setLoadingPlaylists] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [tab, setTab] = useState<SeriesTab>("episodes");
  const [editOpen, setEditOpen] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editEnabled, setEditEnabled] = useState(true);
  const [editMode, setEditMode] = useState("all");

  // History
  const [historyJobs, setHistoryJobs] = useState<DownloadJob[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Rename
  const [renameItems, setRenameItems] = useState<RenameItem[]>([]);
  const [renameSelected, setRenameSelected] = useState<Set<number>>(new Set());
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameNeeds, setRenameNeeds] = useState(0);

  const relatedSourceIds = useMemo(() => {
    if (!source) return [] as number[];
    const ids = new Set<number>([source.id]);
    for (const hit of playlists) {
      const existing = findExistingPlaylist(allSources, hit);
      if (existing) ids.add(existing.id);
    }
    return [...ids];
  }, [source, playlists, allSources]);

  const loadCore = useCallback(async () => {
    if (!Number.isFinite(id)) throw new Error("Invalid source");
    const [sources, vids] = await Promise.all([
      api.sources(),
      api.videos({ source_id: id }),
    ]);
    const found = sources.find((s) => s.id === id);
    if (!found) throw new Error("Source not found");
    setAllSources(sources);
    setSource(found);
    setUploadVideos(vids);
    return found;
  }, [id]);

  useEffect(() => {
    let alive = true;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const found = await loadCore();
        if (!alive) return;
        if (found.source_type === "channel") {
          setLoadingPlaylists(true);
          try {
            const res = await api.channelPlaylists(found.url, 50);
            if (alive) setPlaylists(res.results);
          } catch (err) {
            if (alive) setError(err instanceof Error ? err.message : String(err));
          } finally {
            if (alive) setLoadingPlaylists(false);
          }
        } else {
          setPlaylists([]);
          setExpandedKey("self");
        }
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (alive) setLoading(false);
      }
    };
    void run();
    const timer = window.setInterval(() => {
      void loadCore().catch(() => undefined);
    }, 8000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [loadCore]);

  const loadHistory = useCallback(async (sourceIds: number[]) => {
    setHistoryLoading(true);
    try {
      const batches = await Promise.all(
        sourceIds.map((sid) =>
          Promise.all([
            api.queue({ status: "active", source_id: sid, limit: 100 }),
            api.queue({ status: "history", source_id: sid, limit: 100 }),
          ]),
        ),
      );
      const merged = new Map<number, DownloadJob>();
      for (const [active, hist] of batches) {
        for (const j of [...active, ...hist]) merged.set(j.id, j);
      }
      const list = [...merged.values()].sort((a, b) => b.id - a.id);
      setHistoryJobs(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const loadRename = useCallback(async (sourceIds: number[]) => {
    setRenameBusy(true);
    try {
      const previews = await Promise.all(sourceIds.map((sid) => api.renamePreview(sid)));
      const items = previews.flatMap((p) => p.items);
      const needs = previews.reduce((n, p) => n + p.needs_rename_count, 0);
      setRenameItems(items);
      setRenameNeeds(needs);
      setRenameSelected(new Set(items.filter((i) => i.needs_rename).map((i) => i.video_db_id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRenameBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!relatedSourceIds.length) return;
    if (tab === "history") void loadHistory(relatedSourceIds);
    if (tab === "rename") void loadRename(relatedSourceIds);
  }, [tab, relatedSourceIds, loadHistory, loadRename]);

  const loadAlbumTracks = async (sourceId: number) => {
    const vids = await api.videos({ source_id: sourceId });
    setAlbumTracks((prev) => ({ ...prev, [sourceId]: vids }));
    return vids;
  };

  const toggleExpand = async (key: string, playlistSource?: Source) => {
    if (expandedKey === key) {
      setExpandedKey(null);
      return;
    }
    setExpandedKey(key);
    if (playlistSource && albumTracks[playlistSource.id] == null) {
      try {
        await loadAlbumTracks(playlistSource.id);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
  };

  const runToolbar = async (key: string, fn: () => Promise<void>, okMsg: string) => {
    setBusyKey(key);
    setError(null);
    setMessage(null);
    try {
      await fn();
      setMessage(okMsg);
      await loadCore();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  };

  const onRefresh = () =>
    void runToolbar(
      "refresh",
      async () => {
        if (!source) return;
        await api.checkSource(source.id);
        await api.refreshArtwork(source.id);
        await kickQueue();
      },
      "Refreshed series metadata and checked for new videos.",
    );

  const onSearchAll = () => {
    if (!source) return;
    if (
      !window.confirm(
        `Queue missing downloads for ${source.title}? This can grab a lot of videos.`,
      )
    ) {
      return;
    }
    void runToolbar(
      "search",
      async () => {
        await api.backfillSource(source.id);
        for (const hit of playlists) {
          const existing = findExistingPlaylist(allSources, hit);
          if (existing?.enabled) await api.backfillSource(existing.id);
        }
        await kickQueue();
      },
      "Search queued — check Activity for progress.",
    );
  };

  const openEdit = () => {
    if (!source) return;
    setEditTitle(source.title);
    setEditEnabled(source.enabled);
    setEditMode(source.monitor_mode === "video" ? "all" : source.monitor_mode);
    setEditOpen(true);
  };

  const saveEdit = async () => {
    if (!source) return;
    setBusyKey("edit");
    setError(null);
    try {
      const updated = await api.patchSource(source.id, {
        title: editTitle.trim() || source.title,
        enabled: editEnabled,
        monitor_mode: editMode,
      });
      setSource(updated);
      setEditOpen(false);
      setMessage("Series settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  };

  const onDelete = () => {
    if (!source) return;
    if (
      !window.confirm(
        `Remove ${source.title} from the library? Downloaded files on disk are kept.`,
      )
    ) {
      return;
    }
    void runToolbar(
      "delete",
      async () => {
        await api.deleteSource(source.id);
        navigate("/");
      },
      "Removed.",
    );
  };

  const toggleUploadsMonitor = async () => {
    if (!source) return;
    setBusyKey("uploads-mon");
    setError(null);
    try {
      if (!source.enabled) {
        await api.patchSource(source.id, { enabled: true });
        await api.backfillSource(source.id);
        await kickQueue();
        setMessage("Uploads monitored — downloading.");
      } else {
        await api.patchSource(source.id, { enabled: false });
        setMessage("Uploads unmonitored.");
      }
      await loadCore();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  };

  const togglePlaylistMonitor = async (hit: SearchHit, existing?: Source) => {
    setBusyKey(hit.url);
    setError(null);
    setMessage(null);
    try {
      if (existing?.enabled) {
        await api.patchSource(existing.id, { enabled: false });
        setMessage(`Unmonitored ${existing.title}.`);
      } else if (existing) {
        await api.patchSource(existing.id, { enabled: true });
        await api.backfillSource(existing.id);
        await kickQueue();
        setMessage(`Monitoring ${existing.title} — downloading.`);
        await loadAlbumTracks(existing.id);
      } else {
        const created = await api.addSource(hit.url, "all");
        await kickQueue();
        setMessage(`Monitoring ${created.title} — downloading.`);
        await loadCore();
        await loadAlbumTracks(created.id);
        setExpandedKey(hit.id || hit.url);
      }
      await loadCore();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  };

  const toggleTrack = async (video: Video) => {
    setBusyKey(`v-${video.id}`);
    setError(null);
    try {
      if (trackIsMonitored(video.status)) {
        await api.ignoreVideo(video.id);
      } else {
        await api.retryVideo(video.id);
        await kickQueue();
      }
      await loadCore();
      if (video.source_id !== id) {
        await loadAlbumTracks(video.source_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  };

  const renderTracks = (vids: Video[]) => {
    if (!vids.length) {
      return <p className="muted track-empty">No episodes yet — refresh or monitor this season.</p>;
    }
    return vids.map((v) => (
      <TrackMonitorRow
        key={v.id}
        title={v.title}
        status={v.status}
        published={v.published_at ? new Date(v.published_at).toLocaleDateString() : null}
        checked={trackIsMonitored(v.status)}
        busy={busyKey === `v-${v.id}`}
        onToggle={() => void toggleTrack(v)}
      />
    ));
  };

  const renameSelectable = useMemo(
    () => renameItems.filter((i) => i.needs_rename).map((i) => i.video_db_id),
    [renameItems],
  );

  const applyRename = async () => {
    if (!renameSelected.size) return;
    if (!window.confirm(`Rename ${renameSelected.size} file(s)?`)) return;
    setRenameBusy(true);
    setError(null);
    try {
      const result = await api.renameApply({ video_ids: [...renameSelected] });
      setMessage(
        `Renamed ${result.renamed}, skipped ${result.skipped}` +
          (result.errors.length ? ` · ${result.errors.length} error(s)` : ""),
      );
      if (result.errors.length) setError(result.errors.join("\n"));
      await loadRename(relatedSourceIds);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRenameBusy(false);
    }
  };

  if (loading && !source) {
    return <p className="muted">Loading…</p>;
  }

  if (!source) {
    return (
      <>
        <div className="error">{error || "Series not found"}</div>
        <Link className="btn" to="/">
          ← Library
        </Link>
      </>
    );
  }

  const isChannel = source.source_type === "channel";
  const modeLabel =
    source.monitor_mode === "all" ? "All" : source.monitor_mode === "new" ? "Future" : "Video";

  return (
    <>
      <div className="page-header">
        <div>
          <button className="btn" type="button" onClick={() => navigate("/")}>
            ← Library
          </button>
        </div>
        <Link className="btn" to="/activity">
          Activity
        </Link>
      </div>

      {error && (
        <div className="error" style={{ whiteSpace: "pre-wrap" }}>
          {error}
        </div>
      )}
      {message && <div className="success">{message}</div>}

      <section className="channel-hero panel">
        <div className="channel-hero-art">
          {source.poster_path ? (
            <img src={api.posterUrl(source.id)} alt="" />
          ) : (
            <div className="poster-card-placeholder">No poster</div>
          )}
        </div>
        <div className="channel-hero-body">
          <div className="source-meta">
            <span className="badge">{isChannel ? "series" : source.source_type}</span>
            <span className="badge">Monitor: {modeLabel}</span>
            <span className="badge">{source.enabled ? "monitored" : "unmonitored"}</span>
          </div>
          <h1 style={{ margin: "0.35rem 0 0.5rem" }}>{source.title}</h1>
          <div className="source-meta">
            <span>
              {source.downloaded_count}/{source.video_count || "—"} on disk
            </span>
            <span>{source.wanted_count} wanted</span>
            <span className="mono" style={{ fontSize: "0.75rem" }}>
              {source.folder_name}
            </span>
          </div>
          <p className="muted" style={{ margin: "0.65rem 0 0" }}>
            {isChannel
              ? "Seasons = playlists · Episodes = videos. Members-only videos are hidden."
              : "Episodes in this playlist."}
          </p>

          <div className="series-toolbar">
            <button
              className="btn"
              type="button"
              disabled={busyKey === "refresh"}
              onClick={onRefresh}
              title="Check for new videos and refresh artwork"
            >
              Refresh
            </button>
            <button
              className="btn btn-primary"
              type="button"
              disabled={busyKey === "search" || source.monitor_mode === "video"}
              onClick={onSearchAll}
              title="Queue missing downloads"
            >
              Search
            </button>
            <button
              className="btn"
              type="button"
              onClick={() => setTab("rename")}
              title="Preview and apply file renames"
            >
              Rename
            </button>
            <button className="btn" type="button" onClick={openEdit} title="Edit series">
              Edit
            </button>
            <button
              className="btn"
              type="button"
              onClick={() => setTab("history")}
              title="Download history for this series"
            >
              History
            </button>
            <button
              className="btn btn-danger"
              type="button"
              disabled={busyKey === "delete"}
              onClick={onDelete}
            >
              Delete
            </button>
          </div>
        </div>
      </section>

      <div className="tabs" role="tablist">
        {(
          [
            ["episodes", "Episodes"],
            ["history", "History"],
            ["rename", "Rename"],
          ] as const
        ).map(([idTab, label]) => (
          <button
            key={idTab}
            type="button"
            role="tab"
            className={`tab ${tab === idTab ? "active" : ""}`}
            aria-selected={tab === idTab}
            onClick={() => setTab(idTab)}
          >
            {label}
            {idTab === "rename" && renameNeeds > 0 ? ` (${renameNeeds})` : ""}
          </button>
        ))}
      </div>

      {tab === "episodes" &&
        (isChannel ? (
          <section className="panel">
            <div className="section-head">
              <h2>Seasons</h2>
              <span className="muted">Uploads + playlists</span>
            </div>
            <div className="album-list">
              <AlbumMonitorRow
                title="Uploads"
                subtitle={`${source.downloaded_count}/${source.video_count || "—"} on disk${
                  source.wanted_count ? ` · ${source.wanted_count} wanted` : ""
                }`}
                thumbnailUrl={source.poster_path ? api.posterUrl(source.id) : null}
                monitored={source.enabled}
                busy={busyKey === "uploads-mon"}
                expanded={expandedKey === "uploads"}
                onToggleMonitor={() => void toggleUploadsMonitor()}
                onToggleExpand={() => void toggleExpand("uploads")}
              >
                {renderTracks(uploadVideos)}
              </AlbumMonitorRow>

              {loadingPlaylists && <p className="muted">Loading seasons…</p>}

              {playlists.map((hit) => {
                const existing = findExistingPlaylist(allSources, hit);
                const key = hit.id || hit.url;
                const monitored = Boolean(existing?.enabled);
                return (
                  <AlbumMonitorRow
                    key={key}
                    title={hit.title}
                    subtitle={albumSubtitle(hit, existing)}
                    thumbnailUrl={hit.thumbnail_url}
                    monitored={monitored}
                    busy={busyKey === hit.url}
                    expanded={expandedKey === key}
                    onToggleMonitor={() => void togglePlaylistMonitor(hit, existing)}
                    onToggleExpand={() => {
                      if (existing) void toggleExpand(key, existing);
                      else setExpandedKey((prev) => (prev === key ? null : key));
                    }}
                  >
                    {existing ? (
                      renderTracks(albumTracks[existing.id] || [])
                    ) : (
                      <p className="muted track-empty">
                        Check the box to monitor this season and download its episodes.
                      </p>
                    )}
                  </AlbumMonitorRow>
                );
              })}
            </div>
          </section>
        ) : (
          <section className="panel">
            <div className="section-head">
              <h2>Episodes</h2>
              <span className="muted">
                {source.downloaded_count}/{source.video_count || 0} on disk
              </span>
            </div>
            <div className="album-list">
              <AlbumMonitorRow
                title={source.title}
                subtitle={`${uploadVideos.length} episodes`}
                thumbnailUrl={source.poster_path ? api.posterUrl(source.id) : null}
                monitored={source.enabled}
                busy={busyKey === "uploads-mon"}
                expanded={expandedKey === "self"}
                onToggleMonitor={() => void toggleUploadsMonitor()}
                onToggleExpand={() => void toggleExpand("self")}
              >
                {renderTracks(uploadVideos)}
              </AlbumMonitorRow>
            </div>
          </section>
        ))}

      {tab === "history" && (
        <section className="panel table-wrap">
          {historyLoading && <p className="muted">Loading history…</p>}
          <table>
            <thead>
              <tr>
                <th>Episode</th>
                <th>Status</th>
                <th>Progress</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {historyJobs.map((job) => (
                <tr key={job.id}>
                  <td>
                    <div>{job.video_title || `Video #${job.video_id}`}</div>
                    <div className="muted mono">{job.youtube_id}</div>
                    {job.error && (
                      <div className="error" style={{ marginTop: 6 }}>
                        {job.error}
                      </div>
                    )}
                  </td>
                  <td>
                    <span className={`badge ${job.status}`}>{job.status}</span>
                  </td>
                  <td className="mono muted">
                    {job.status === "downloading" || job.status === "queued"
                      ? `${job.progress.toFixed(0)}%`
                      : "—"}
                  </td>
                  <td className="mono muted">
                    {job.finished_at || job.started_at || job.created_at
                      ? new Date(
                          job.finished_at || job.started_at || job.created_at,
                        ).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!historyLoading && !historyJobs.length && (
            <p className="muted">No download history for this series yet.</p>
          )}
        </section>
      )}

      {tab === "rename" && (
        <section className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.75rem" }}>
            <p className="muted" style={{ margin: 0 }}>
              {renameNeeds} file(s) need renaming · pattern{" "}
              <span className="mono">YYYY-MM-DD - Title [id].ext</span>
            </p>
            <div className="row">
              <button
                className="btn"
                type="button"
                disabled={renameBusy}
                onClick={() => void loadRename(relatedSourceIds)}
              >
                Preview
              </button>
              <button
                className="btn btn-primary"
                type="button"
                disabled={renameBusy || renameSelected.size === 0}
                onClick={() => void applyRename()}
              >
                Rename {renameSelected.size || ""} selected
              </button>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 36 }}>
                    <input
                      type="checkbox"
                      checked={
                        renameSelectable.length > 0 &&
                        renameSelected.size === renameSelectable.length
                      }
                      onChange={() => {
                        setRenameSelected((prev) =>
                          prev.size === renameSelectable.length
                            ? new Set()
                            : new Set(renameSelectable),
                        );
                      }}
                      disabled={!renameSelectable.length}
                    />
                  </th>
                  <th>Title</th>
                  <th>Current</th>
                  <th>New</th>
                </tr>
              </thead>
              <tbody>
                {renameItems.map((item) => (
                  <tr key={item.video_db_id} className={item.needs_rename ? "" : "muted"}>
                    <td>
                      <input
                        type="checkbox"
                        disabled={!item.needs_rename}
                        checked={renameSelected.has(item.video_db_id)}
                        onChange={() => {
                          setRenameSelected((prev) => {
                            const next = new Set(prev);
                            if (next.has(item.video_db_id)) next.delete(item.video_db_id);
                            else next.add(item.video_db_id);
                            return next;
                          });
                        }}
                      />
                    </td>
                    <td>
                      <div>{item.title}</div>
                      <div className="muted mono" style={{ fontSize: "0.75rem" }}>
                        {item.youtube_id}
                      </div>
                    </td>
                    <td className="mono" style={{ fontSize: "0.72rem", wordBreak: "break-all" }}>
                      {item.current_path || "—"}
                    </td>
                    <td className="mono" style={{ fontSize: "0.72rem", wordBreak: "break-all" }}>
                      {item.new_path || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!renameItems.length && !renameBusy && (
              <p className="muted">No downloaded files to rename for this series yet.</p>
            )}
          </div>
        </section>
      )}

      {editOpen && (
        <div className="modal-backdrop" role="presentation" onClick={() => setEditOpen(false)}>
          <div
            className="modal-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="edit-series-title"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: 480 }}
          >
            <div className="modal-header">
              <h2 id="edit-series-title">Edit series</h2>
              <button className="btn" type="button" onClick={() => setEditOpen(false)}>
                Close
              </button>
            </div>
            <div className="modal-body">
              <div className="field">
                <label htmlFor="edit-title">Title</label>
                <input
                  id="edit-title"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="edit-mode">Monitor</label>
                <select
                  id="edit-mode"
                  value={editMode}
                  onChange={(e) => setEditMode(e.target.value)}
                >
                  <option value="all">All — download catalog + future</option>
                  <option value="new">Future — new uploads only</option>
                </select>
              </div>
              <label className="mode-option" style={{ marginBottom: 0 }}>
                <input
                  type="checkbox"
                  checked={editEnabled}
                  onChange={(e) => setEditEnabled(e.target.checked)}
                />
                <span>
                  <strong>Monitored</strong>
                  <small>Include this series in automatic checks.</small>
                </span>
              </label>
              <p className="muted" style={{ marginTop: "0.85rem", marginBottom: 0 }}>
                Path folder: <span className="mono">{source.folder_name}</span>
              </p>
            </div>
            <div className="modal-footer">
              <button className="btn" type="button" onClick={() => setEditOpen(false)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                type="button"
                disabled={busyKey === "edit"}
                onClick={() => void saveEdit()}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
