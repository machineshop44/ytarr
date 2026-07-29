import type { ReactNode } from "react";
import type { SearchHit, Source } from "../api";

type AlbumMonitorRowProps = {
  title: string;
  subtitle?: string;
  thumbnailUrl?: string | null;
  monitored: boolean;
  busy?: boolean;
  expanded?: boolean;
  onToggleMonitor: () => void;
  onToggleExpand?: () => void;
  children?: ReactNode;
};

/** Lidarr-style album row: monitor check + expand for tracks. */
export function AlbumMonitorRow({
  title,
  subtitle,
  thumbnailUrl,
  monitored,
  busy,
  expanded,
  onToggleMonitor,
  onToggleExpand,
  children,
}: AlbumMonitorRowProps) {
  return (
    <article className={`album-monitor ${expanded ? "expanded" : ""} ${monitored ? "is-monitored" : ""}`}>
      <div className="album-monitor-main">
        <label className="monitor-check" title={monitored ? "Monitored — click to unmonitor" : "Click to monitor & download"}>
          <input
            type="checkbox"
            checked={monitored}
            disabled={busy}
            onChange={(e) => {
              e.stopPropagation();
              onToggleMonitor();
            }}
          />
          <span className="monitor-check-box" aria-hidden />
        </label>
        <button
          type="button"
          className="album-monitor-hit"
          onClick={onToggleExpand}
          disabled={!onToggleExpand}
        >
          {thumbnailUrl ? (
            <img className="album-thumb" src={thumbnailUrl} alt="" />
          ) : (
            <div className="album-thumb placeholder">—</div>
          )}
          <div className="album-body">
            <div className="album-title-row">
              <h3>{title}</h3>
              {monitored && <span className="badge">monitored</span>}
            </div>
            {subtitle && <div className="source-meta">{subtitle}</div>}
          </div>
          {onToggleExpand && (
            <span className="album-chevron" aria-hidden>
              {expanded ? "▾" : "▸"}
            </span>
          )}
        </button>
      </div>
      {expanded && children && <div className="album-tracks">{children}</div>}
    </article>
  );
}

type TrackMonitorRowProps = {
  title: string;
  status: string;
  published?: string | null;
  checked: boolean;
  busy?: boolean;
  onToggle: () => void;
};

export function TrackMonitorRow({
  title,
  status,
  published,
  checked,
  busy,
  onToggle,
}: TrackMonitorRowProps) {
  return (
    <label className={`track-monitor ${checked ? "is-wanted" : ""}`}>
      <input type="checkbox" checked={checked} disabled={busy} onChange={onToggle} />
      <span className="monitor-check-box" aria-hidden />
      <span className="track-monitor-body">
        <span className="track-title">{title}</span>
        <span className="track-meta">
          <span className="badge">{status}</span>
          {published && <span className="muted">{published}</span>}
        </span>
      </span>
    </label>
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

/** Track is selected for download library (Lidarr “monitored”). */
export function trackIsMonitored(status: string): boolean {
  return !["seen", "ignored"].includes(status);
}
