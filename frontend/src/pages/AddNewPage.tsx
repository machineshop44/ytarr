import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type SearchHit, type Source } from "../api";
import { ChannelAddModal } from "../components/ChannelAddModal";
import { findExistingPlaylist } from "../components/playlistMatch";
import { MEDIA_TYPE_OPTIONS, coerceQualityForMedia, qualityOptionsFor } from "../qualityOptions";

type SearchKind = "channel" | "playlist" | "video";
type AddMode = "new" | "all" | "video";

/** "Artist - Song" / "Artist: Song" style queries → prefer video/song results. */
function looksLikeTrackQuery(q: string): boolean {
  const t = q.trim();
  if (t.length < 3) return false;
  if (/^".+"$/.test(t)) return true;
  return /\s[-–—:]\s/.test(t);
}

function defaultKindForMedia(mediaType: "video" | "audio"): SearchKind {
  return mediaType === "audio" ? "video" : "channel";
}

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
  // Fire-and-forget — /queue/process starts a background worker and returns immediately
  void api.processQueue().catch(() => undefined);
}

function SearchSkeleton() {
  return (
    <div className="search-results" aria-busy="true" aria-live="polite">
      <p className="muted search-status">Searching YouTube…</p>
      {Array.from({ length: 5 }, (_, i) => (
        <article key={i} className="search-card search-card-skeleton">
          <div className="search-thumb skeleton-block" />
          <div className="search-body">
            <div className="skeleton-line skeleton-line-title" />
            <div className="skeleton-line skeleton-line-meta" />
            <div className="skeleton-line skeleton-line-meta short" />
          </div>
        </article>
      ))}
    </div>
  );
}

