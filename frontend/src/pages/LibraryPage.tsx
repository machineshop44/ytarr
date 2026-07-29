import { useEffect, useState } from "react";
import { api, type Video } from "../api";

export function LibraryPage() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [status, setStatus] = useState("downloaded");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = async (nextStatus = status) => {
    setVideos(await api.videos(nextStatus === "all" ? undefined : { status: nextStatus }));
  };

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [status]);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Videos</h1>
          <p>Tracked videos by status. Identity is YouTube video id, not title.</p>
        </div>
        <select
          style={{ width: 180 }}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="downloaded">Downloaded</option>
          <option value="wanted">Wanted</option>
          <option value="failed">Failed</option>
          <option value="seen">Seen (not downloaded)</option>
          <option value="ignored">Ignored</option>
          <option value="all">All</option>
        </select>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Source</th>
              <th>Status</th>
              <th>Published</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {videos.map((video) => (
              <tr key={video.id}>
                <td>
                  <div>{video.title}</div>
                  <div className="muted mono">{video.video_id}</div>
                  {video.error && <div className="error" style={{ marginTop: 8 }}>{video.error}</div>}
                </td>
                <td>{video.source_title || "—"}</td>
                <td>
                  <span className={`badge ${video.status}`}>{video.status}</span>
                </td>
                <td className="mono">
                  {video.published_at ? new Date(video.published_at).toLocaleDateString() : "—"}
                </td>
                <td>
                  <div className="row">
                    {(video.status === "failed" || video.status === "ignored" || video.status === "seen") && (
                      <button
                        className="btn"
                        type="button"
                        disabled={busyId === video.id}
                        onClick={() => {
                          setBusyId(video.id);
                          void api
                            .retryVideo(video.id)
                            .then(() => load())
                            .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                            .finally(() => setBusyId(null));
                        }}
                      >
                        Download
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
                            .catch((err) => setError(err instanceof Error ? err.message : String(err)))
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
        {!videos.length && <p className="muted">No videos in this view.</p>}
      </div>
    </>
  );
}
