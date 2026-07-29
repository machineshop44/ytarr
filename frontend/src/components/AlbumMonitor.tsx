import type { ReactNode } from "react";
import type { SearchHit, Source } from "../api";

type AlbumMonitorRowProps = {
  title: string;
  /** e.g. file size / extra note shown after progress */
  detail?: string;
  downloaded?: number;
  total?: number;
  monitored: boolean;
  busy?: boolean;
  expanded?: boolean;
  onToggleMonitor: () => void;
  onToggleExpand?: () => void;
  children?: ReactNode;
};

/** Sonarr-style season row: monitor bookmark · title · progress badge · expand. */
export function AlbumMonitorRow({
  title,
  detail,
  downloaded = 0,
  total = 0,
  monitored,
  busy,
  expanded,
  onToggleMonitor,
  onToggleExpand,
  children,
}: AlbumMonitorRowProps) {
  const progressClass =
    total > 0 && downloaded >= total
      ? "season-progress-ok"
      : downloaded > 0
        ? "season-progress-partial"
        : "season-progress-empty";

  return (
    <article
      className={`season-row ${expanded ? "expanded" : ""} ${monitored ? "is-monitored" : ""}`}
    >
      <div className="season-row-main">
        <label
          className="monitor-check season-monitor"
          title={monitored ? "Monitored — click to unmonitor" : "Click to monitor"}
        >
          <input
            type="checkbox"
            checked={monitored}
            disabled={busy}
            onChange={(e) => {
              e.stopPropagation();
              onToggleMonitor();
            }}
          />
          <span className="monitor-bookmark" aria-hidden />
        </label>
        <button
          type="button"
          className="season-row-hit"
          onClick={onToggleExpand}
          disabled={!onToggleExpand}
        >
          <span className="season-title">{title}</span>
          <span className={`season-progress ${progressClass}`}>
            {downloaded} / {total || "—"}
          </span>
          {detail ? <span className="season-detail muted">{detail}</span> : <span />}
          {onToggleExpand && (
            <span className="season-chevron" aria-hidden>
              {expanded ? "▾" : "▸"}
            </span>
          )}
        </button>
      </div>
      {expanded && children != null && <div className="season-episodes">{children}</div>}
    </article>
  );
}

type TrackMonitorRowProps = {
  index: number;
  title: string;
  status: string;
  published?: string | null;
  checked: boolean;
  busy?: boolean;
  onToggle: () => void;
};

/** Sonarr-style episode row inside an expanded season. */
export function TrackMonitorRow({
  index,
  title,
  status,
  published,
  checked,
  busy,
  onToggle,
}: TrackMonitorRowProps) {
  return (
    <tr className={`episode-row ${checked ? "is-monitored" : ""}`}>
      <td className="episode-mon">
        <label className="monitor-check" title={checked ? "Monitored" : "Unmonitored"}>
          <input type="checkbox" checked={checked} disabled={busy} onChange={onToggle} />
          <span className="monitor-bookmark" aria-hidden />
        </label>
      </td>
      <td className="episode-num mono">{index}</td>
      <td className="episode-title">
        <div>{title}</div>
        <div className="episode-status-mobile">
          <span className={`badge ${status}`}>{status}</span>
        </div>
      </td>
      <td className="episode-air mono muted">{published || "—"}</td>
      <td className="episode-status">
        <span className={`badge ${status}`}>{status}</span>
      </td>
    </tr>
  );
}

export function EpisodeTable({ children }: { children: ReactNode }) {
  return (
    <div className="table-wrap episode-table-wrap">
      <table className="episode-table">
        <thead>
          <tr>
            <th className="episode-mon" aria-label="Monitor" />
            <th className="episode-num">#</th>
            <th>Title</th>
            <th>Published</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function albumSubtitle(hit: SearchHit, existing?: Source | null): string {
  const parts: string[] = [];
  if (hit.video_count != null) {
    parts.push(`${hit.video_count} ${hit.video_count === 1 ? "video" : "videos"}`);
  }
  if (existing) {
    parts.push(`${existing.downloaded_count}/${existing.video_count || "—"} on disk`);
    if (existing.wanted_count > 0) parts.push(`${existing.wanted_count} wanted`);
  }
  return parts.join(" · ");
}

/** Episode is selected for download library (Sonarr “monitored”). */
export function trackIsMonitored(status: string): boolean {
  return !["seen", "ignored"].includes(status);
}
