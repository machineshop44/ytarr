import type { SearchHit, Source } from "../api";

/** Match a live playlist hit to an already-monitored source. */
export function findExistingPlaylist(sources: Source[], hit: SearchHit): Source | undefined {
  const hitId = hit.id || playlistListId(hit.url);
  return sources.find((s) => {
    if (s.source_type === "channel" || s.source_type === "video") return false;
    if (hit.url && urlsRoughlyEqual(s.url, hit.url)) return true;
    const sid = s.yt_id || playlistListId(s.url);
    return Boolean(hitId && sid && (hitId === sid || hitId.startsWith(sid) || sid.startsWith(hitId)));
  });
}

export function playlistListId(url: string): string | null {
  try {
    const u = new URL(url);
    return u.searchParams.get("list");
  } catch {
    const m = url.match(/[?&]list=([^&]+)/i);
    return m ? decodeURIComponent(m[1]) : null;
  }
}

export function urlsRoughlyEqual(a: string, b: string): boolean {
  const norm = (u: string) => u.trim().replace(/\/+$/, "").toLowerCase();
  if (norm(a) === norm(b)) return true;
  const idA = playlistListId(a);
  const idB = playlistListId(b);
  return Boolean(idA && idB && idA === idB);
}
