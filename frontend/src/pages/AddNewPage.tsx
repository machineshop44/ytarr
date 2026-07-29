import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type SearchHit, type Source } from "../api";
import { ChannelAddModal } from "../components/ChannelAddModal";
import { findExistingPlaylist } from "../components/playlistMatch";
import { MEDIA_TYPE_OPTIONS, QUALITY_OPTIONS } from "../qualityOptions";

type SearchKind = "channel" | "playlist" | "video";
type AddMode = "new" | "all" | "video";

function defaultModeForKind(kind: SearchKind): AddMode {
  if (kind === "video") return "video";
  return "all";
}

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

async function kickQueue() {
  try {
    await api.processQueue();
  } catch {
    /* scheduler will catch up */
  }
}

export function AddNewPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState(() => searchParams.get("q") || "");
  const [kind, setKind] = useState<SearchKind>("channel");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [addingUrl, setAddingUrl] = useState<string | null>(null);
  const [addMode, setAddMode] = useState<AddMode>("all");
  const [quality, setQuality] = useState("");
  const [mediaType, setMediaType] = useState<"video" | "audio">("video");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [added, setAdded] = useState<Source[]>([]);
  const [knownSources, setKnownSources] = useState<Source[]>([]);
  const [pickerChannel, setPickerChannel] = useState<SearchHit | null>(null);
  const [confirming, setConfirming] = useState(false);

  const monitored = useMemo(() => {
    const byId = new Map<number, Source>();
    for (const s of [...knownSources, ...added]) byId.set(s.id, s);
    return [...byId.values()];
  }, [knownSources, added]);

  useEffect(() => {
    void api
      .sources()
      .then(setKnownSources)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const q = searchParams.get("q");
    if (q && q.trim().length >= 2) {
      setQuery(q);
      void (async () => {
        setSearching(true);
        setError(null);
        try {
          const res = await api.search(q.trim(), "channel", 12);
          setResults(res.results);
          setAddMode(defaultModeForKind("channel"));
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err));
        } finally {
          setSearching(false);
        }
      })();
    }
  }, [searchParams]);

  const modeOptions = useMemo(() => {
    if (kind === "video") {
      return [{ value: "video" as const, label: "Download this video" }];
    }
    return [
      { value: "all" as const, label: "All — download everything now and monitor" },
      { value: "new" as const, label: "Future — monitor new uploads only" },
    ];
  }, [kind]);

  const onSearch = async (e?: FormEvent) => {
    e?.preventDefault();
    if (query.trim().length < 2) return;
    setSearching(true);
    setError(null);
    setMessage(null);
    setResults([]);
    setPickerChannel(null);
    try {
      const res = await api.search(query.trim(), kind, 12);
      setResults(res.results);
      setAddMode(defaultModeForKind(kind));
      if (!res.results.length) setMessage("No results. Try a different query or kind.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  };

  const onAdd = async (hit: SearchHit) => {
    if (hit.kind === "channel") {
      setPickerChannel(hit);
      return;
    }
    setAddingUrl(hit.url);
    setError(null);
    setMessage(null);
    try {
      const mode = hit.kind === "video" ? "video" : addMode;
      const source = await api.addSource(hit.url, mode, {
        quality,
        media_type: mediaType,
      });
      setAdded((prev) => [source, ...prev.filter((s) => s.id !== source.id)]);
      await kickQueue();
      navigate(api.sourceDetailPath(source.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddingUrl(null);
    }
  };

  const onConfirmChannel = async (selection: {
    monitorUploads: boolean;
    uploadVideoIds: string[] | null;
    playlists: { hit: SearchHit; videoIds: string[] | null }[];
  }) => {
    if (!pickerChannel) return;
    setConfirming(true);
    setError(null);
    try {
      // Sonarr-like: unchecked Uploads → structure only (none). Checked + all → all.
      // Checked + episode picks → only those ids (server ignores the rest).
      const channelMode = selection.monitorUploads
        ? selection.uploadVideoIds != null
          ? "none"
          : "all"
        : "none";
      const baseOpts = {
        quality,
        media_type: mediaType,
        title: pickerChannel.title,
        yt_id: pickerChannel.id,
        thumbnail_url: pickerChannel.thumbnail_url,
      };
      const channelSource = await api.addSource(pickerChannel.url, channelMode, {
        ...baseOpts,
        ...(selection.monitorUploads && selection.uploadVideoIds != null
          ? { wanted_video_ids: selection.uploadVideoIds }
          : {}),
      });
      setAdded((prev) => [channelSource, ...prev.filter((s) => s.id !== channelSource.id)]);

      for (const { hit, videoIds } of selection.playlists) {
        const existing = findExistingPlaylist(
          [...knownSources, channelSource, ...added],
          hit,
        );
        let pl = existing;
        const playlistMode = videoIds != null ? "none" : "all";
        const playlistOpts = {
          ...baseOpts,
          ...(videoIds != null ? { wanted_video_ids: videoIds } : {}),
        };
        if (!pl) {
          pl = await api.addSource(hit.url, playlistMode, playlistOpts);
        } else if (!pl.enabled) {
          await api.patchSource(pl.id, {
            enabled: true,
            monitor_mode: playlistMode,
            quality,
            media_type: mediaType,
          });
          if (videoIds != null) {
            // Re-apply selection without pulling ignored via backfill
            await api.addSource(hit.url, playlistMode, playlistOpts);
          } else {
            await api.backfillSource(pl.id, false);
          }
        } else if (videoIds != null) {
          await api.addSource(hit.url, playlistMode, playlistOpts);
        } else {
          await api.checkSource(pl.id);
        }
        setAdded((prev) => [pl!, ...prev.filter((s) => s.id !== pl!.id)]);
      }

      await kickQueue();
      setPickerChannel(null);
      navigate(api.sourceDetailPath(channelSource.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setConfirming(false);
    }
  };

  const renderHit = (hit: SearchHit) => {
    const already = monitored.some((s) => s.url === hit.url);
    return (
      <article key={`${hit.kind}-${hit.id || hit.url}`} className="search-card">
        {hit.thumbnail_url ? (
          <img className="search-thumb" src={hit.thumbnail_url} alt="" />
        ) : (
          <div className="search-thumb placeholder">No art</div>
        )}
        <div className="search-body">
          <div className="search-title-row">
            <h3>{hit.title}</h3>
            <span className="badge">{hit.kind}</span>
          </div>
          <div className="source-meta">
            {hit.channel && <span>{hit.channel}</span>}
            {hit.video_count != null && (
              <span>
                {hit.video_count} {hit.video_count === 1 ? "video" : "videos"}
              </span>
            )}
            {hit.duration != null && <span>{formatDuration(hit.duration)}</span>}
          </div>
          {hit.description && <p className="muted search-desc">{hit.description}</p>}
          <div className="row">
            <button
              className="btn btn-primary"
              type="button"
              disabled={
                (hit.kind !== "channel" && already) ||
                addingUrl === hit.url ||
                confirming
              }
              onClick={() => void onAdd(hit)}
            >
              {hit.kind === "channel"
                ? already
                  ? "Manage…"
                  : "Add…"
                : already
                  ? "In library"
                  : addingUrl === hit.url
                    ? "Adding…"
                    : "Add"}
            </button>
          </div>
        </div>
      </article>
    );
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Add New</h1>
          <p>
            Search for a channel, then pick seasons (playlists) and episodes (videos) — like Sonarr.
          </p>
        </div>
        <Link className="btn" to="/">
          Library
        </Link>
      </div>

      <form className="panel" onSubmit={onSearch}>
        <div className="row search-bar">
          <div className="grow">
            <label htmlFor="yt-search">Search YouTube</label>
            <input
              id="yt-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Channel, playlist, or video…"
              disabled={searching}
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="yt-kind">Looking for</label>
            <select
              id="yt-kind"
              value={kind}
              disabled={searching}
              onChange={(e) => {
                const next = e.target.value as SearchKind;
                setKind(next);
                setAddMode(defaultModeForKind(next));
              }}
            >
              <option value="channel">Channels</option>
              <option value="playlist">Playlists</option>
              <option value="video">Videos</option>
            </select>
          </div>
          <button
            className="btn btn-primary"
            type="submit"
            disabled={searching || query.trim().length < 2}
          >
            {searching ? "Searching…" : "Search"}
          </button>
        </div>

        {kind === "playlist" && (
          <div className="field" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
            <label htmlFor="add-mode">Monitor</label>
            <select
              id="add-mode"
              value={addMode}
              onChange={(e) => setAddMode(e.target.value as AddMode)}
            >
              {modeOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="row" style={{ marginTop: "0.75rem", gap: "0.75rem" }}>
          <div className="field grow" style={{ marginBottom: 0 }}>
            <label htmlFor="add-quality">Quality</label>
            <select
              id="add-quality"
              value={quality}
              onChange={(e) => setQuality(e.target.value)}
            >
              {QUALITY_OPTIONS.map((o) => (
                <option key={o.value || "default"} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field grow" style={{ marginBottom: 0 }}>
            <label htmlFor="add-media-type">Media type</label>
            <select
              id="add-media-type"
              value={mediaType}
              onChange={(e) => setMediaType(e.target.value as "video" | "audio")}
            >
              {MEDIA_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {mediaType === "audio" && (
          <p className="muted" style={{ margin: "0.5rem 0 0", fontSize: "0.82rem" }}>
            Music mode strips audio (m4a) into the music library — useful for one-off songs from
            music videos.
          </p>
        )}
      </form>

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      <div className="search-results">{results.map((hit) => renderHit(hit))}</div>

      {!results.length && !searching && !error && (
        <p className="muted">
          Tip: leave <strong>Uploads</strong> unchecked unless you want the channel feed. Expand a
          playlist and tick only the episodes you want — like Sonarr seasons/episodes. Members-only
          videos are hidden.
        </p>
      )}

      {pickerChannel && (
        <ChannelAddModal
          channel={pickerChannel}
          busy={confirming}
          onClose={() => !confirming && setPickerChannel(null)}
          onConfirm={(sel) => void onConfirmChannel(sel)}
        />
      )}
    </>
  );
}
