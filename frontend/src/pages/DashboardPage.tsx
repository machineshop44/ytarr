import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Source } from "../api";
import { PosterCard } from "../components/PosterCard";

type SortKey = "title" | "wanted" | "downloaded";
type FilterKey = "all" | "monitored" | "unmonitored" | "wanted";
type MediaFilter = "all" | "video" | "audio";

export function DashboardPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyAction, setBusyAction] = useState<"update" | "art" | null>(null);
  const [sort, setSort] = useState<SortKey>("title");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [tagFilter, setTagFilter] = useState("");
  const [mediaFilter, setMediaFilter] = useState<MediaFilter>("all");
  const [query, setQuery] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [loading, setLoading] = useState(true);

  const load = async () => {
    setSources(await api.sources());
  };

  useEffect(() => {
    let alive = true;
    let inFlight = false;
    const tick = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        await load();
        if (alive) setError(null);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      } finally {
        inFlight = false;
        if (alive) setLoading(false);
      }
    };
    void tick();
    const id = window.setInterval(() => {
      if (document.hidden) return;
      void tick();
    }, 15000);
    const onVis = () => {
      if (!document.hidden) void tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      alive = false;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  /** Top-level library posters: channels, videos, and standalone playlists only. */
  const libraryItems = useMemo(() => {
    const channelTitles = new Set(
      sources
        .filter((s) => s.source_type === "channel")
        .map((s) => s.title.trim().toLowerCase())
        .filter(Boolean),
    );
    let list = sources.filter((s) => {
      if (s.source_type !== "playlist") return true;
      // Nested under a channel (DB link)
      if (s.parent_source_id != null) return false;
      // Same title as a channel → treat as season, not a duplicate poster
      if (channelTitles.has(s.title.trim().toLowerCase())) return false;
      return true;
    });
    const q = query.trim().toLowerCase();
    if (q) list = list.filter((s) => s.title.toLowerCase().includes(q));
    if (mediaFilter === "video") list = list.filter((s) => (s.media_type || "video") !== "audio");
    if (mediaFilter === "audio") list = list.filter((s) => s.media_type === "audio");
    if (filter === "monitored") list = list.filter((s) => s.enabled);
    if (filter === "unmonitored") list = list.filter((s) => !s.enabled);
    if (filter === "wanted") list = list.filter((s) => s.wanted_count > 0);
    if (tagFilter) {
      list = list.filter((s) =>
        (s.tags || "")
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean)
          .includes(tagFilter),
      );
    }
    list = [...list].sort((a, b) => {
      if (sort === "wanted") return b.wanted_count - a.wanted_count || a.title.localeCompare(b.title);
      if (sort === "downloaded")
        return b.downloaded_count - a.downloaded_count || a.title.localeCompare(b.title);
      return a.title.localeCompare(b.title);
    });
    return list;
  }, [sources, sort, filter, mediaFilter, query, tagFilter]);

  const allTags = useMemo(() => {
    const found = new Set<string>();
    for (const s of sources) {
      for (const part of (s.tags || "").split(",")) {
        const t = part.trim();
        if (t) found.add(t);
      }
    }
    return [...found].sort((a, b) => a.localeCompare(b));
  }, [sources]);

  // Drop selections that are no longer in the filtered list
  useEffect(() => {
    if (!editMode) return;
    setSelectedIds((prev) => {
      if (prev.size === 0) return prev;
      const visible = new Set(libraryItems.map((s) => s.id));
      let changed = false;
      const next = new Set<number>();
      for (const id of prev) {
        if (visible.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [libraryItems, editMode]);

  const selectedItems = useMemo(
    () => libraryItems.filter((s) => selectedIds.has(s.id)),
    [libraryItems, selectedIds],
  );

  const allVisibleSelected =
    libraryItems.length > 0 && libraryItems.every((s) => selectedIds.has(s.id));

  const toggleEditMode = () => {
    setEditMode((prev) => {
      if (prev) {
        setSelectedIds(new Set());
        setDeleteOpen(false);
        setDeleteFiles(false);
      }
      return !prev;
    });
  };

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedIds(new Set(libraryItems.map((s) => s.id)));
  };

  const clearSelection = () => setSelectedIds(new Set());

  const refreshAll = async () => {
    setBusy(true);
    setBusyAction("update");
    setError(null);
    setMessage(null);
    try {
      const result = await api.checkAllSources();
      await api.processQueue();
      await load();
      setMessage(`Checked ${result.checked} monitored source(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      setBusyAction(null);
    }
  };

  const refreshArtworkAll = async () => {
    setBusy(true);
    setBusyAction("art");
    setError(null);
    setMessage(null);
    try {
      // Skip nested playlists — they often share the channel folder and would overwrite the avatar
      const targets = sources.filter((s) => !s.parent_source_id);
      let ok = 0;
      for (const ch of targets) {
        try {
          const updated = await api.refreshArtwork(ch.id, { force: false });
          if (updated.poster_path) ok += 1;
        } catch {
          /* continue */
        }
      }
      await load();
      setMessage(
        ok === targets.length
          ? `Refreshed artwork for ${ok} series.`
          : `Refreshed artwork for ${ok} of ${targets.length} series.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      setBusyAction(null);
    }
  };

  const openBulkDelete = () => {
    if (selectedItems.length === 0) return;
    setDeleteFiles(false);
    setDeleteOpen(true);
  };

  const confirmBulkDelete = async () => {
    if (selectedItems.length === 0) return;
    setDeleting(true);
    setError(null);
    setMessage(null);
    const ids = selectedItems.map((s) => s.id);
    const titles = selectedItems.map((s) => s.title);
    setDeleteOpen(false);
    let ok = 0;
    const failures: string[] = [];
    try {
      for (let i = 0; i < ids.length; i++) {
        try {
          await api.deleteSource(ids[i], { deleteFiles });
          ok += 1;
        } catch (err) {
          failures.push(
            `${titles[i]}: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      }
      await load();
      setSelectedIds(new Set());
      setEditMode(false);
      if (failures.length === 0) {
        setMessage(
          deleteFiles
            ? `Deleted ${ok} item(s) and removed files from disk.`
            : `Removed ${ok} item(s) from the library (files kept).`,
        );
      } else {
        setError(
          `Removed ${ok}, failed ${failures.length}. ${failures.slice(0, 3).join(" · ")}`,
        );
      }
    } finally {
      setDeleting(false);
      setDeleteFiles(false);
    }
  };

  return (
    <>
      <div className="page-toolbar">
        <button
          className={`btn${editMode ? " btn-primary" : ""}`}
          type="button"
          disabled={busy || deleting}
          onClick={toggleEditMode}
        >
          {editMode ? "Done" : "Edit"}
        </button>
        {!editMode && (
          <>
            <button className="btn" type="button" disabled={busy} onClick={() => void refreshAll()}>
              {busyAction === "update" ? "Updating…" : "Update All"}
            </button>
            <button
              className="btn"
              type="button"
              disabled={busy}
              onClick={() => void refreshArtworkAll()}
            >
              {busyAction === "art" ? "Refreshing…" : "Refresh Art"}
            </button>
            <Link className="btn btn-primary" to="/add">
              Add New
            </Link>
          </>
        )}
        {editMode && (
          <>
            <button
              className="btn"
              type="button"
              disabled={libraryItems.length === 0 || deleting}
              onClick={allVisibleSelected ? clearSelection : selectAllVisible}
            >
              {allVisibleSelected ? "Unselect All" : "Select All"}
            </button>
            <button
              className="btn btn-danger"
              type="button"
              disabled={selectedIds.size === 0 || deleting}
              onClick={openBulkDelete}
            >
              Delete{selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}
            </button>
            <span className="muted" style={{ fontSize: "0.85rem" }}>
              {selectedIds.size} selected
            </span>
          </>
        )}
        <div className="page-toolbar-spacer" />
        <input
          className="toolbar-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search library"
          aria-label="Search library"
        />
        <select
          className="toolbar-select"
          value={mediaFilter}
          onChange={(e) => setMediaFilter(e.target.value as MediaFilter)}
          aria-label="Media type"
        >
          <option value="all">Media: All</option>
          <option value="video">Video</option>
          <option value="audio">Music</option>
        </select>
        <select
          className="toolbar-select"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          aria-label="Sort"
        >
          <option value="title">Sort: Title</option>
          <option value="wanted">Sort: Wanted</option>
          <option value="downloaded">Sort: Downloaded</option>
        </select>
        <select
          className="toolbar-select"
          value={filter}
          onChange={(e) => setFilter(e.target.value as FilterKey)}
          aria-label="Filter"
        >
          <option value="all">Filter: All</option>
          <option value="monitored">Monitored</option>
          <option value="unmonitored">Unmonitored</option>
          <option value="wanted">Has wanted</option>
        </select>
        {allTags.length > 0 && (
          <select
            className="toolbar-select"
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
            aria-label="Tag"
          >
            <option value="">Tag: All</option>
            {allTags.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      {loading && !libraryItems.length && !error && (
        <div className="panel empty-library">
          <p className="muted">Loading library…</p>
        </div>
      )}

      {!loading && !sources.length && !error && (
        <div className="panel empty-library">
          <h2 style={{ marginTop: 0 }}>Library is empty</h2>
          <p className="muted">
            Add a <strong>channel</strong>, playlist, or single song/video. Music one-offs and
            channels both show up here.
          </p>
          <Link className="btn btn-primary" to="/add">
            Add New
          </Link>
        </div>
      )}

      {!loading && sources.length > 0 && !libraryItems.length && !error && (
        <div className="panel empty-library">
          <h2 style={{ marginTop: 0 }}>No matches</h2>
          <p className="muted">Nothing matches the current search or filters.</p>
          <button
            className="btn"
            type="button"
            onClick={() => {
              setQuery("");
              setFilter("all");
              setMediaFilter("all");
              setTagFilter("");
            }}
          >
            Clear filters
          </button>
        </div>
      )}

      {libraryItems.length > 0 && (
        <section className="library-section">
          <div className={`poster-grid${editMode ? " is-editing" : ""}`}>
            {libraryItems.map((source) => (
              <PosterCard
                key={source.id}
                source={source}
                selectMode={editMode}
                selected={selectedIds.has(source.id)}
                onToggleSelect={() => toggleSelect(source.id)}
              />
            ))}
          </div>
        </section>
      )}

      {deleteOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => !deleting && setDeleteOpen(false)}
        >
          <div
            className="modal-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="bulk-delete-title"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: 520 }}
          >
            <div className="modal-header">
              <h2 id="bulk-delete-title">Delete from library</h2>
              <button
                className="btn"
                type="button"
                disabled={deleting}
                onClick={() => setDeleteOpen(false)}
              >
                Close
              </button>
            </div>
            <div className="modal-body">
              <p style={{ marginTop: 0 }}>
                Remove <strong>{selectedItems.length}</strong> item
                {selectedItems.length === 1 ? "" : "s"} from the library?
              </p>
              {selectedItems.length <= 8 ? (
                <ul className="bulk-delete-list">
                  {selectedItems.map((s) => (
                    <li key={s.id}>{s.title}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted" style={{ fontSize: "0.85rem" }}>
                  Including {selectedItems
                    .slice(0, 3)
                    .map((s) => s.title)
                    .join(", ")}
                  , and {selectedItems.length - 3} more.
                </p>
              )}
              <label className="mode-option" style={{ marginBottom: 0 }}>
                <input
                  type="checkbox"
                  checked={deleteFiles}
                  onChange={(e) => setDeleteFiles(e.target.checked)}
                  disabled={deleting}
                />
                <span>
                  <strong>Delete files</strong>
                  <small>
                    Also remove each item&apos;s folder and downloaded media from disk.
                  </small>
                </span>
              </label>
            </div>
            <div className="modal-footer">
              <button
                className="btn"
                type="button"
                disabled={deleting}
                onClick={() => setDeleteOpen(false)}
              >
                Cancel
              </button>
              <button
                className="btn btn-danger"
                type="button"
                disabled={deleting}
                onClick={() => void confirmBulkDelete()}
              >
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
