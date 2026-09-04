export type Source = {
  id: number;
  url: string;
  title: string;
  yt_id: string | null;
  source_type: string;
  enabled: boolean;
  monitor_mode: string;
  /** YouTube About text. null = not looked up yet, "" = channel has none. */
  description?: string | null;
  subscriber_count?: number | null;
  quality: string;
  media_type: string;
  folder_name: string;
  poster_path: string | null;
  fanart_path: string | null;
  parent_source_id?: number | null;
  tags?: string;
  season_number?: number;
  last_checked: string | null;
  initialized: boolean;
  created_at: string;
  video_count: number;
  wanted_count: number;
  downloaded_count: number;
  nested_playlist_count?: number;
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
  downloads_paused?: boolean;
};

export type PathMapping = {
  host_path: string;
  plex_path: string;
};

export type Settings = {
  host: string;
  port: number;
  data_dir: string;
  library_root: string;
  music_library_root: string;
  ytdlp_path: string;
  ffmpeg_path?: string;
  ytdlp_cookies_path?: string;
  ytdlp_cookies_from_browser?: string;
  default_quality: string;
  default_music_quality: string;
  format: string;
  music_format: string;
  output_template: string;
  music_output_template: string;
  poll_interval_minutes: number;
  concurrent_downloads: number;
  downloads_paused: boolean;
  nocheck_certificates: boolean;
  sponsorblock_remove: boolean;
  sponsorblock_categories_video: string;
  sponsorblock_categories_music: string;
  path_mappings: PathMapping[];
  plex_enabled?: boolean;
  plex_url?: string;
  plex_token?: string;
  plex_video_section_id?: string;
  plex_music_section_id?: string;
  plex_refresh_debounce_seconds?: number;
  connect_webhook_url?: string;
  connect_on_download?: boolean;
  connect_on_failure?: boolean;
  connect_on_grab?: boolean;
  api_key: string;
  api_auth_required: boolean;
  authentication_method: "none" | "forms";
  username: string;
  has_password: boolean;
  config_path?: string;
  listen_host?: string | null;
  listen_port?: number | null;
  restart_required?: boolean;
};

export type AuthStatus = {
  authentication_method: string;
  forms_required: boolean;
  authenticated: boolean;
  username: string | null;
};

