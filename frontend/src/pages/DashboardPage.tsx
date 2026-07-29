import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Source } from "../api";
import { PosterCard } from "../components/PosterCard";

type SortKey = "title" | "wanted" | "downloaded";
type FilterKey = "all" | "monitored" | "unmonitored" | "wanted";

export function DashboardPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sort, setSort] = useState<SortKey>("title");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [query, setQuery] = useState("");

  const load = async () => {
    setSources(await api.sources());
  };

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        await load();
        if (alive) setError(null);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      }
    };
    void tick();
    const id = window.setInterval(tick, 5000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const channels = useMemo(() => {
    let list = sources.filter((s) => s.source_type === "channel");
    const q = query.trim().toLowerCase();
    if (q) list = list.filter((s) => s.title.toLowerCase().includes(q));
    if (filter === "monitored") list = list.filter((s) => s.enabled);
    if (filter === "unmonitored") list = list.filter((s) => !s.enabled);
    if (filter === "wanted") list = list.filter((s) => s.wanted_count > 0);
    list = [...list].sort((a, b) => {
      if (sort === "wanted") return b.wanted_count - a.wanted_count || a.title.localeCompare(b.title);
      if (sort === "downloaded")
        return b.downloaded_count - a.downloaded_count || a.title.localeCompare(b.title);
      return a.title.localeCompare(b.title);
    });
    return list;
  }, [sources, sort, filter, query]);

  const orphanPlaylists = sources.filter((s) => s.source_type === "playlist");

  const refreshAll = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.checkAllSources();
      await api.processQueue();
      await load();
      setMessage(`Checked ${result.checked} monitored source(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const refreshArtworkAll = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const channelsOnly = sources.filter((s) => s.source_type === "channel");
      for (const ch of channelsOnly) {
        try {
          await api.refreshArtwork(ch.id);
        } catch {
          /* continue */
        }
      }
      await load();
      setMessage(`Refreshed artwork for ${channelsOnly.length} channel(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-toolbar">
        <button className="btn" type="button" disabled={busy} onClick={() => void refreshAll()}>
          {busy ? "Working…" : "Update All"}
        </button>
        <button
          className="btn"
          type="button"
          disabled={busy}
          onClick={() => void refreshArtworkAll()}
        >
          Refresh Art
        </button>
        <Link className="btn btn-primary" to="/add">
          Add New
        </Link>
        <div className="page-toolbar-spacer" />
        <input
          className="toolbar-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search library"
          aria-label="Search library"
        />
        <select
          className="toolbar-select"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          aria-label="Sort"
        >
          <option value="title">Sort: Title</option>
          <option value="wanted">Sort: Wanted</option>
          <option value="downloaded">Sort: Downloaded</option>
        </select>
        <select
          className="toolbar-select"
          value={filter}
          onChange={(e) => setFilter(e.target.value as FilterKey)}
          aria-label="Filter"
        >
          <option value="all">Filter: All</option>
          <option value="monitored">Monitored</option>
          <option value="unmonitored">Unmonitored</option>
          <option value="wanted">Has wanted</option>
        </select>
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      {!channels.length && !error && (
        <div className="panel empty-library">
          <h2 style={{ marginTop: 0 }}>No channels yet</h2>
          <p className="muted">
            Add a <strong>channel</strong> (series). Pick seasons (playlists) and episodes (videos)
            like Lidarr albums/tracks — members-only videos stay hidden.
          </p>
          <Link className="btn btn-primary" to="/add">
            Add New
          </Link>
          {orphanPlaylists.length > 0 && (
            <p className="muted" style={{ marginTop: "1rem", marginBottom: 0 }}>
              You have {orphanPlaylists.length} playlist
              {orphanPlaylists.length === 1 ? "" : "s"} on{" "}
              <Link to="/sources">Sources</Link>. Add the parent channel so they show under that
              series.
            </p>
          )}
        </div>
      )}

      {channels.length > 0 && (
        <section className="library-section">
          <div className="poster-grid">
            {channels.map((source) => (
              <PosterCard key={source.id} source={source} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}
