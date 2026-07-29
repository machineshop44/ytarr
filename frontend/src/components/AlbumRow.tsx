import type { SearchHit, Source } from "../api";

export { findExistingPlaylist } from "./playlistMatch";

type AlbumRowProps = {
  hit: SearchHit;
  existing?: Source | null;
  busy?: boolean;
  onAdd?: () => void;
  onOpen?: () => void;
  primaryLabel?: string;
};

/** Compact playlist row for Add New search results. */
export function AlbumRow({
  hit,
  existing,
  busy,
  onAdd,
  onOpen,
  primaryLabel = "Add + Search",
}: AlbumRowProps) {
  return (
    <article className="album-row">
      {hit.thumbnail_url ? (
        <img className="album-thumb" src={hit.thumbnail_url} alt="" />
      ) : (
        <div className="album-thumb placeholder">No art</div>
      )}
      <div className="album-body">
        <div className="album-title-row">
          <h3>{hit.title}</h3>
          {existing ? <span className="badge">monitored</span> : <span className="badge">playlist</span>}
        </div>
        <div className="source-meta">
          {hit.video_count != null && (
            <span>
              {hit.video_count} {hit.video_count === 1 ? "video" : "videos"}
            </span>
          )}
          {existing && (
            <span>
              {existing.downloaded_count}/{existing.video_count || "—"} downloaded
              {existing.wanted_count > 0 ? ` · ${existing.wanted_count} wanted` : ""}
            </span>
          )}
        </div>
        <div className="row">
          {existing && onOpen && (
            <button className="btn" type="button" onClick={onOpen}>
              Open
            </button>
          )}
          {!existing && onAdd && (
            <button className="btn btn-primary" type="button" disabled={busy} onClick={onAdd}>
              {busy ? "Adding…" : primaryLabel}
            </button>
          )}
          {existing && onAdd && (
            <button className="btn" type="button" disabled={busy} onClick={onAdd}>
              {busy ? "Searching…" : "Search"}
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
