import { useEffect, useState } from "react";
import { api, type DownloadJob } from "../api";

type Tab = "queue" | "history" | "blocklist";

type BlockItem = {
  id: number;
  title: string;
  video_id: string;
  error: string | null;
  source_id: number;
  source_title: string | null;
  updated_at: string | null;
};

function formatWhen(iso: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

type ActivityPageProps = {
  tab?: Tab;
};

export function ActivityPage({ tab = "queue" }: ActivityPageProps) {
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [blocklist, setBlocklist] = useState<BlockItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = async (nextTab = tab) => {
    if (nextTab === "blocklist") {
      const data = await api.blocklist();
      setBlocklist(data.items);
      return;
    }
    const [data, dash] = await Promise.all([
      nextTab === "queue"
        ? api.queue({ status: "active", limit: 200 })
        : api.queue({ status: "history", limit: 100 }),
      api.dashboard(),
    ]);
    setJobs(data);
    setPaused(Boolean(dash.downloads_paused));
  };

  useEffect(() => {
    let alive = true;
    let inFlight = false;
    const tick = async () => {
      if (inFlight || document.hidden) return;
      inFlight = true;
      try {
        if (tab === "blocklist") {
          const data = await api.blocklist();
          if (alive) {
            setBlocklist(data.items);
            setError(null);
          }
        } else {
          const data =
            tab === "queue"
              ? await api.queue({ status: "active", limit: 200 })
              : await api.queue({ status: "history", limit: 100 });
          if (alive) {
            setJobs(data);
            setError(null);
          }
        }
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      } finally {
        inFlight = false;
        if (alive) setLoading(false);
      }
    };
    setLoading(true);
    void tick();
    const id = window.setInterval(tick, tab === "blocklist" ? 10000 : 2500);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [tab]);

  const runAction = (jobId: number, action: () => Promise<unknown>) => {
    setBusyId(jobId);
    void action()
      .then(() => load())
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setBusyId(null));
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            {tab === "queue" ? "Queue" : tab === "history" ? "History" : "Blocklist"}
          </h1>
          <p>
            {tab === "queue"
              ? "Active and queued yt-dlp downloads."
              : tab === "history"
                ? "Recent download history for this instance."
                : "Ignored episodes (permanent skips). Unblock to return them to Seen."}
          </p>
        </div>
        {tab === "queue" && (
          <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              className="btn"
              type="button"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                setMessage(null);
                void (paused ? api.resumeQueue() : api.pauseQueue())
                  .then((r) => {
                    setPaused(r.downloads_paused);
                    setMessage(r.downloads_paused ? "Downloads paused." : "Downloads resumed.");
                    return load();
                  })
                  .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                  .finally(() => setBusy(false));
              }}
            >
              {paused ? "Resume" : "Pause"}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              disabled={busy}
              title="Cancel everything queued and pause downloads"
              onClick={() => {
                if (
                  !window.confirm(
                    "Clear the entire download queue and pause downloads?\n\nQueued items become ignored.",
                  )
                ) {
                  return;
                }
                setBusy(true);
                setMessage(null);
                void api
                  .clearQueue()
                  .then((r) => {
                    setPaused(true);
                    setMessage(`Cleared ${r.cancelled} item(s). Downloads paused.`);
                    return load();
                  })
                  .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                  .finally(() => setBusy(false));
              }}
            >
              Clear queue
            </button>
            <button
              className="btn"
              type="button"
              disabled={busy || paused}
              onClick={() => {
                setBusy(true);
                setMessage(null);
                void api
                  .processQueue()
                  .then(() => {
                    setMessage("Queue processing started.");
                    return load();
                  })
                  .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                  .finally(() => setBusy(false));
              }}
            >
              Process now
            </button>
          </div>
        )}
      </div>

      {paused && tab === "queue" && (
        <div className="error" style={{ marginBottom: "0.75rem" }}>
          Downloads are paused. Free disk space if needed, then click Resume.
        </div>
      )}

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      {tab === "blocklist" ? (
        <div className="panel table-wrap">
          <table>
            <thead>
              <tr>
                <th>Video</th>
                <th>Channel</th>
                <th>Reason</th>
                <th>When</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {blocklist.map((item) => (
                <tr key={item.id}>
                  <td>
                    <div>{item.title}</div>
                    <div className="muted mono">{item.video_id}</div>
                  </td>
                  <td>{item.source_title || "—"}</td>
                  <td className="muted">{item.error || "ignored"}</td>
                  <td className="mono muted">{formatWhen(item.updated_at)}</td>
                  <td>
                    <button
                      className="btn"
                      type="button"
                      disabled={busyId === item.id}
                      onClick={() => {
                        setBusyId(item.id);
                        void api
                          .unblock(item.id)
                          .then(() => load())
                          .catch((err) =>
                            setError(err instanceof Error ? err.message : String(err)),
                          )
                          .finally(() => setBusyId(null));
                      }}
                    >
                      Unblock
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {loading && <p className="muted">Loading…</p>}
          {!loading && !blocklist.length && <p className="muted">Blocklist is empty.</p>}
        </div>
      ) : (
        <div className="panel table-wrap">
          <table>
            <thead>
              <tr>
                <th>Video</th>
                <th>Channel</th>
                <th>Status</th>
                {tab === "queue" ? <th>Progress</th> : <th>When</th>}
                <th />
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>
                    <div>{job.video_title || `Video #${job.video_id}`}</div>
                    <div className="muted mono">{job.youtube_id}</div>
                    {job.error && (
                      <div className="error" style={{ marginTop: 8 }}>
                        {job.error}
                      </div>
                    )}
                  </td>
                  <td>{job.source_title || "—"}</td>
                  <td>
                    <span className={`badge ${job.status}`}>{job.status}</span>
                  </td>
                  {tab === "queue" ? (
                    <td>
                      <div className="progress" title={`${job.progress.toFixed(1)}%`}>
                        <span style={{ width: `${Math.min(100, Math.max(0, job.progress))}%` }} />
                      </div>
                      <div className="muted mono">{job.progress.toFixed(1)}%</div>
                    </td>
                  ) : (
                    <td className="mono muted">
                      {formatWhen(job.finished_at || job.started_at || job.created_at)}
                    </td>
                  )}
                  <td>
                    <div className="row">
                      {(job.status === "failed" || job.status === "cancelled") && (
                        <button
                          className="btn"
                          type="button"
                          disabled={busyId === job.id}
                          onClick={() => runAction(job.id, () => api.retryQueueJob(job.id))}
                        >
                          Retry
                        </button>
                      )}
                      {(job.status === "queued" || job.status === "downloading") && (
                        <button
                          className="btn btn-ghost"
                          type="button"
                          disabled={busyId === job.id}
                          title={
                            job.status === "downloading"
                              ? "Marks ignored; active yt-dlp may still finish"
                              : "Remove from queue"
                          }
                          onClick={() => runAction(job.id, () => api.cancelQueueJob(job.id))}
                        >
                          {job.status === "downloading" ? "Ignore" : "Cancel"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {loading && <p className="muted">Loading…</p>}
          {!loading && !jobs.length && (
            <p className="muted">
              {tab === "queue" ? "Nothing downloading or queued." : "No download history yet."}
            </p>
          )}
        </div>
      )}
    </>
  );
}
