import { Link } from "react-router-dom";
import { api, type Source } from "../api";

type PosterCardProps = {
  source: Source;
};

function qualityLabel(quality: string | undefined): string {
  const q = (quality || "").trim();
  if (!q || q === "best") return "Any";
  return q;
}

export function PosterCard({ source }: PosterCardProps) {
  const progress =
    source.video_count > 0
      ? `${source.downloaded_count}/${source.video_count}`
      : `${source.downloaded_count} dl`;
  const kindLabel =
    source.media_type === "audio"
      ? source.source_type === "video"
        ? "Song"
        : "Music"
      : source.source_type === "video"
        ? "Video"
        : source.source_type === "playlist"
          ? "Playlist"
          : "Channel";
  const monitored =
    source.enabled && source.monitor_mode !== "none" && source.monitor_mode !== "video";
  const statusClass = !monitored
    ? "poster-status-off"
    : source.wanted_count > 0
      ? "poster-status-wanted"
      : "poster-status-ok";

  return (
    <Link to={api.sourceDetailPath(source.id)} className="poster-card">
      <div className="poster-card-art">
        {source.poster_path ? (
          <img src={api.posterUrl(source.id)} alt="" />
        ) : (
          <div className="poster-card-placeholder">No poster</div>
        )}
        {!monitored && <span className="poster-card-badge muted-badge">Off</span>}
        {monitored && source.wanted_count > 0 && (
          <span className="poster-card-badge wanted-badge">{source.wanted_count}</span>
        )}
        <div className={`poster-status-bar ${statusClass}`} />
      </div>
      <div className="poster-card-meta">
        <div className="poster-card-title" title={source.title}>
          {source.title}
        </div>
        <div className="poster-card-line">
          {kindLabel} · {monitored ? "Monitored" : "Downloaded"}
        </div>
        <div className="poster-card-line muted">
          <span>{qualityLabel(source.quality)}</span>
          <span>·</span>
          <span>{progress}</span>
        </div>
      </div>
    </Link>
  );
}