export function AddNewPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState(() => searchParams.get("q") || "");
  const [mediaType, setMediaType] = useState<"video" | "audio">("video");
  const [kind, setKind] = useState<SearchKind>(() => {
    const q = searchParams.get("q") || "";
    const paramKind = searchParams.get("kind");
    if (paramKind === "channel" || paramKind === "playlist" || paramKind === "video") {
      return paramKind;
    }
    return looksLikeTrackQuery(q) ? "video" : "channel";
  });
  const [results, setResults] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [addingUrl, setAddingUrl] = useState<string | null>(null);
  const [addMode, setAddMode] = useState<AddMode>("all");
  const [quality, setQuality] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [added, setAdded] = useState<Source[]>([]);
  const [knownSources, setKnownSources] = useState<Source[]>([]);
  const [pickerChannel, setPickerChannel] = useState<SearchHit | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const monitored = useMemo(() => {
    const byId = new Map<number, Source>();
    for (const s of [...knownSources, ...added]) byId.set(s.id, s);
    return [...byId.values()];
  }, [knownSources, added]);

  const kindLabels = useMemo(() => {
    if (mediaType === "audio") {
      return {
        channel: "Artists (channels)",
        playlist: "Playlists",
        video: "Songs (videos)",
      };
    }
    return {
      channel: "Channels",
      playlist: "Playlists",
      video: "Videos",
    };
  }, [mediaType]);

  const placeholder =
    mediaType === "audio"
      ? kind === "video"
        ? "Song or Artist - Title…"
        : kind === "channel"
          ? "Artist or channel name…"
          : "Playlist name…"
      : kind === "video"
        ? "Video title or paste a URL…"
        : kind === "channel"
          ? "Channel name…"
          : "Playlist name…";

  useEffect(() => {
    void api
      .sources()
      .then(setKnownSources)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const q = searchParams.get("q");
    if (!q || q.trim().length < 2) return;
    const paramKind = searchParams.get("kind");
    let nextKind: SearchKind = "channel";
    if (paramKind === "channel" || paramKind === "playlist" || paramKind === "video") {
      nextKind = paramKind;
    } else if (looksLikeTrackQuery(q)) {
      nextKind = "video";
    }
    setQuery(q);
    setKind(nextKind);
    setAddMode(defaultModeForKind(nextKind));
    void runSearch(q.trim(), nextKind);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- topbar deep-link only
  }, [searchParams]);

  const runSearch = async (q: string, searchKind: SearchKind, infoNote?: string | null) => {
    setSearching(true);
    setError(null);
    setMessage(null);
    setResults([]);
    setPickerChannel(null);
    setHasSearched(true);
    try {
      const res = await api.search(q, searchKind, searchKind === "video" ? 18 : 12);
      setResults(res.results);
      setAddMode(defaultModeForKind(searchKind));
      if (!res.results.length) {
        setMessage(
          searchKind === "video"
            ? "No songs/videos found. Try Artist - Title, or switch Looking for to Artists."
            : searchKind === "channel"
              ? "No channels found. For a specific song, switch Looking for to Songs/Videos."
              : "No results. Try a different query or kind.",
        );
      } else if (infoNote) {
        setMessage(infoNote);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  };

  const onSearch = async (e?: FormEvent) => {
    e?.preventDefault();
    const q = query.trim();
    if (q.length < 2) return;
    let searchKind = kind;
    let infoNote: string | null = null;
    // Song-style query while filtering channels → flip to videos automatically
    if (looksLikeTrackQuery(q) && searchKind === "channel") {
      searchKind = "video";
      setKind("video");
      infoNote = "Treated as a song/video search (Artist - Title).";
    }
    await runSearch(q, searchKind, infoNote);
  };

  const onMediaTypeChange = (next: "video" | "audio") => {
    setMediaType(next);
    setQuality((q) => coerceQualityForMedia(q, next));
    const nextKind = defaultKindForMedia(next);
    setKind(nextKind);
    setAddMode(defaultModeForKind(nextKind));
    setResults([]);
    setMessage(null);
    setHasSearched(false);
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
        title: hit.title,
        yt_id: hit.id,
        thumbnail_url: hit.thumbnail_url,
        channel: hit.channel,
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
      const channelMode = selection.monitorUploads
        ? selection.uploadVideoIds != null
          ? "none"
          : "all"
        : "none";
      const channelSource = await api.addSource(pickerChannel.url, channelMode, {
        quality,
        media_type: mediaType,
        title: pickerChannel.title,
        yt_id: pickerChannel.id,
        thumbnail_url: pickerChannel.thumbnail_url,
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
          quality,
          media_type: mediaType,
          title: hit.title,
          yt_id: hit.id,
          thumbnail_url: hit.thumbnail_url,
          parent_source_id: channelSource.id,
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
            await api.addSource(hit.url, playlistMode, playlistOpts);
          } else {
            await api.backfillSource(pl.id, false);
            // Ensure nesting even if playlist already existed
            await api.addSource(hit.url, playlistMode, {
              parent_source_id: channelSource.id,
              title: hit.title,
              yt_id: hit.id,
            });
          }
        } else if (videoIds != null) {
          await api.addSource(hit.url, playlistMode, playlistOpts);
        } else {
          await api.addSource(hit.url, "all", {
            parent_source_id: channelSource.id,
            title: hit.title,
            yt_id: hit.id,
          });
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
    const kindBadge =
      mediaType === "audio"
        ? hit.kind === "video"
          ? "song"
          : hit.kind === "channel"
            ? "artist"
            : hit.kind
        : hit.kind;
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
            <span className="badge">{kindBadge}</span>
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
                    : hit.kind === "video" && mediaType === "audio"
                      ? "Add song"
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
            {mediaType === "audio"
              ? "Search songs by title (Artist - Song) or find an artist channel — music extracts to your music library."
              : "Search channels, playlists, or individual videos — then pick seasons/episodes like Sonarr."}
          </p>
        </div>
        <Link className="btn" to="/">
          Library
        </Link>
      </div>

      <form className="panel" onSubmit={(e) => void onSearch(e)}>
        <div className="row search-bar">
          <div className="grow">
            <label htmlFor="yt-search">Search YouTube</label>
            <input
              id="yt-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={placeholder}
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
                setResults([]);
                setHasSearched(false);
              }}
            >
              <option value="video">{kindLabels.video}</option>
              <option value="channel">{kindLabels.channel}</option>
              <option value="playlist">{kindLabels.playlist}</option>
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
              <option value="all">All — download everything now and monitor</option>
              <option value="new">Future — monitor new uploads only</option>
            </select>
          </div>
        )}

        <div className="row" style={{ marginTop: "0.75rem", gap: "0.75rem" }}>
          <div className="field grow" style={{ marginBottom: 0 }}>
            <label htmlFor="add-quality">{mediaType === "audio" ? "Music quality" : "Video quality"}</label>
            <select
              id="add-quality"
              value={quality}
              onChange={(e) => setQuality(e.target.value)}
            >
              {qualityOptionsFor(mediaType).map((o) => (
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
              onChange={(e) => onMediaTypeChange(e.target.value as "video" | "audio")}
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
            Tip: for a single track use <strong>Songs</strong> and search{" "}
            <span className="mono">Yungblud - Changes</span>. Use <strong>Artists</strong> to add
            their channel and pick albums later.
          </p>
        )}
      </form>

      {error && <div className="error">{error}</div>}
      {message && !searching && <div className="success">{message}</div>}

      {searching && <SearchSkeleton />}

      {!searching && results.length > 0 && (
        <div className="search-results">{results.map((hit) => renderHit(hit))}</div>
      )}

      {!results.length && !searching && !error && !hasSearched && (
        <p className="muted">
          {mediaType === "audio" ? (
            <>
              Switch <strong>Looking for</strong> between Songs and Artists. Leave{" "}
              <strong>Uploads</strong> unchecked when adding an artist unless you want their full
              feed.
            </>
          ) : (
            <>
              Tip: leave <strong>Uploads</strong> unchecked unless you want the channel feed. Expand
              a playlist and tick only the episodes you want — like Sonarr seasons/episodes.
            </>
          )}
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
