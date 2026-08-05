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
  const [busyId, setBusyId] = useState<number | null>(null);
  const [busyAll, setBusyAll] = useState(false);

  const load = async (nextStatus = status) => {
    setVideos(await api.videos(nextStatus === "all" ? undefined : { status: nextStatus }));
  };

  useEffect(() => {
    setStatus(statusFromQuery || defaultStatus);
  }, [defaultStatus, statusFromQuery]);

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [status]);

  const searchAll = async () => {
    setBusyAll(true);
    setError(null);
    try {
      await api.processQueue();
      await load();
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
          <h1>Missing</h1>
          <p>
            Wanted / missing videos — Sonarr Wanted for YouTube. Identity is the video id, not the
            title.
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
            <option value="failed">Failed</option>
            <option value="seen">Seen (not downloaded)</option>
            <option value="ignored">Ignored</option>
            <option value="downloaded">Downloaded</option>
            <option value="all">All</option>
          </select>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

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
                        Search
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
                        Unmonitor
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!videos.length && <p className="muted">No videos in this view.</p>}
      </div>
    </>
  );
}
