import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Video } from "../api";

type LibraryPageProps = {
  defaultStatus?: string;
};

export function LibraryPage({ defaultStatus = "wanted" }: LibraryPageProps) {
  const [searchParams] = useSearchParams();
  const statusFromQuery = searchParams.get("status");
  const [videos, setVideos] = useState<Video[]>([]);
  const [status, setStatus] = useState(statusFromQuery || defaultStatus);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [busyAll, setBusyAll] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setStatus(statusFromQuery || defaultStatus);
  }, [defaultStatus, statusFromQuery]);

  const load = async (nextStatus = status) => {
    setVideos(await api.videos(nextStatus === "all" ? undefined : { status: nextStatus }));
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setVideos([]);
    void api
      .videos(status === "all" ? undefined : { status })
      .then((rows) => {
        if (!alive) return;
        setVideos(rows);
        setError(null);
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [status]);

  const searchAll = async () => {
    setBusyAll(true);
    setError(null);
    setMessage(null);
    try {
      await api.processQueue();
      await load();
      setMessage("Queue processing started.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyAll(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            {status === "cutoff"
              ? "Cutoff Unmet"
              : status === "failed"
                ? "Failed"
                : "Wanted"}
          </h1>
          <p>
            {status === "cutoff"
              ? "Quality-upgrade requeues — change a series Quality to bump downloaded episodes here."
              : status === "failed"
                ? "Downloads that failed — retry or ignore."
              : "Wanted / failed videos — Sonarr Wanted for YouTube. Identity is the video id, not the title."}
          </p>
        </div>
        <div className="row">
          <button className="btn" type="button" disabled={busyAll} onClick={() => void searchAll()}>
            Process queue
          </button>
          <select
            className="toolbar-select"
            style={{ width: 180 }}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="wanted">Wanted</option>
            <option value="cutoff">Cutoff Unmet</option>
            <option value="failed">Failed</option>
            <option value="seen">Seen (not downloaded)</option>
            <option value="ignored">Ignored</option>
            <option value="downloaded">Downloaded</option>
            <option value="all">All</option>
          </select>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>Channel / playlist</th>
              <th>Episode</th>
              <th>Status</th>
              <th>Published</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {videos.map((video) => (
              <tr key={video.id}>
                <td>
                  <Link to={api.sourceDetailPath(video.source_id)}>
                    {video.source_title || `Source #${video.source_id}`}
                  </Link>
                </td>
                <td>
                  <div>{video.title}</div>
                  <div className="muted mono">{video.video_id}</div>
                  {video.error && (
                    <div className="error" style={{ marginTop: 8 }}>
                      {video.error}
                    </div>
                  )}
                </td>
                <td>
                  <span className={`badge ${video.status}`}>{video.status}</span>
                </td>
                <td className="mono">
                  {video.published_at ? new Date(video.published_at).toLocaleDateString() : "—"}
                </td>
                <td>
                  <div className="row">
                    {(video.status === "failed" ||
                      video.status === "ignored" ||
                      video.status === "seen" ||
                      video.status === "wanted") && (
                      <button
                        className="btn"
                        type="button"
                        disabled={busyId === video.id}
                        onClick={() => {
                          setBusyId(video.id);
                          void api
                            .retryVideo(video.id)
                            .then(() => api.processQueue())
                            .then(() => load())
                            .catch((err) =>
                              setError(err instanceof Error ? err.message : String(err)),
                            )
                            .finally(() => setBusyId(null));
                        }}
                      >
                        Retry
                      </button>
                    )}
                    {video.status !== "ignored" && video.status !== "downloaded" && (
                      <button
                        className="btn btn-ghost"
                        type="button"
                        disabled={busyId === video.id}
                        onClick={() => {
                          setBusyId(video.id);
                          void api
                            .ignoreVideo(video.id)
                            .then(() => load())
                            .catch((err) =>
                              setError(err instanceof Error ? err.message : String(err)),
                            )
                            .finally(() => setBusyId(null));
                        }}
                      >
                        Ignore
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <p className="muted">Loading…</p>}
        {!loading && !videos.length && <p className="muted">No videos in this view.</p>}
      </div>
    </>
  );
}
