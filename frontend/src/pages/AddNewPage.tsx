import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type SearchHit, type Source } from "../api";
import { AlbumRow, findExistingPlaylist } from "../components/AlbumRow";

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
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<SearchKind>("channel");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [addingUrl, setAddingUrl] = useState<string | null>(null);
  const [addMode, setAddMode] = useState<AddMode>("all");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [added, setAdded] = useState<Source[]>([]);
  const [knownSources, setKnownSources] = useState<Source[]>([]);

  const [browseChannel, setBrowseChannel] = useState<SearchHit | null>(null);
  const [playlists, setPlaylists] = useState<SearchHit[]>([]);
  const [loadingPlaylists, setLoadingPlaylists] = useState(false);

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

  const modeOptions = useMemo(() => {
    if (kind === "video" && !browseChannel) {
      return [{ value: "video" as const, label: "Download this video" }];
    }
    return [
      { value: "all" as const, label: "All — download everything now and monitor" },
      { value: "new" as const, label: "Future — monitor new uploads only" },
    ];
  }, [kind, browseChannel]);

  const onSearch = async (e?: FormEvent) => {
    e?.preventDefault();
    if (query.trim().length < 2) return;
    setSearching(true);
    setError(null);
    setMessage(null);
    setResults([]);
    setBrowseChannel(null);
    setPlaylists([]);
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

  const openPlaylists = async (channel: SearchHit) => {
    setBrowseChannel(channel);
    setLoadingPlaylists(true);
    setError(null);
    setMessage(null);
    setPlaylists([]);
    try {
      const res = await api.channelPlaylists(channel.url, 50);
      setPlaylists(res.results);
      if (!res.results.length) {
        setMessage("No playlists found on this channel. You can still add the channel uploads feed.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingPlaylists(false);
    }
  };

  const closePlaylists = () => {
    setBrowseChannel(null);
    setPlaylists([]);
  };

  const onAdd = async (hit: SearchHit) => {
    setAddingUrl(hit.url);
    setError(null);
    setMessage(null);
    try {
      const mode = hit.kind === "video" ? "video" : addMode;
      const source = await api.addSource(hit.url, mode);
      setAdded((prev) => [source, ...prev.filter((s) => s.id !== source.id)]);
      await kickQueue();
      navigate(api.sourceDetailPath(source.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddingUrl(null);
    }
  };

  const renderHit = (hit: SearchHit, opts?: { showBrowse?: boolean }) => {
    const already =
      monitored.some((s) => s.url === hit.url) || Boolean(findExistingPlaylist(monitored, hit));
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
            {opts?.showBrowse && hit.kind === "channel" && (
              <button
                className="btn"
                type="button"
                disabled={loadingPlaylists}
                onClick={() => void openPlaylists(hit)}
              >
                Browse playlists
              </button>
            )}
            <button
              className="btn btn-primary"
              type="button"
              disabled={already || addingUrl === hit.url}
              onClick={() => void onAdd(hit)}
            >
              {already
                ? "Added"
                : addingUrl === hit.url
                  ? "Adding…"
                  : hit.kind === "channel"
                    ? "Add"
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
          <p>Search YouTube — add a channel or playlist like Series / Artists in the other Arrs.</p>
        </div>
        <Link className="btn" to="/">
          Library
        </Link>
      </div>

      {!browseChannel && (
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

          {kind !== "video" && (
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
        </form>
      )}

      {browseChannel && (
        <div className="panel browse-header">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div className="muted" style={{ fontSize: "0.8rem", marginBottom: "0.25rem" }}>
                Channel playlists
              </div>
              <h2 style={{ margin: 0, fontSize: "1.25rem" }}>{browseChannel.title}</h2>
            </div>
            <button className="btn" type="button" onClick={closePlaylists}>
              ← Back to search
            </button>
          </div>
          <div className="field" style={{ marginTop: "0.9rem", marginBottom: 0 }}>
            <label htmlFor="add-mode-browse">Monitor</label>
            <select
              id="add-mode-browse"
              value={addMode === "video" ? "all" : addMode}
              onChange={(e) => setAddMode(e.target.value as AddMode)}
            >
              <option value="all">All — download everything now and monitor</option>
              <option value="new">Future — monitor new uploads only</option>
            </select>
          </div>
          <div className="row" style={{ marginTop: "0.75rem" }}>
            <button
              className="btn btn-primary"
              type="button"
              disabled={
                monitored.some((s) => s.url === browseChannel.url) ||
                addingUrl === browseChannel.url
              }
              onClick={() => void onAdd(browseChannel)}
            >
              {monitored.some((s) => s.url === browseChannel.url)
                ? "Channel uploads already added"
                : "Add channel uploads"}
            </button>
          </div>
        </div>
      )}

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      {browseChannel ? (
        <div className="album-list">
          {loadingPlaylists && <p className="muted">Loading playlists…</p>}
          {!loadingPlaylists &&
            playlists.map((hit) => (
              <AlbumRow
                key={hit.id || hit.url}
                hit={hit}
                existing={findExistingPlaylist(monitored, hit)}
                busy={addingUrl === hit.url}
                onOpen={(() => {
                  const existing = findExistingPlaylist(monitored, hit);
                  return existing
                    ? () => navigate(api.sourceDetailPath(existing.id))
                    : undefined;
                })()}
                onAdd={() => void onAdd(hit)}
                primaryLabel="Add"
              />
            ))}
        </div>
      ) : (
        <div className="search-results">
          {results.map((hit) => renderHit(hit, { showBrowse: true }))}
        </div>
      )}

      {!browseChannel && !results.length && !searching && !error && (
        <p className="muted">
          Tip: search <strong>Channels</strong>, Add with Monitor <strong>All</strong> to start
          downloading, then open the channel to grab more playlists. Or paste a URL on{" "}
          <Link to="/sources">Sources</Link>.
        </p>
      )}
    </>
  );
}
