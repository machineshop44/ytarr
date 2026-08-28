import { useEffect, useState } from "react";
import { api } from "../api";

export function TagsPage() {
  const [tags, setTags] = useState<string[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [renameFrom, setRenameFrom] = useState<string | null>(null);
  const [renameTo, setRenameTo] = useState("");

  const load = async () => {
    const res = await api.tags();
    setTags(res.tags);
    setCounts(res.counts || {});
  };

  useEffect(() => {
    void load().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const onRename = async () => {
    if (!renameFrom || !renameTo.trim()) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await api.renameTag(renameFrom, renameTo.trim());
      setMessage(`Renamed “${renameFrom}” → “${renameTo.trim()}” on ${res.updated} series.`);
      setRenameFrom(null);
      setRenameTo("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (tag: string) => {
    if (!window.confirm(`Remove tag “${tag}” from all series?`)) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await api.deleteTag(tag);
      setMessage(`Removed “${tag}” from ${res.updated} series.`);
      await load();
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
          <h1>Tags</h1>
          <p className="muted">
            Manage series tags (comma-separated on Edit). Rename or remove across the library —
            Sonarr Tags for YouTube.
          </p>
        </div>
      </header>
      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}
      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>Tag</th>
              <th>Series</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tags.map((tag) => (
              <tr key={tag}>
                <td>
                  {renameFrom === tag ? (
                    <input
                      value={renameTo}
                      onChange={(e) => setRenameTo(e.target.value)}
                      autoFocus
                      aria-label="New tag name"
                    />
                  ) : (
                    tag
                  )}
                </td>
                <td className="mono muted">{counts[tag] ?? "—"}</td>
                <td>
                  <div className="row" style={{ gap: "0.35rem" }}>
                    {renameFrom === tag ? (
                      <>
                        <button
                          className="btn btn-primary"
                          type="button"
                          disabled={busy || !renameTo.trim()}
                          onClick={() => void onRename()}
                        >
                          Save
                        </button>
                        <button
                          className="btn"
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            setRenameFrom(null);
                            setRenameTo("");
                          }}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          className="btn"
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            setRenameFrom(tag);
                            setRenameTo(tag);
                          }}
                        >
                          Rename
                        </button>
                        <button
                          className="btn"
                          type="button"
                          disabled={busy}
                          onClick={() => void onDelete(tag)}
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!tags.length && (
          <p className="muted" style={{ padding: "0.75rem" }}>
            No tags yet. Add tags on a series Edit dialog (comma-separated).
          </p>
        )}
      </div>
    </div>
  );
}
