import { useEffect, useMemo, useState } from "react";
import { api, type RenameItem, type Source } from "../api";

export function RenamePage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState<string>("all");
  const [items, setItems] = useState<RenameItem[]>([]);
  const [needsCount, setNeedsCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const load = async (sid = sourceId) => {
    const preview = await api.renamePreview(sid === "all" ? undefined : Number(sid));
    setItems(preview.items);
    setNeedsCount(preview.needs_rename_count);
    setSelected(new Set(preview.items.filter((i) => i.needs_rename).map((i) => i.video_db_id)));
  };

  useEffect(() => {
    void (async () => {
      try {
        setSources(await api.sources());
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  const selectable = useMemo(
    () => items.filter((i) => i.needs_rename).map((i) => i.video_db_id),
    [items],
  );

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected((prev) => {
      if (prev.size === selectable.length) return new Set();
      return new Set(selectable);
    });
  };

  const onRefresh = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await load(sourceId);
      setMessage("Preview refreshed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onApply = async () => {
    if (!selected.size) return;
    if (!window.confirm(`Rename ${selected.size} file(s) to the Plex-friendly pattern?`)) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.renameApply({
        source_id: sourceId === "all" ? undefined : Number(sourceId),
        video_ids: [...selected],
      });
      setMessage(
        `Renamed ${result.renamed}, skipped ${result.skipped}` +
          (result.errors.length ? ` · ${result.errors.length} error(s)` : ""),
      );
      if (result.errors.length) setError(result.errors.join("\n"));
      await load(sourceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Rename</h1>
          <p>
            Organize files like Sonarr —{" "}
            <span className="mono">Channel / YYYY-MM-DD - Title [id].ext</span> for Plex Local Media
            Assets.
          </p>
        </div>
      </div>

      <div className="panel row" style={{ alignItems: "flex-end" }}>
        <div className="field grow" style={{ marginBottom: 0 }}>
          <label htmlFor="rename-source">Source</label>
          <select
            id="rename-source"
            value={sourceId}
            disabled={busy}
            onChange={(e) => {
              const v = e.target.value;
              setSourceId(v);
              setBusy(true);
              void load(v)
                .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                .finally(() => setBusy(false));
            }}
          >
            <option value="all">All sources</option>
            {sources.map((s) => (
              <option key={s.id} value={String(s.id)}>
                {s.title}
              </option>
            ))}
          </select>
        </div>
        <button className="btn" type="button" disabled={busy} onClick={() => void onRefresh()}>
          Preview
        </button>
        <button
          className="btn btn-primary"
          type="button"
          disabled={busy || selected.size === 0}
          onClick={() => void onApply()}
        >
          Rename {selected.size || ""} selected
        </button>
      </div>

      {error && <div className="error" style={{ whiteSpace: "pre-wrap" }}>{error}</div>}
      {message && <div className="success">{message}</div>}

      <p className="muted">
        {needsCount} file(s) need renaming · {items.length} downloaded total
      </p>

      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                <input
                  type="checkbox"
                  checked={selectable.length > 0 && selected.size === selectable.length}
                  onChange={toggleAll}
                  disabled={!selectable.length}
                />
              </th>
              <th>Title</th>
              <th>Current</th>
              <th>New</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.video_db_id} className={item.needs_rename ? "" : "muted"}>
                <td>
                  <input
                    type="checkbox"
                    disabled={!item.needs_rename}
                    checked={selected.has(item.video_db_id)}
                    onChange={() => toggle(item.video_db_id)}
                  />
                </td>
                <td>
                  <div>{item.title}</div>
                  <div className="muted" style={{ fontSize: "0.8rem" }}>
                    {item.source_title} · <span className="mono">{item.youtube_id}</span>
                  </div>
                  {item.reason && !item.needs_rename && (
                    <div className="muted" style={{ fontSize: "0.78rem" }}>
                      {item.reason}
                    </div>
                  )}
                </td>
                <td className="mono" style={{ fontSize: "0.75rem", wordBreak: "break-all" }}>
                  {item.current_path || "—"}
                </td>
                <td className="mono" style={{ fontSize: "0.75rem", wordBreak: "break-all" }}>
                  {item.new_path || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!items.length && <p className="muted">No downloaded files to rename yet.</p>}
      </div>
    </>
  );
}
