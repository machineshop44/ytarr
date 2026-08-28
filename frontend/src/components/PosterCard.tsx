import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Source } from "../api";
import { qualityLabel } from "../qualityOptions";

type PosterCardProps = {
  source: Source;
  selectMode?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
};

export function PosterCard({ source, selectMode, selected, onToggleSelect }: PosterCardProps) {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [artState, setArtState] = useState<"loading" | "loaded" | "failed">("loading");
  const posterBust = source.poster_path || String(source.id);
  const posterSrc = api.posterUrl(source.id, posterBust);

  const syncArtState = useCallback((img: HTMLImageElement | null) => {
    if (!img) return;
    if (img.complete && img.naturalWidth > 0) setArtState("loaded");
    else if (img.complete) setArtState("failed");
    else setArtState("loading");
  }, []);

  useEffect(() => {
    syncArtState(imgRef.current);
  }, [posterSrc, syncArtState]);

  const onImgRef = useCallback(
    (node: HTMLImageElement | null) => {
      imgRef.current = node;
      syncArtState(node);
    },
    [syncArtState],
  );
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

  const body = (
    <>
      <div className="poster-card-art">
        <img
          ref={onImgRef}
          src={posterSrc}
          alt=""
          className={artState === "loaded" ? "is-loaded" : undefined}
          onLoad={() => setArtState("loaded")}
          onError={() => setArtState("failed")}
        />
        {artState !== "loaded" && (
          <div className="poster-card-placeholder">
            {artState === "failed" || !source.poster_path ? "No poster" : ""}
          </div>
        )}
        {selectMode && (
          <span className={`poster-select-check${selected ? " is-selected" : ""}`} aria-hidden>
            {selected ? "✓" : ""}
          </span>
        )}
        {!selectMode && !monitored && <span className="poster-card-badge muted-badge">Off</span>}
        {!selectMode && monitored && source.wanted_count > 0 && (
          <span className="poster-card-badge wanted-badge">{source.wanted_count}</span>
        )}
        <div className={`poster-status-bar ${statusClass}`} />
      </div>
      <div className="poster-card-meta">
        <div className="poster-card-title" title={source.title}>
          {source.title}
        </div>
        <div className="poster-card-line">
          {kindLabel}
          {source.source_type === "channel" && (source.nested_playlist_count ?? 0) > 0
            ? ` · ${source.nested_playlist_count} playlist${
                (source.nested_playlist_count ?? 0) === 1 ? "" : "s"
              }`
            : ""}{" "}
          · {monitored ? "Monitored" : "Unmonitored"}
        </div>
        <div className="poster-card-line muted">
          <span>{qualityLabel(source.quality, source.media_type)}</span>
          <span>·</span>
          <span>{progress}</span>
        </div>
      </div>
    </>
  );

  if (selectMode) {
    return (
      <button
        type="button"
        className={`poster-card poster-card-selectable${selected ? " is-selected" : ""}`}
        onClick={onToggleSelect}
      >
        {body}
      </button>
    );
  }

  return (
    <Link to={`/channel/${source.id}`} className="poster-card">
      {body}
    </Link>
  );
}
