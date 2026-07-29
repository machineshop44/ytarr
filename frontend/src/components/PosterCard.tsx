import { Link } from "react-router-dom";
import { api, type Source } from "../api";

type PosterCardProps = {
  source: Source;
};

export function PosterCard({ source }: PosterCardProps) {
  const progress =
    source.video_count > 0
      ? `${source.downloaded_count}/${source.video_count}`
      : `${source.downloaded_count} downloaded`;
  const wantedHint = source.wanted_count > 0 ? `${source.wanted_count} wanted` : null;

  return (
    <Link to={api.sourceDetailPath(source.id)} className="poster-card">
      <div className="poster-card-art">
        {source.poster_path ? (
          <img src={api.posterUrl(source.id)} alt="" />
        ) : (
          <div className="poster-card-placeholder">No poster</div>
        )}
        {!source.enabled && <span className="poster-card-badge muted-badge">Off</span>}
        {source.enabled && source.wanted_count > 0 && (
          <span className="poster-card-badge wanted-badge">{source.wanted_count}</span>
        )}
      </div>
      <div className="poster-card-meta">
        <div className="poster-card-title" title={source.title}>
          {source.title}
        </div>
        <div className="poster-card-sub">
          <span className="badge">{source.source_type}</span>
          <span>{progress}</span>
          {wantedHint && <span>{wantedHint}</span>}
        </div>
      </div>
    </Link>
  );
}
