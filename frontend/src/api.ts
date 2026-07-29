export type Source = {
  id: number;
  url: string;
  title: string;
  yt_id: string | null;
  source_type: string;
  enabled: boolean;
  monitor_mode: string;
  folder_name: string;
  poster_path: string | null;
  fanart_path: string | null;
  last_checked: string | null;
  initialized: boolean;
  created_at: string;
  video_count: number;
  wanted_count: number;
  downloaded_count: number;
};

export type Video = {
  id: number;
  source_id: number;
  video_id: string;
  title: string;
  published_at: string | null;
  duration: number | null;
  thumbnail_url: string | null;
  file_path: string | null;
  status: string;
  error: string | null;
  source_title: string | null;
  created_at: string;
};

export type DownloadJob = {
  id: number;
  video_id: number;
  progress: number;
  status: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  video_title: string | null;
  youtube_id: string | null;
  source_title: string | null;
};

export type Dashboard = {
  sources: number;
  enabled_sources: number;
  videos: number;
  wanted: number;
  downloading: number;
  downloaded: number;
  failed: number;
  queue_size: number;
  ytdlp_ok: boolean;
  ytdlp_version: string | null;
};

export type Settings = {
  host: string;
  port: number;
  data_dir: string;
  library_root: string;
  ytdlp_path: string;
  ffmpeg_path?: string;
  format: string;
  output_template: string;
  poll_interval_minutes: number;
  concurrent_downloads: number;
  nocheck_certificates: boolean;
};

export type SearchHit = {
  kind: string;
  title: string;
  url: string;
  id: string | null;
  channel: string | null;
  thumbnail_url: string | null;
  duration: number | null;
  description: string | null;
  video_count?: number | null;
};

export type SearchResponse = {
  query: string;
  kind: string;
  results: SearchHit[];
};

export type PlaylistEntryPreview = {
  video_id: string;
  title: string;
  published_at: string | null;
  duration: number | null;
  thumbnail_url: string | null;
  url: string | null;
};

export type PlaylistEntriesResponse = {
  url: string;
  entries: PlaylistEntryPreview[];
};

export type RenameItem = {
  video_db_id: number;
  youtube_id: string;
  title: string;
  source_title: string;
  current_path: string | null;
  new_path: string;
  needs_rename: boolean;
  reason: string | null;
};

export type RenamePreview = {
  items: RenameItem[];
  needs_rename_count: number;
};

export type RenameApplyResult = {
  renamed: number;
  skipped: number;
  planned: number;
  errors: string[];
};

export type Health = {
  status: string;
  ytdlp_ok: boolean;
  ytdlp_version: string | null;
  ytdlp_error: string | null;
  library_root: string;
  library_exists: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  dashboard: () => request<Dashboard>("/api/dashboard"),
  health: () => request<Health>("/api/health"),
  settings: () => request<Settings>("/api/settings"),
  updateSettings: (body: Partial<Settings>) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  sources: () => request<Source[]>("/api/sources"),
  search: (q: string, kind: "channel" | "playlist" | "video" = "channel", limit = 12) => {
    const params = new URLSearchParams({
      q,
      kind,
      limit: String(limit),
    });
    return request<SearchResponse>(`/api/search?${params}`);
  },
  channelPlaylists: (url: string, limit = 50) => {
    const params = new URLSearchParams({ url, limit: String(limit) });
    return request<SearchResponse>(`/api/search/playlists?${params}`);
  },
  playlistEntries: (url: string, limit = 100) => {
    const params = new URLSearchParams({ url, limit: String(limit) });
    return request<PlaylistEntriesResponse>(`/api/search/entries?${params}`);
  },
  addSource: (url: string, mode: "new" | "all" | "video" = "all") =>
    request<Source>("/api/sources", {
      method: "POST",
      body: JSON.stringify({ url, mode }),
    }),
  sourceDetailPath: (id: number) => `/channel/${id}`,
  patchSource: (id: number, body: { enabled?: boolean; title?: string; monitor_mode?: string }) =>
    request<Source>(`/api/sources/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSource: (id: number) =>
    request<{ ok: boolean }>(`/api/sources/${id}`, { method: "DELETE" }),
  checkSource: (id: number) =>
    request<Record<string, unknown>>(`/api/sources/${id}/check`, { method: "POST" }),
  backfillSource: (id: number) =>
    request<Record<string, unknown>>(`/api/sources/${id}/backfill`, { method: "POST" }),
  refreshArtwork: (id: number) =>
    request<Source>(`/api/sources/${id}/refresh-artwork`, { method: "POST" }),
  videos: (params?: { status?: string; source_id?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.source_id) q.set("source_id", String(params.source_id));
    const qs = q.toString();
    return request<Video[]>(`/api/videos${qs ? `?${qs}` : ""}`);
  },
  retryVideo: (id: number) =>
    request<Video>(`/api/videos/${id}/retry`, { method: "POST" }),
  ignoreVideo: (id: number) =>
    request<Video>(`/api/videos/${id}/ignore`, { method: "POST" }),
  queue: (params?: { status?: string; limit?: number; source_id?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.source_id != null) q.set("source_id", String(params.source_id));
    const qs = q.toString();
    return request<DownloadJob[]>(`/api/queue${qs ? `?${qs}` : ""}`);
  },
  processQueue: () => request<{ ok: boolean }>("/api/queue/process", { method: "POST" }),
  retryQueueJob: (id: number) =>
    request<DownloadJob>(`/api/queue/${id}/retry`, { method: "POST" }),
  cancelQueueJob: (id: number) =>
    request<DownloadJob>(`/api/queue/${id}/cancel`, { method: "POST" }),
  posterUrl: (id: number) => `/api/sources/${id}/poster`,
  renamePreview: (sourceId?: number) => {
    const q = new URLSearchParams();
    if (sourceId != null) q.set("source_id", String(sourceId));
    const qs = q.toString();
    return request<RenamePreview>(`/api/rename/preview${qs ? `?${qs}` : ""}`);
  },
  renameApply: (body: { source_id?: number; video_ids?: number[] }) =>
    request<RenameApplyResult>("/api/rename/apply", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
