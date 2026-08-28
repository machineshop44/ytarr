import { useEffect, useState } from "react";
import { api } from "../api";

type Orphan = {
  path: string;
  video_id: string;
  title: string;
  already_in_db: boolean;
};

export function ManualImportPage() {
  const [items, setItems] = useState<Orphan[]>([]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const scan = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.importScan();
      setItems(res.items);
      setSelected(new Set(res.items.map((i) => i.path)));
      setMessage(`Found ${res.items.length} candidate file(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void scan();
  }, []);

  const toggle = (path: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const apply = async () => {
    const picks = items.filter((i) => selected.has(i.path));
    if (!picks.length) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.importApply(picks);
      setMessage(
        `Imported ${res.imported}, skipped ${res.skipped}` +
          (res.errors.length ? ` · ${res.errors.length} error(s)` : ""),
      );
      if (res.errors.length) setError(res.errors.join("\n"));
      await scan();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Manual Import</h1>
          <p className="muted">
            Scan library folders for files named with <span className="mono">[youtubeId]</span> and
            link them into the catalog (Arr Manual Import).
          </p>
        </div>
        <div className="toolbar">
          <button className="btn" type="button" disabled={busy} onClick={() => void scan()}>
            Rescan
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={busy || !selected.size}
            onClick={() => void apply()}
          >
            Import selected ({selected.size})
          </button>
        </div>
      </header>
      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}
      {!items.length && !busy && <p className="muted">No orphan files found.</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th aria-label="Select" />
              <th>Title</th>
              <th>ID</th>
              <th>Path</th>
              <th>DB</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.path}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(i.path)}
                    onChange={() => toggle(i.path)}
                  />
                </td>
                <td>{i.title}</td>
                <td className="mono">{i.video_id}</td>
                <td className="mono muted" style={{ fontSize: "0.8rem" }}>
                  {i.path}
                </td>
                <td>{i.already_in_db ? "update" : "new"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
