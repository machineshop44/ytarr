import { useEffect, useMemo, useState } from "react";
import { api, type PlaylistEntryPreview, type SearchHit } from "../api";

const UPLOADS_KEY = "__uploads__";

type SeasonState = {
  checked: boolean;
  expanded: boolean;
  loading: boolean;
  entries: PlaylistEntryPreview[];
  /** null = all videos (season check without per-episode edits) */
  selectedIds: Set<string> | null;
};

type ChannelAddModalProps = {
  channel: SearchHit;
  busy?: boolean;
  onClose: () => void;
  onConfirm: (selection: {
    monitorUploads: boolean;
    uploadVideoIds: string[] | null;
    playlists: { hit: SearchHit; videoIds: string[] | null }[];
  }) => void;
};

function emptySeason(checked = false): SeasonState {
  return {
    checked,
    expanded: false,
    loading: false,
    entries: [],
    selectedIds: null,
  };
}

export function ChannelAddModal({ channel, busy, onClose, onConfirm }: ChannelAddModalProps) {
  const [playlists, setPlaylists] = useState<SearchHit[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [seasons, setSeasons] = useState<Record<string, SeasonState>>({
    [UPLOADS_KEY]: emptySeason(true),
  });

  useEffect(() => {
    let alive = true;
    setLoadingList(true);
    setError(null);
    void api
      .channelPlaylists(channel.url, 50)
      .then((res) => {
        if (!alive) return;
        setPlaylists(res.results);
        setSeasons((prev) => {
          const next = { ...prev };
          for (const pl of res.results) {
            const key = pl.id || pl.url;
            if (!next[key]) next[key] = emptySeason(false);
          }
          return next;
        });
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (alive) setLoadingList(false);
      });
    return () => {
      alive = false;
    };
  }, [channel.url]);

  const selectedCount = useMemo(() => {
    let n = 0;
    if (seasons[UPLOADS_KEY]?.checked) n += 1;
    for (const pl of playlists) {
      const key = pl.id || pl.url;
      if (seasons[key]?.checked) n += 1;
    }
    return n;
  }, [seasons, playlists]);

  const setSeason = (key: string, patch: Partial<SeasonState>) => {
    setSeasons((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || emptySeason()), ...patch },
    }));
  };

  const loadEntries = async (key: string, url: string) => {
    setSeason(key, { loading: true });
    try {
      const res = await api.playlistEntries(url, 100);
      const ids = new Set(res.entries.map((e) => e.video_id));
      setSeason(key, {
        loading: false,
        entries: res.entries,
        selectedIds: ids,
        checked: true,
      });
    } catch (err) {
      setSeason(key, { loading: false });
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const toggleExpand = (key: string, url: string) => {
    const cur = seasons[key] || emptySeason();
    if (cur.expanded) {
      setSeason(key, { expanded: false });
      return;
    }
    setSeason(key, { expanded: true });
    if (!cur.entries.length && !cur.loading) {
      void loadEntries(key, url);
    }
  };

  const toggleSeasonCheck = (key: string, url: string) => {
    const cur = seasons[key] || emptySeason();
    const next = !cur.checked;
    if (next && cur.expanded && !cur.entries.length) {
      void loadEntries(key, url);
    }
    setSeason(key, {
      checked: next,
      selectedIds: next ? cur.selectedIds : null,
    });
  };

  const toggleEpisode = (key: string, videoId: string) => {
    const cur = seasons[key] || emptySeason();
    const base =
      cur.selectedIds ?? new Set(cur.entries.map((e) => e.video_id));
    const next = new Set(base);
    if (next.has(videoId)) next.delete(videoId);
    else next.add(videoId);
    setSeason(key, {
      checked: next.size > 0,
      selectedIds: next,
    });
  };

  const handleConfirm = () => {
    const uploads = seasons[UPLOADS_KEY];
    const selectedPlaylists: { hit: SearchHit; videoIds: string[] | null }[] = [];
    for (const pl of playlists) {
      const key = pl.id || pl.url;
      const st = seasons[key];
      if (!st?.checked) continue;
      const videoIds =
        st.selectedIds == null
          ? null
          : st.entries.length === 0
            ? null
            : st.selectedIds.size === st.entries.length
              ? null
              : [...st.selectedIds];
      selectedPlaylists.push({ hit: pl, videoIds });
    }
    let uploadVideoIds: string[] | null = null;
    if (uploads?.checked && uploads.selectedIds && uploads.entries.length > 0) {
      if (uploads.selectedIds.size < uploads.entries.length) {
        uploadVideoIds = [...uploads.selectedIds];
      }
    }
    onConfirm({
      monitorUploads: Boolean(uploads?.checked),
      uploadVideoIds,
      playlists: selectedPlaylists,
    });
  };

  const renderSeason = (
    key: string,
    title: string,
    url: string,
    subtitle?: string,
    thumb?: string | null,
  ) => {
    const st = seasons[key] || emptySeason();
    return (
      <article key={key} className={`season-row ${st.checked ? "is-monitored" : ""}`}>
        <div className="season-row-main">
          <label className="monitor-check" title="Monitor / download this season">
            <input
              type="checkbox"
              checked={st.checked}
              disabled={busy}
              onChange={() => toggleSeasonCheck(key, url)}
            />
            <span className="monitor-check-box" aria-hidden />
          </label>
          <button type="button" className="season-row-hit" onClick={() => toggleExpand(key, url)}>
            {thumb ? (
              <img className="album-thumb" src={thumb} alt="" />
            ) : (
              <div className="album-thumb placeholder">—</div>
            )}
            <div className="album-body">
              <div className="album-title-row">
                <h3>{title}</h3>
                {st.checked && <span className="badge">selected</span>}
              </div>
              {subtitle && <div className="source-meta">{subtitle}</div>}
            </div>
            <span className="album-chevron">{st.expanded ? "▾" : "▸"}</span>
          </button>
        </div>
        {st.expanded && (
          <div className="album-tracks">
            {st.loading && <p className="muted track-empty">Loading episodes…</p>}
            {!st.loading && !st.entries.length && (
              <p className="muted track-empty">No downloadable videos (members-only hidden).</p>
            )}
            {st.entries.map((ep) => {
              const on =
                st.selectedIds == null
                  ? st.checked
                  : st.selectedIds.has(ep.video_id);
              return (
                <label key={ep.video_id} className={`track-monitor ${on ? "is-wanted" : ""}`}>
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={busy}
                    onChange={() => toggleEpisode(key, ep.video_id)}
                  />
                  <span className="monitor-check-box" aria-hidden />
                  <span className="track-monitor-body">
                    <span className="track-title">{ep.title}</span>
                    <span className="track-meta">
                      {ep.duration != null && ep.duration > 0 && (
                        <span className="muted">{Math.floor(ep.duration / 60)}m</span>
                      )}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        )}
      </article>
    );
  };

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="channel-add-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <div className="muted" style={{ fontSize: "0.8rem" }}>
              Add to library
            </div>
            <h2 id="channel-add-title">{channel.title}</h2>
            <p className="muted" style={{ margin: "0.35rem 0 0" }}>
              Check seasons (playlists) and episodes (videos) to download — like Sonarr.
              Members-only videos are hidden.
            </p>
          </div>
          <button className="btn" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>

        {error && <div className="error">{error}</div>}

        <div className="modal-body">
          <div className="section-head">
            <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Seasons</h3>
            <span className="muted">{selectedCount} selected</span>
          </div>

          {loadingList && <p className="muted">Loading playlists…</p>}

          <div className="album-list">
            {renderSeason(
              UPLOADS_KEY,
              "Uploads",
              channel.url,
              "Channel uploads feed",
              channel.thumbnail_url,
            )}
            {playlists.map((pl) =>
              renderSeason(
                pl.id || pl.url,
                pl.title,
                pl.url,
                pl.video_count != null
                  ? `${pl.video_count} ${pl.video_count === 1 ? "video" : "videos"}`
                  : undefined,
                pl.thumbnail_url,
              ),
            )}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={busy || selectedCount === 0}
            onClick={handleConfirm}
          >
            {busy ? "Adding…" : `Add to library (${selectedCount})`}
          </button>
        </div>
      </div>
    </div>
  );
}
