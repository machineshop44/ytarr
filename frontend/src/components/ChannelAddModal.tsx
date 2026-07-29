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
  error: string | null;
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
    error: null,
  };
}

/** Prefer a canonical playlist?list= URL so yt-dlp lists the full playlist. */
function entriesUrlFor(hit: SearchHit | { id?: string | null; url: string }): string {
  const id = (hit.id || "").trim();
  if (/^(PL|OL|UU|LL|FL|RD)[\w-]+$/i.test(id)) {
    return `https://www.youtube.com/playlist?list=${id}`;
  }
  try {
    const u = new URL(hit.url);
    const list = u.searchParams.get("list");
    if (list && /^(PL|OL|UU|LL|FL|RD)/i.test(list)) {
      return `https://www.youtube.com/playlist?list=${list}`;
    }
  } catch {
    /* fall through */
  }
  return hit.url;
}

export function ChannelAddModal({ channel, busy, onClose, onConfirm }: ChannelAddModalProps) {
  const [playlists, setPlaylists] = useState<SearchHit[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [seasons, setSeasons] = useState<Record<string, SeasonState>>({
    [UPLOADS_KEY]: emptySeason(false),
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

  // Prefetch uploads catalog for dedupe display (does NOT check Uploads)
  useEffect(() => {
    let alive = true;
    void api
      .playlistEntries(channel.url, 200)
      .then((res) => {
        if (!alive) return;
        setSeasons((prev) => {
          const cur = prev[UPLOADS_KEY] || emptySeason(false);
          if (cur.entries.length) return prev;
          return {
            ...prev,
            [UPLOADS_KEY]: { ...cur, entries: res.entries, error: null },
          };
        });
      })
      .catch(() => {
        /* optional */
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

  /** YouTube ids covered by any selected playlist (playlists win over Uploads). */
  const playlistOwnedIds = useMemo(() => {
    const ids = new Set<string>();
    for (const pl of playlists) {
      const key = pl.id || pl.url;
      const st = seasons[key];
      if (!st?.checked || !st.entries.length) continue;
      for (const e of st.entries) {
        if (st.selectedIds == null || st.selectedIds.has(e.video_id)) {
          ids.add(e.video_id);
        }
      }
    }
    return ids;
  }, [playlists, seasons]);

  const setSeason = (key: string, patch: Partial<SeasonState>) => {
    setSeasons((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || emptySeason()), ...patch },
    }));
  };

  const loadEntries = async (key: string, url: string) => {
    setSeason(key, { loading: true, error: null });
    try {
      const res = await api.playlistEntries(url, 200);
      setSeasons((prev) => {
        const cur = prev[key] || emptySeason();
        return {
          ...prev,
          [key]: {
            ...cur,
            loading: false,
            error: null,
            entries: res.entries,
            selectedIds:
              cur.checked && cur.selectedIds == null
                ? new Set(res.entries.map((e) => e.video_id))
                : cur.selectedIds,
          },
        };
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setSeason(key, { loading: false, error: msg });
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
    if (next) {
      setSeason(key, {
        checked: true,
        expanded: true,
        selectedIds: cur.selectedIds,
        error: null,
      });
      if (!cur.entries.length && !cur.loading) {
        void loadEntries(key, url);
      }
    } else {
      setSeason(key, {
        checked: false,
        selectedIds: null,
      });
    }
  };

  /** Playlists show everything; Uploads hides ids already in selected playlists. */
  const visibleEntries = (key: string, entries: PlaylistEntryPreview[]) => {
    let list =
      key !== UPLOADS_KEY || !playlistOwnedIds.size
        ? entries
        : entries.filter((e) => !playlistOwnedIds.has(e.video_id));
    // Newest first when dates exist; undated keep relative order at the end
    return [...list].sort((a, b) => {
      const ta = a.published_at ? Date.parse(a.published_at) : NaN;
      const tb = b.published_at ? Date.parse(b.published_at) : NaN;
      if (!Number.isNaN(ta) && !Number.isNaN(tb)) return tb - ta;
      if (!Number.isNaN(ta)) return -1;
      if (!Number.isNaN(tb)) return 1;
      return 0;
    });
  };

  const toggleEpisode = (key: string, videoId: string, visible: PlaylistEntryPreview[]) => {
    const cur = seasons[key] || emptySeason();
    // Important: when nothing is selected yet (checked=false, selectedIds=null),
    // start from an EMPTY set — not "all videos". Otherwise clicking one episode
    // selects everything else and deselects the one you clicked.
    let base: Set<string>;
    if (cur.selectedIds != null) {
      base = new Set(cur.selectedIds);
    } else if (cur.checked) {
      base = new Set(visible.map((e) => e.video_id));
    } else {
      base = new Set();
    }
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
    const uploadsChecked = Boolean(uploads?.checked);
    const selectedPlaylists: { hit: SearchHit; videoIds: string[] | null }[] = [];
    for (const pl of playlists) {
      const key = pl.id || pl.url;
      const st = seasons[key];
      if (!st?.checked) continue;
      let videoIds: string[] | null = null;
      if (st.selectedIds != null && st.entries.length > 0) {
        if (st.selectedIds.size < st.entries.length) {
          videoIds = [...st.selectedIds];
        }
      }
      selectedPlaylists.push({ hit: pl, videoIds });
    }
    let uploadVideoIds: string[] | null = null;
    if (uploadsChecked) {
      const visibleUploads = visibleEntries(UPLOADS_KEY, uploads?.entries || []);
      if (uploads?.selectedIds && uploads.entries.length > 0) {
        const picked = [...uploads.selectedIds].filter((id) =>
          visibleUploads.some((e) => e.video_id === id),
        );
        if (picked.length < visibleUploads.length || playlistOwnedIds.size > 0) {
          uploadVideoIds = picked;
        }
      } else if (playlistOwnedIds.size > 0) {
        uploadVideoIds = visibleUploads.map((e) => e.video_id);
      }
    }
    onConfirm({
      monitorUploads: uploadsChecked,
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
    const visible = visibleEntries(key, st.entries);
    const hiddenDupes =
      key === UPLOADS_KEY && st.entries.length > 0 ? st.entries.length - visible.length : 0;
    return (
      <article key={key} className={`season-row ${st.checked ? "is-monitored" : ""}`}>
        <div className="season-row-main">
          <label className="monitor-check" title="Monitor this playlist">
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
              {!st.expanded && (
                <div className="muted" style={{ fontSize: "0.78rem", marginTop: "0.15rem" }}>
                  Click to view episodes
                </div>
              )}
            </div>
            <span className="album-chevron">{st.expanded ? "▾" : "▸"}</span>
          </button>
        </div>
        {st.expanded && (
          <div className="album-tracks">
            {st.loading && <p className="muted track-empty">Loading episodes…</p>}
            {st.error && (
              <div className="track-empty">
                <p className="error" style={{ margin: "0 0 0.35rem" }}>
                  {st.error}
                </p>
                <button
                  className="btn"
                  type="button"
                  disabled={busy || st.loading}
                  onClick={() => void loadEntries(key, url)}
                >
                  Retry
                </button>
              </div>
            )}
            {!st.loading && !st.error && !visible.length && (
              <p className="muted track-empty">
                {hiddenDupes > 0
                  ? `All ${hiddenDupes} videos already appear in selected playlists — nothing unique in Uploads.`
                  : "No downloadable videos (members-only hidden)."}
              </p>
            )}
            {hiddenDupes > 0 && visible.length > 0 && (
              <p className="muted track-empty">
                Hiding {hiddenDupes} video{hiddenDupes === 1 ? "" : "s"} already in selected
                playlists.
              </p>
            )}
            {visible.map((ep) => {
              const on =
                st.selectedIds == null ? st.checked : st.selectedIds.has(ep.video_id);
              const dateLabel = ep.published_at
                ? new Date(ep.published_at).toLocaleDateString(undefined, {
                    year: "numeric",
                    month: "short",
                    day: "numeric",
                  })
                : null;
              return (
                <label
                  key={ep.video_id}
                  className={`track-monitor ${on ? "is-wanted" : ""}`}
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={busy}
                    onChange={() => toggleEpisode(key, ep.video_id, visible)}
                  />
                  <span className="monitor-check-box" aria-hidden />
                  <span className="track-monitor-body">
                    <span className="track-title">{ep.title}</span>
                    <span className="track-meta">
                      {dateLabel && <span className="muted">{dateLabel}</span>}
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
              Tick playlists or individual episodes — or add the channel alone and pick seasons later
              from the library. <strong>Uploads</strong> is last and stays unchecked by default.
            </p>
          </div>
          <button className="btn" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>

        {error && <div className="error">{error}</div>}

        <div className="modal-body">
          <div className="section-head">
            <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Playlists</h3>
            <span className="muted">{selectedCount} selected</span>
          </div>
          <p className="muted album-hint">
            Videos already in a selected playlist are omitted from Uploads so you do not pick the
            same episode twice.
          </p>

          {loadingList && <p className="muted">Loading playlists…</p>}

          <div className="album-list">
            {playlists.map((pl) => {
              const key = pl.id || pl.url;
              const url = entriesUrlFor(pl);
              return renderSeason(
                key,
                pl.title,
                url,
                pl.video_count != null
                  ? `${pl.video_count} ${pl.video_count === 1 ? "video" : "videos"}`
                  : undefined,
                pl.thumbnail_url,
              );
            })}
            {renderSeason(
              UPLOADS_KEY,
              "Uploads",
              channel.url,
              "Full channel feed — leave unchecked unless you want everything not already in a playlist",
              channel.thumbnail_url,
            )}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            className="btn"
            type="button"
            disabled={busy}
            title="Add the channel with no playlists monitored — configure later in Library"
            onClick={() =>
              onConfirm({
                monitorUploads: false,
                uploadVideoIds: null,
                playlists: [],
              })
            }
          >
            {busy ? "Adding…" : "Add channel only"}
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={busy || selectedCount === 0}
            onClick={handleConfirm}
          >
            {busy ? "Adding…" : `Add selected (${selectedCount})`}
          </button>
        </div>
      </div>
    </div>
  );
}
