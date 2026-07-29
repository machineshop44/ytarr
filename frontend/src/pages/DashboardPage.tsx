import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Dashboard, type Source } from "../api";
import { PosterCard } from "../components/PosterCard";

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [d, s] = await Promise.all([api.dashboard(), api.sources()]);
        if (!alive) return;
        setData(d);
        setSources(s);
        setError(null);
      } catch (err) {
        if (!alive) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    };
    void load();
    const id = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  // Lidarr artists = channels only. Playlists live inside the channel.
  const channels = sources.filter((s) => s.source_type === "channel");
  const orphanPlaylists = sources.filter((s) => s.source_type === "playlist");

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Library</h1>
          <p>Channels are artists — open one to monitor playlists (albums) and videos (tracks).</p>
        </div>
        <div className="row">
          <Link className="btn btn-primary" to="/add">
            Add New
          </Link>
          <Link className="btn" to="/activity">
            Activity
            {data && data.queue_size > 0 ? ` (${data.queue_size})` : ""}
          </Link>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="stats stats-compact">
        <div className="stat">
          <div className="stat-label">Wanted</div>
          <div className="stat-value">{data?.wanted ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Queue</div>
          <div className="stat-value">{data?.queue_size ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Downloaded</div>
          <div className="stat-value">{data?.downloaded ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Failed</div>
          <div className="stat-value">{data?.failed ?? "—"}</div>
        </div>
      </div>

      {!channels.length && !error && (
        <div className="panel empty-library">
          <h2 style={{ marginTop: 0 }}>No channels yet</h2>
          <p className="muted">
            Add a <strong>channel</strong> (artist). Inside it you can check playlists and videos to
            download — like Lidarr albums and tracks.
          </p>
          <Link className="btn btn-primary" to="/add">
            Add New
          </Link>
          {orphanPlaylists.length > 0 && (
            <p className="muted" style={{ marginTop: "1rem", marginBottom: 0 }}>
              You have {orphanPlaylists.length} playlist
              {orphanPlaylists.length === 1 ? "" : "s"} on{" "}
              <Link to="/sources">Sources</Link>. Add the parent channel so they show as albums under
              that artist.
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