export type SystemStatus = {
  appName: string;
  instanceName: string;
  version: string;
  authentication: string;
  api_auth_required: boolean;
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

export type DiscoverHit = SearchHit & {
  already_added?: boolean;
};

export type DiscoverSection = {
  tag: string;
  source: string;
  based_on: string | null;
  weight: number;
  results: DiscoverHit[];
};

export type DiscoverResponse = {
  sections: DiscoverSection[];
  library_channels: number;
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
  config_path?: string;
  configured_host?: string;
  listen_host?: string | null;
  listen_port?: number | null;
  restart_required?: boolean;
  warnings?: string[];
};

declare global {
  interface Window {
    __YTARR__?: {
      apiKey?: string;
      apiAuthRequired?: boolean;
      authenticationMethod?: string;
      formsRequired?: boolean;
      authenticated?: boolean;
      username?: string;
      port?: number;
    };
  }
}

function getApiKey(): string {
  const fromWindow = window.__YTARR__?.apiKey?.trim();
  if (fromWindow) {
    try {
      localStorage.setItem("ytarr_api_key", fromWindow);
    } catch {
      /* ignore */
    }
    return fromWindow;
  }
  try {
    return localStorage.getItem("ytarr_api_key") || "";
  } catch {
    return "";
  }
}

export function setApiKey(key: string) {
  const trimmed = key.trim();
  if (window.__YTARR__) window.__YTARR__.apiKey = trimmed;
  else window.__YTARR__ = { apiKey: trimmed };
  try {
    localStorage.setItem("ytarr_api_key", trimmed);
  } catch {
    /* ignore */
  }
}

export function clearApiKey() {
  if (window.__YTARR__) window.__YTARR__.apiKey = "";
  try {
    localStorage.removeItem("ytarr_api_key");
  } catch {
    /* ignore */
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const key = getApiKey();
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(key ? { "X-Api-Key": key } : {}),
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
  ping: () => request<{ ok: boolean; app: string }>("/api/ping"),
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  login: (username: string, password: string) =>
    request<{ ok: boolean; username: string; api_key: string }>("/api/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ ok: boolean }>("/api/logout", { method: "POST" }),
  systemStatus: () => request<SystemStatus>("/api/system/status"),
  systemLogs: (maxBytes = 256000) =>
    request<{ path: string; text: string }>(`/api/system/logs?max_bytes=${maxBytes}`),
  clearSystemLogs: () =>
    request<{ ok: boolean; cleared?: string[]; error?: string }>("/api/system/logs", {
      method: "DELETE",
    }),
  clearFailedVideos: () =>
    request<{ ok: boolean; cleared: number }>("/api/videos/clear-failed", { method: "POST" }),
  settings: () => request<Settings>("/api/settings"),
  updateSettings: (body: Partial<Settings> & { password?: string }) => {
    const { api_key: _drop, has_password: _hp, ...rest } = body;
    return request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(rest) });
  },
  regenerateApiKey: () =>
    request<Settings>("/api/settings/regenerate-api-key", { method: "POST" }),
  sources: () => request<Source[]>("/api/sources"),
  source: (id: number) => request<Source>(`/api/sources/${id}`),
  search: (q: string, kind: "channel" | "playlist" | "video" = "channel", limit = 12) => {
    const params = new URLSearchParams({
      q,
      kind,
      limit: String(limit),
    });
    return request<SearchResponse>(`/api/search?${params}`);
  },
  discover: (opts?: { max_tags?: number; per_tag?: number; enrich?: boolean }) => {
    const params = new URLSearchParams();
    if (opts?.max_tags != null) params.set("max_tags", String(opts.max_tags));
    if (opts?.per_tag != null) params.set("per_tag", String(opts.per_tag));
    if (opts?.enrich != null) params.set("enrich", opts.enrich ? "true" : "false");
    const qs = params.toString();
    return request<DiscoverResponse>(`/api/discover${qs ? `?${qs}` : ""}`);
  },
  channelPlaylists: (url: string, limit = 50) => {
    const params = new URLSearchParams({ url, limit: String(limit) });
    return request<SearchResponse>(`/api/search/playlists?${params}`);
  },
  playlistEntries: (url: string, limit = 100) => {
    const params = new URLSearchParams({ url, limit: String(limit) });
    return request<PlaylistEntriesResponse>(`/api/search/entries?${params}`);
  },
  addSource: (
    url: string,
    mode: "new" | "all" | "video" | "none" = "all",
    opts?: {
      quality?: string;
      media_type?: "video" | "audio";
      wanted_video_ids?: string[] | null;
      title?: string | null;
      yt_id?: string | null;
      thumbnail_url?: string | null;
      channel?: string | null;
      parent_source_id?: number | null;
    },
  ) =>
    request<Source>("/api/sources", {
      method: "POST",
      body: JSON.stringify({
        url,
        mode,
        quality: opts?.quality ?? "",
        media_type: opts?.media_type ?? "video",
        ...(opts && "wanted_video_ids" in opts
          ? { wanted_video_ids: opts.wanted_video_ids }
          : {}),
        ...(opts?.title ? { title: opts.title } : {}),
        ...(opts?.yt_id ? { yt_id: opts.yt_id } : {}),
        ...(opts?.thumbnail_url ? { thumbnail_url: opts.thumbnail_url } : {}),
        ...(opts?.channel ? { channel: opts.channel } : {}),
        ...(opts?.parent_source_id != null
          ? { parent_source_id: opts.parent_source_id }
          : {}),
      }),
    }),
  sourceDetailPath: (id: number) => `/channel/${id}`,
  patchSource: (
    id: number,
    body: {
      enabled?: boolean;
      title?: string;
      monitor_mode?: string;
      quality?: string;
      media_type?: string;
      tags?: string;
      parent_source_id?: number;
    },
  ) =>
    request<Source>(`/api/sources/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSource: (id: number, opts?: { deleteFiles?: boolean }) => {
    const q = opts?.deleteFiles ? "?delete_files=true" : "";
    return request<{
      ok: boolean;
      delete_files?: boolean;
      removed?: string[];
      errors?: string[];
    }>(`/api/sources/${id}${q}`, { method: "DELETE" });
  },
  checkSource: (id: number) =>
    request<Record<string, unknown>>(`/api/sources/${id}/check`, { method: "POST" }),
  refreshSourceMetadata: (id: number) =>
    request<Source>(`/api/sources/${id}/refresh-metadata`, { method: "POST" }),
  checkAllSources: () =>
    request<{ ok: boolean; checked: number; results: Record<string, unknown>[] }>(
      "/api/sources/check-all",
      { method: "POST" },
    ),
  backfillSource: (id: number, includeIgnored = false) => {
    const q = includeIgnored ? "?include_ignored=true" : "";
    return request<Record<string, unknown>>(`/api/sources/${id}/backfill${q}`, {
      method: "POST",
    });
  },
  refreshArtwork: (id: number, opts?: { force?: boolean }) => {
    const force = opts?.force !== false;
    const q = force ? "" : "?force=false";
    return request<Source>(`/api/sources/${id}/refresh-artwork${q}`, { method: "POST" });
  },
  videos: (params?: { status?: string; source_id?: number; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.source_id) q.set("source_id", String(params.source_id));
    if (params?.limit != null) q.set("limit", String(params.limit));
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
  pauseQueue: () =>
    request<{ ok: boolean; downloads_paused: boolean }>("/api/queue/pause", {
      method: "POST",
    }),
  resumeQueue: () =>
    request<{ ok: boolean; downloads_paused: boolean }>("/api/queue/resume", {
      method: "POST",
    }),
  clearQueue: () =>
    request<{ ok: boolean; cancelled: number; downloads_paused: boolean }>("/api/queue/clear", {
      method: "POST",
    }),
  retryQueueJob: (id: number) =>
    request<DownloadJob>(`/api/queue/${id}/retry`, { method: "POST" }),
  cancelQueueJob: (id: number) =>
    request<DownloadJob>(`/api/queue/${id}/cancel`, { method: "POST" }),
  posterUrl: (id: number, bust?: string | number) => {
    const params = new URLSearchParams();
    const key = getApiKey();
    if (key) params.set("apikey", key);
    if (bust != null && String(bust)) params.set("v", String(bust));
    const q = params.toString();
    return `/api/sources/${id}/poster${q ? `?${q}` : ""}`;
  },
  fanartUrl: (id: number, bust?: string | number) => {
    const params = new URLSearchParams();
    const key = getApiKey();
    if (key) params.set("apikey", key);
    if (bust != null && String(bust)) params.set("v", String(bust));
    const q = params.toString();
    return `/api/sources/${id}/fanart${q ? `?${q}` : ""}`;
  },
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
  plexSections: (opts?: { plex_url?: string; plex_token?: string }) =>
    request<{ sections: { id: string; title: string; type: string; locations: string[] }[] }>(
      "/api/connect/plex/sections",
      {
        method: "POST",
        body: JSON.stringify({
          plex_url: opts?.plex_url ?? null,
          plex_token: opts?.plex_token ?? null,
        }),
      },
    ),
  plexTest: (opts?: { plex_url?: string; plex_token?: string }) =>
    request<{
      ok: boolean;
      error?: string;
      section_count?: number;
      sections?: { id: string; title: string; type: string }[];
    }>("/api/connect/plex/test", {
      method: "POST",
      body: JSON.stringify({
        plex_url: opts?.plex_url ?? null,
        plex_token: opts?.plex_token ?? null,
      }),
    }),
  plexRefresh: (mediaType: "video" | "audio" = "video") =>
    request<Record<string, unknown>>(
      `/api/connect/plex/refresh?media_type=${encodeURIComponent(mediaType)}`,
      { method: "POST" },
    ),
  systemTasks: () =>
    request<{ tasks: { id: string; name: string; next_run_time: string | null; trigger: string }[] }>(
      "/api/system/tasks",
    ),
  runSystemTask: (taskId: string) =>
    request<Record<string, unknown>>(`/api/system/tasks/${encodeURIComponent(taskId)}/run`, {
      method: "POST",
    }),
  listBackups: () =>
    request<{ backups: { name: string; path: string; size: number; mtime: string }[] }>(
      "/api/system/backup",
    ),
  createBackup: () =>
    request<{ ok: boolean; path: string; name: string; size: number }>("/api/system/backup", {
      method: "POST",
    }),
  restoreBackup: (name: string) =>
    request<{ ok: boolean; restored: string[]; restart_required?: boolean }>(
      `/api/system/backup/restore?name=${encodeURIComponent(name)}`,
      { method: "POST" },
    ),
  systemUpdates: () =>
    request<{
      app_version: string;
      ytdlp_ok: boolean;
      ytdlp_version: string | null;
      ytdlp_error: string | null;
      note?: string;
    }>("/api/system/updates"),
  triggerYtdlpUpdate: () =>
    request<Record<string, unknown>>("/api/system/updates/ytdlp", { method: "POST" }),
  calendar: (start?: string, end?: string) => {
    const q = new URLSearchParams();
    if (start) q.set("start", start);
    if (end) q.set("end", end);
    const qs = q.toString();
    return request<{
      events: {
        id: number;
        title: string;
        video_id: string;
        status: string;
        published_at: string | null;
        source_id: number;
        source_title: string | null;
      }[];
      start: string;
      end: string;
    }>(`/api/calendar${qs ? `?${qs}` : ""}`);
  },
  blocklist: (limit = 200) =>
    request<{
      items: {
        id: number;
        title: string;
        video_id: string;
        error: string | null;
        source_id: number;
        source_title: string | null;
        updated_at: string | null;
      }[];
    }>(`/api/blocklist?limit=${limit}`),
  unblock: (videoId: number) =>
    request<{ ok: boolean }>(`/api/blocklist/${videoId}`, { method: "DELETE" }),
  importScan: (limit = 200) =>
    request<{
      items: { path: string; video_id: string; title: string; already_in_db: boolean }[];
    }>(`/api/import/scan?limit=${limit}`),
  importApply: (items: { path: string; video_id: string; title?: string }[], sourceId?: number) =>
    request<{ imported: number; skipped: number; errors: string[] }>("/api/import/apply", {
      method: "POST",
      body: JSON.stringify({ items, source_id: sourceId ?? null }),
    }),
  interactiveSearch: (sourceId: number, q?: string, limit = 20) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (q) params.set("q", q);
    return request<{
      query: string;
      results: (SearchHit & { in_library?: boolean; library_status?: string })[];
    }>(`/api/sources/${sourceId}/interactive-search?${params}`);
  },
  interactiveGrab: (
    sourceId: number,
    body: { video_id: string; title?: string; url?: string },
  ) =>
    request<{
      ok: boolean;
      created?: boolean;
      already?: boolean;
      video_id: number;
      youtube_id?: string;
      status: string;
      message: string;
    }>(`/api/sources/${sourceId}/interactive-search/grab`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  tags: () => request<{ tags: string[]; counts?: Record<string, number> }>("/api/tags"),
  renameTag: (from: string, to: string) =>
    request<{ ok: boolean; updated: number }>("/api/tags/rename", {
      method: "POST",
      body: JSON.stringify({ from, to }),
    }),
  deleteTag: (tag: string) =>
    request<{ ok: boolean; updated: number }>(`/api/tags/${encodeURIComponent(tag)}`, {
      method: "DELETE",
    }),
};
