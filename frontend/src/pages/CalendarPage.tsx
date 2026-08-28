import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

type CalEvent = {
  id: number;
  title: string;
  video_id: string;
  status: string;
  published_at: string | null;
  source_id: number;
  source_title: string | null;
};

type ViewMode = "month" | "week";

function startOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function startOfWeek(d: Date) {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7; // Monday-first
  x.setDate(x.getDate() - day);
  x.setHours(0, 0, 0, 0);
  return x;
}

function addDays(d: Date, n: number) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

function ymd(d: Date) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function monthLabel(d: Date) {
  return d.toLocaleString(undefined, { month: "long", year: "numeric" });
}

function eventLocalDay(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (!Number.isNaN(d.getTime())) return ymd(d);
  return iso.slice(0, 10) || null;
}

export function CalendarPage() {
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ViewMode>("month");
  const [cursor, setCursor] = useState(() => startOfMonth(new Date()));
  const [loading, setLoading] = useState(true);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  const range = useMemo(() => {
    if (view === "week") {
      const start = startOfWeek(cursor);
      const end = addDays(start, 6);
      end.setHours(23, 59, 59, 999);
      return { start, end };
    }
    const start = startOfWeek(startOfMonth(cursor));
    const endMonth = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
    const end = addDays(startOfWeek(endMonth), 6);
    end.setHours(23, 59, 59, 999);
    return { start, end };
  }, [cursor, view]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    void (async () => {
      try {
        const res = await api.calendar(range.start.toISOString(), range.end.toISOString());
        if (!alive) return;
        setEvents(res.events);
        setError(null);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [range.start, range.end]);

  const byDay = useMemo(() => {
    const map = new Map<string, CalEvent[]>();
    for (const e of events) {
      const day = eventLocalDay(e.published_at);
      if (!day) continue;
      const list = map.get(day) || [];
      list.push(e);
      map.set(day, list);
    }
    return map;
  }, [events]);

  const cells = useMemo(() => {
    const days: Date[] = [];
    let d = new Date(range.start);
    const end = range.end;
    while (d <= end) {
      days.push(new Date(d));
      d = addDays(d, 1);
    }
    return days;
  }, [range.start, range.end]);

  const today = ymd(new Date());
  const inMonth = (d: Date) =>
    view === "week" || (d.getMonth() === cursor.getMonth() && d.getFullYear() === cursor.getFullYear());

  const shift = (dir: -1 | 1) => {
    if (view === "week") {
      setCursor((c) => addDays(c, dir * 7));
    } else {
      setCursor((c) => new Date(c.getFullYear(), c.getMonth() + dir, 1));
    }
    setSelectedDay(null);
  };

  const selectedEvents = selectedDay ? byDay.get(selectedDay) || [] : [];
  const previewLimit = view === "week" ? 12 : 4;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Calendar</h1>
          <p className="muted">
            Monitored episodes by publish date — click a day for the full list.
          </p>
        </div>
        <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
          <button className="btn" type="button" onClick={() => shift(-1)}>
            Prev
          </button>
          <button
            className="btn"
            type="button"
            onClick={() => {
              setCursor(view === "week" ? new Date() : startOfMonth(new Date()));
              setSelectedDay(ymd(new Date()));
            }}
          >
            Today
          </button>
          <button className="btn" type="button" onClick={() => shift(1)}>
            Next
          </button>
          <select
            className="toolbar-select"
            value={view}
            onChange={(e) => {
              const next = e.target.value as ViewMode;
              setView(next);
              setCursor(next === "month" ? startOfMonth(new Date()) : new Date());
              setSelectedDay(null);
            }}
            aria-label="Calendar view"
          >
            <option value="month">Month</option>
            <option value="week">Week</option>
          </select>
        </div>
      </header>

      <div className="panel" style={{ marginBottom: "0.75rem" }}>
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>
          {view === "month"
            ? monthLabel(cursor)
            : `${ymd(range.start)} → ${ymd(range.end)}`}
        </h2>
      </div>

      {error && <div className="error">{error}</div>}
      {loading && <p className="muted">Loading…</p>}

      <div className="calendar-grid" role="grid" aria-label="Episode calendar">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
          <div key={d} className="calendar-dow">
            {d}
          </div>
        ))}
        {cells.map((day) => {
          const key = ymd(day);
          const dayEvents = byDay.get(key) || [];
          const muted = !inMonth(day);
          const selected = selectedDay === key;
          return (
            <button
              key={key}
              type="button"
              className={`calendar-cell${muted ? " calendar-cell-muted" : ""}${
                key === today ? " calendar-cell-today" : ""
              }${selected ? " calendar-cell-selected" : ""}`}
              onClick={() => setSelectedDay(key)}
              aria-pressed={selected}
              aria-label={`${key}, ${dayEvents.length} episode${dayEvents.length === 1 ? "" : "s"}`}
            >
              <div className="calendar-daynum">{day.getDate()}</div>
              <ul className="calendar-events">
                {dayEvents.slice(0, previewLimit).map((e) => (
                  <li key={e.id} title={`${e.source_title || ""} — ${e.title}`}>
                    <span className={`badge ${e.status}`}>{e.status}</span> {e.title}
                  </li>
                ))}
                {dayEvents.length > previewLimit && (
                  <li className="muted">+{dayEvents.length - previewLimit} more</li>
                )}
              </ul>
            </button>
          );
        })}
      </div>

      {selectedDay && (
        <div className="panel" style={{ marginTop: "1rem" }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ margin: 0, fontSize: "1.05rem" }}>
              {selectedDay}
              <span className="muted" style={{ fontWeight: 400, marginLeft: "0.5rem" }}>
                {selectedEvents.length} episode{selectedEvents.length === 1 ? "" : "s"}
              </span>
            </h2>
            <button className="btn" type="button" onClick={() => setSelectedDay(null)}>
              Close
            </button>
          </div>
          {!selectedEvents.length ? (
            <p className="muted">No monitored episodes on this day.</p>
          ) : (
            <ul style={{ margin: "0.75rem 0 0", paddingLeft: "1.1rem" }}>
              {selectedEvents.map((e) => (
                <li key={e.id} style={{ marginBottom: "0.35rem" }}>
                  <span className={`badge ${e.status}`}>{e.status}</span>{" "}
                  <Link to={`/channel/${e.source_id}`}>{e.title}</Link>
                  {e.source_title && (
                    <span className="muted"> — {e.source_title}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
