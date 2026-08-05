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
  EpisodeTable,
  TrackMonitorRow,
  albumSubtitle,
  trackIsMonitored,
} from "../components/AlbumMonitor";
import { findExistingPlaylist } from "../components/playlistMatch";
import { MEDIA_TYPE_OPTIONS, coerceQualityForMedia, qualityLabel, qualityOptionsFor } from "../qualityOptions";

type SeriesTab = "episodes" | "history" | "rename";

async function kickQueue() {
  void api.processQueue().catch(() => undefined);
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
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set());
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
  const [editQuality, setEditQuality] = useState("");
  const [editMediaType, setEditMediaType] = useState("video");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteFiles, setDeleteFiles] = useState(false);

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

  /** YouTube ids already covered by a monitored playlist — omit these from Uploads UI. */
  const playlistOwnedIds = useMemo(() => {
    const ids = new Set<string>();
    for (const hit of playlists) {
      const existing = findExistingPlaylist(allSources, hit);
      if (!existing?.enabled) continue;
      for (const v of albumTracks[existing.id] || []) {
        ids.add(v.video_id);
      }
    }
    return ids;
  }, [playlists, allSources, albumTracks]);

  const uploadVideosVisible = useMemo(() => {
    if (!playlistOwnedIds.size) return uploadVideos;
    return uploadVideos.filter((v) => !playlistOwnedIds.has(v.video_id));
  }, [uploadVideos, playlistOwnedIds]);

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
            // Prefetch playlist catalogs so Uploads can hide duplicates
            const sourcesNow = await api.sources();
            if (!alive) return;
            setAllSources(sourcesNow);
            await Promise.all(
              res.results.map(async (hit) => {
                const existing = findExistingPlaylist(sourcesNow, hit);
                if (!existing) return;
                try {
                  const vids = await api.videos({ source_id: existing.id });
                  if (alive) {
                    setAlbumTracks((prev) => ({ ...prev, [existing.id]: vids }));
                  }
                } catch {
                  /* ignore */
                }
              }),
            );
          } catch (err) {
            if (alive) setError(err instanceof Error ? err.message : String(err));
          } finally {
            if (alive) setLoadingPlaylists(false);
          }
        } else {
          setPlaylists([]);
          setExpandedKeys(new Set(["self"]));
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
    }, source && !source.initialized ? 2000 : 8000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [loadCore, source?.initialized]);

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

  const loadRename = useCallback(async (sourceIds: number[], opts?: { quiet?: boolean }) => {
    if (!opts?.quiet) setRenameBusy(true);
    try {
      const previews = await Promise.all(sourceIds.map((sid) => api.renamePreview(sid)));
      const items = previews.flatMap((p) => p.items);
      const needs = previews.reduce((n, p) => n + p.needs_rename_count, 0);
      setRenameItems(items);
      setRenameNeeds(needs);
      setRenameSelected(new Set(items.filter((i) => i.needs_rename).map((i) => i.video_db_id)));
    } catch (err) {
      if (!opts?.quiet) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!opts?.quiet) setRenameBusy(false);
    }
  }, []);

  // Prefetch rename preview for this series (tab badge + Preview Rename toolbar)
  useEffect(() => {
    if (!relatedSourceIds.length) return;
    void loadRename(relatedSourceIds, { quiet: true });
  }, [relatedSourceIds, loadRename]);

  useEffect(() => {
    if (!relatedSourceIds.length) return;
    if (tab === "history") void loadHistory(relatedSourceIds);
  }, [tab, relatedSourceIds, loadHistory]);

  const loadAlbumTracks = async (sourceId: number, opts?: { refresh?: boolean }) => {
    if (opts?.refresh) {
      try {
        await api.checkSource(sourceId);
      } catch {
        /* still try to list what we have */
      }
    }
    const vids = await api.videos({ source_id: sourceId });
    setAlbumTracks((prev) => ({ ...prev, [sourceId]: vids }));
    // Keep library counts fresh after catalog sync
    if (opts?.refresh) {
      try {
        const sources = await api.sources();
        setAllSources(sources);
        const found = sources.find((s) => s.id === id);
        if (found) setSource(found);
      } catch {
        /* ignore */
      }
    }
    return vids;
  };

  const refreshUploadsCatalog = async () => {
    if (!source) return;
    try {
      await api.checkSource(source.id);
      await loadCore();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const toggleExpand = async (key: string, playlistSource?: Source) => {
    const willExpand = !expandedKeys.has(key);
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    if (playlistSource) {
      try {
        const cached = albumTracks[playlistSource.id];
        if (cached == null) {
          const vids = await loadAlbumTracks(playlistSource.id);
          if (!vids.length) {
            await loadAlbumTracks(playlistSource.id, { refresh: true });
          }
        } else if (!cached.length) {
          await loadAlbumTracks(playlistSource.id, { refresh: true });
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } else if (willExpand && (key === "uploads" || key === "self") && !uploadVideos.length) {
      // Structure-only channels used to skip Uploads enumeration — pull catalog on expand
      await refreshUploadsCatalog();
    }
  };

  const expandAllSeasons = async () => {
    const keys = [...playlists.map((h) => h.id || h.url), "uploads"];
    setExpandedKeys(new Set(keys));
    for (const hit of playlists) {
      const existing = findExistingPlaylist(allSources, hit);
      if (existing && albumTracks[existing.id] == null) {
        try {
          await loadAlbumTracks(existing.id);
        } catch {
          /* ignore */
        }
      }
    }
    if (source && !uploadVideos.length) {
      await refreshUploadsCatalog();
    }
  };

  const collapseAllSeasons = () => setExpandedKeys(new Set());

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
        for (const hit of playlists) {
          const existing = findExistingPlaylist(allSources, hit);
          if (existing?.enabled) {
            await api.checkSource(existing.id);
            await loadAlbumTracks(existing.id);
          }
        }
        await kickQueue();
      },
      "Refreshed series metadata and checked for new videos.",
    );

  const onSearchAll = () => {
    if (!source) return;
    if (
      !window.confirm(
        `Queue missing (seen) downloads for ${source.title}?\n\n` +
          `Previously ignored episodes stay ignored. This will not re-flood the queue with ignored items.`,
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
    setEditQuality(source.quality || "");
    setEditMediaType(source.media_type || "video");
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
        quality: editQuality,
        media_type: editMediaType,
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
    setDeleteFiles(false);
    setDeleteOpen(true);
  };

  const confirmDelete = async () => {
    if (!source) return;
    setDeleteOpen(false);
    void runToolbar(
      "delete",
      async () => {
        const result = await api.deleteSource(source.id, { deleteFiles });
        if (result.errors?.length) {
          throw new Error(result.errors.join("; "));
        }
        navigate("/");
      },
      deleteFiles ? "Removed series and deleted files." : "Removed from library (files kept).",
    );
  };

  const uploadsMonitored =
    Boolean(source?.enabled) && source?.monitor_mode !== "none" && source?.monitor_mode !== "video";

  const toggleUploadsMonitor = async () => {
    if (!source) return;
    setBusyKey("uploads-mon");
    setError(null);
    try {
      if (!uploadsMonitored) {
        if (
          !window.confirm(
            `Monitor Uploads for future videos only?\n\n` +
              `Previously ignored episodes stay ignored. Use Search to grab missing (seen) ones.`,
          )
        ) {
          return;
        }
        await api.patchSource(source.id, { enabled: true, monitor_mode: "new" });
        await api.checkSource(source.id);
        await kickQueue();
        setMessage("Uploads monitored — future uploads only.");
      } else {
        await api.patchSource(source.id, { enabled: false, monitor_mode: "none" });
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
    if (!source) return;
    const channelId = source.id;
    setBusyKey(hit.url);
    setError(null);
    setMessage(null);
    try {
      if (existing?.enabled) {
        await api.patchSource(existing.id, { enabled: false });
        setMessage(`Unmonitored ${existing.title}.`);
      } else if (existing) {
        if (
          !window.confirm(
            `Monitor “${existing.title}” for future uploads only?\n\n` +
              `This will NOT re-download previously ignored episodes. ` +
              `Use Search if you want missing (seen) episodes.`,
          )
        ) {
          return;
        }
        await api.patchSource(existing.id, { enabled: true, monitor_mode: "new" });
        // Nest under this channel so it does not get a duplicate library poster
        await api.addSource(hit.url, "new", {
          parent_source_id: channelId,
          title: hit.title,
          yt_id: hit.id,
        });
        await api.checkSource(existing.id);
        await kickQueue();
        setMessage(`Monitoring ${existing.title} — future uploads only.`);
        await loadAlbumTracks(existing.id);
      } else {
        if (
          !window.confirm(
            `Add “${hit.title}” and download the FULL playlist now?\n\n` +
              `Cancel and use Add New → expand the playlist to pick individual episodes instead.`,
          )
        ) {
          return;
        }
        const created = await api.addSource(hit.url, "all", {
          quality: source.quality || "",
          media_type: (source.media_type as "video" | "audio") || "video",
          title: hit.title,
          yt_id: hit.id,
          thumbnail_url: hit.thumbnail_url,
          parent_source_id: channelId,
        });
        await kickQueue();
        setMessage(`Monitoring ${created.title} — downloading.`);
        await loadCore();
        await loadAlbumTracks(created.id);
        setExpandedKeys((prev) => new Set(prev).add(hit.id || hit.url));
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
    return (
      <EpisodeTable>
        {vids.map((v, i) => (
          <TrackMonitorRow
            key={v.id}
            index={vids.length - i}
            title={v.title}
            status={v.status}
            published={v.published_at ? new Date(v.published_at).toLocaleDateString() : null}
            checked={trackIsMonitored(v.status)}
            busy={busyKey === `v-${v.id}`}
            onToggle={() => void toggleTrack(v)}
          />
        ))}
      </EpisodeTable>
    );
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
    source.monitor_mode === "all"
      ? "All"
      : source.monitor_mode === "new"
        ? "Future"
        : source.monitor_mode === "none"
          ? "None"
          : "Video";
  const seasonKeys = isChannel
    ? [...playlists.map((h) => h.id || h.url), "uploads"]
    : ["self"];
  const allSeasonsExpanded =
    seasonKeys.length > 0 && seasonKeys.every((k) => expandedKeys.has(k));

  return (
    <>
      <div className="page-toolbar series-page-toolbar">
        <button className="btn btn-ghost" type="button" onClick={() => navigate("/")}>
          ← Library
        </button>
        <div className="page-toolbar-spacer" />
        <button
          className="btn"
          type="button"
          disabled={busyKey === "refresh"}
          onClick={onRefresh}
          title="Check for new videos and refresh artwork"
        >
          Refresh &amp; Scan
        </button>
        <button
          className="btn"
          type="button"
          disabled={busyKey === "search" || source.monitor_mode === "video"}
          onClick={onSearchAll}
          title="Queue missing downloads"
        >
          Search Monitored
        </button>
        <button
          className="btn"
          type="button"
          onClick={() => setTab("rename")}
          title="Preview and apply Plex-friendly file renames for this series"
        >
          Preview Rename{renameNeeds > 0 ? ` (${renameNeeds})` : ""}
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
          className="btn"
          type="button"
          onClick={openEdit}
          title="Series monitoring & quality"
        >
          Series Monitoring
        </button>
        <button className="btn" type="button" onClick={openEdit} title="Edit series">
          Edit
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

      {error && (
        <div className="error" style={{ whiteSpace: "pre-wrap" }}>
          {error}
        </div>
      )}
      {message && <div className="success">{message}</div>}

      <section
        className="series-hero"
        style={{
          backgroundImage: `linear-gradient(90deg, rgba(10,16,20,0.92) 0%, rgba(10,16,20,0.72) 45%, rgba(10,16,20,0.55) 100%), url(${api.fanartUrl(source.id)})`,
        }}
      >
        <div className="series-hero-inner">
          <div className="channel-hero-art">
            {source.poster_path ? (
              <img src={api.posterUrl(source.id)} alt="" />
            ) : (
              <div className="poster-card-placeholder">No poster</div>
            )}
          </div>
          <div className="channel-hero-body">
            <h1 className="series-hero-title">{source.title}</h1>
            <div className="series-hero-meta muted">
              <span>{isChannel ? "Channel" : "Playlist"}</span>
              <span>·</span>
              <span>
                {source.downloaded_count}/{source.video_count || "—"} on disk
              </span>
              {source.wanted_count > 0 && (
                <>
                  <span>·</span>
                  <span>{source.wanted_count} wanted</span>
                </>
              )}
            </div>
            <div className="series-info-labels">
              <span className="info-label mono" title={source.folder_name}>
                {source.folder_name}
              </span>
              <span className="info-label">
                {qualityLabel(source.quality, source.media_type)}
              </span>
              <span className="info-label">{uploadsMonitored ? "Monitored" : "Unmonitored"}</span>
              <span className="info-label">{source.media_type === "audio" ? "Music" : "Video"}</span>
              <span className="info-label">Monitor: {modeLabel}</span>
            </div>
            <p className="series-hero-blurb muted">
              {isChannel
                ? "Playlists first, Uploads last. Monitor seasons from here anytime — or pick episodes in Add New."
                : "Episodes in this playlist."}
            </p>
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

      {source && !source.initialized && (
        <div className="panel" style={{ marginBottom: "0.75rem" }}>
          <p className="muted" style={{ margin: 0 }}>
            Importing catalog in the background… episodes will appear here shortly. Downloads
            continue in Activity without blocking this page.
          </p>
        </div>
      )}

      {tab === "episodes" &&
        (isChannel ? (
          <section className="panel seasons-panel">
            <div className="section-head">
              <h2>Seasons</h2>
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => {
                  if (allSeasonsExpanded) collapseAllSeasons();
                  else void expandAllSeasons();
                }}
              >
                {allSeasonsExpanded ? "Collapse All" : "Expand All"}
              </button>
            </div>
            <div className="season-list">
              {loadingPlaylists && <p className="muted">Loading playlists…</p>}

              {playlists.map((hit) => {
                const existing = findExistingPlaylist(allSources, hit);
                const key = hit.id || hit.url;
                const monitored = Boolean(existing?.enabled);
                const tracks = existing ? albumTracks[existing.id] || [] : [];
                const downloaded = existing?.downloaded_count ?? 0;
                const total = existing?.video_count || hit.video_count || tracks.length;
                return (
                  <AlbumMonitorRow
                    key={key}
                    title={hit.title}
                    downloaded={downloaded}
                    total={total || 0}
                    detail={albumSubtitle(hit, existing)}
                    monitored={monitored}
                    busy={busyKey === hit.url}
                    expanded={expandedKeys.has(key)}
                    onToggleMonitor={() => void togglePlaylistMonitor(hit, existing)}
                    onToggleExpand={() => {
                      if (existing) void toggleExpand(key, existing);
                      else
                        setExpandedKeys((prev) => {
                          const next = new Set(prev);
                          if (next.has(key)) next.delete(key);
                          else next.add(key);
                          return next;
                        });
                    }}
                  >
                    {existing ? (
                      renderTracks(tracks)
                    ) : (
                      <p className="muted track-empty">
                        Monitor this playlist to download its episodes (or pick them in Add New).
                      </p>
                    )}
                  </AlbumMonitorRow>
                );
              })}

              <AlbumMonitorRow
                title="Uploads"
                downloaded={uploadVideosVisible.filter((v) => v.status === "downloaded").length}
                total={uploadVideosVisible.length}
                detail={
                  playlistOwnedIds.size
                    ? `Hiding ${playlistOwnedIds.size} already in playlists`
                    : source.wanted_count
                      ? `${source.wanted_count} wanted`
                      : undefined
                }
                monitored={uploadsMonitored}
                busy={busyKey === "uploads-mon"}
                expanded={expandedKeys.has("uploads")}
                onToggleMonitor={() => void toggleUploadsMonitor()}
                onToggleExpand={() => void toggleExpand("uploads")}
              >
                {renderTracks(uploadVideosVisible)}
              </AlbumMonitorRow>
            </div>
          </section>
        ) : (
          <section className="panel seasons-panel">
            <div className="section-head">
              <h2>Episodes</h2>
              <span className="muted">
                {source.downloaded_count}/{source.video_count || 0} on disk
              </span>
            </div>
            <div className="season-list">
              <AlbumMonitorRow
                title={source.title}
                downloaded={source.downloaded_count}
                total={source.video_count || uploadVideos.length}
                monitored={uploadsMonitored}
                busy={busyKey === "uploads-mon"}
                expanded={expandedKeys.has("self")}
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
              Organize files for this series ·{" "}
              {renameNeeds ? `${renameNeeds} need renaming` : "all match pattern"} ·{" "}
              <span className="mono">
                {source.media_type === "audio"
                  ? "Artist / Title.ext (MusicBrainz tags)"
                  : "Channel / YYYY-MM-DD - Title [youtubeId].ext"}
              </span>
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
              <div className="field">
                <label htmlFor="edit-quality">
                  {editMediaType === "audio" ? "Music quality" : "Video quality"}
                </label>
                <select
                  id="edit-quality"
                  value={editQuality}
                  onChange={(e) => setEditQuality(e.target.value)}
                >
                  {qualityOptionsFor(editMediaType).map((o) => (
                    <option key={o.value || "default"} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="edit-media">Media type</label>
                <select
                  id="edit-media"
                  value={editMediaType}
                  onChange={(e) => {
                    const next = e.target.value;
                    setEditMediaType(next);
                    setEditQuality((q) => coerceQualityForMedia(q, next));
                  }}
                >
                  {MEDIA_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
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

      {deleteOpen && source && (
        <div className="modal-backdrop" role="presentation" onClick={() => setDeleteOpen(false)}>
          <div
            className="modal-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-series-title"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: 480 }}
          >
            <div className="modal-header">
              <h2 id="delete-series-title">Delete series</h2>
              <button className="btn" type="button" onClick={() => setDeleteOpen(false)}>
                Close
              </button>
            </div>
            <div className="modal-body">
              <p style={{ marginTop: 0 }}>
                Remove <strong>{source.title}</strong> from the library?
                {(source.nested_playlist_count ?? 0) > 0
                  ? ` This also removes ${source.nested_playlist_count} nested playlist season${
                      (source.nested_playlist_count ?? 0) === 1 ? "" : "s"
                    }.`
                  : ""}
              </p>
              <label className="mode-option" style={{ marginBottom: 0 }}>
                <input
                  type="checkbox"
                  checked={deleteFiles}
                  onChange={(e) => setDeleteFiles(e.target.checked)}
                />
                <span>
                  <strong>Delete files</strong>
                  <small>
                    Also remove the channel folder, nested playlist folders, and downloaded
                    videos from disk (
                    <span className="mono">{source.folder_name}</span>).
                  </small>
                </span>
              </label>
            </div>
            <div className="modal-footer">
              <button className="btn" type="button" onClick={() => setDeleteOpen(false)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                type="button"
                disabled={busyKey === "delete"}
                onClick={() => void confirmDelete()}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
