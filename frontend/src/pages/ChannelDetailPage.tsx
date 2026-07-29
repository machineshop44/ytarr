import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type SearchHit, type Source, type Video } from "../api";
import {
  AlbumMonitorRow,
  TrackMonitorRow,
  albumSubtitle,
  trackIsMonitored,
} from "../components/AlbumMonitor";
import { findExistingPlaylist } from "../components/playlistMatch";

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
      if (trackIsMonitored(video.status) && video.status !== "downloaded") {
        await api.ignoreVideo(video.id);
      } else if (video.status === "downloaded") {
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
      return <p className="muted track-empty">No videos tracked yet — check the album to scan.</p>;
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

  if (loading && !source) {
    return <p className="muted">Loading…</p>;
  }

  if (!source) {
    return (
      <>
        <div className="error">{error || "Source not found"}</div>
        <Link className="btn" to="/">
          ← Library
        </Link>
      </>
    );
  }

  const isChannel = source.source_type === "channel";

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

      {error && <div className="error">{error}</div>}
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
            <span className="badge">{isChannel ? "artist" : source.source_type}</span>
            <span className="badge">{source.enabled ? "monitored" : "unmonitored"}</span>
          </div>
          <h1 style={{ margin: "0.35rem 0 0.5rem" }}>{source.title}</h1>
          <p className="muted" style={{ margin: 0 }}>
            {isChannel
              ? "Check playlists (albums) and videos (tracks) to download — same idea as Lidarr."
              : "Playlist tracks — check what you want downloaded."}
          </p>
        </div>
      </section>

      {isChannel ? (
        <section className="panel">
          <div className="section-head">
            <h2>Albums</h2>
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

            {loadingPlaylists && <p className="muted">Loading playlists…</p>}

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
                      Check the box to monitor this playlist and download its videos.
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
            <h2>Tracks</h2>
            <span className="muted">
              {source.downloaded_count}/{source.video_count || 0} on disk
            </span>
          </div>
          <div className="album-list">
            <AlbumMonitorRow
              title={source.title}
              subtitle={`${uploadVideos.length} videos`}
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
      )}
    </>
  );
}
