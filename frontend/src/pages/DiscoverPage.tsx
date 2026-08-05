import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DiscoverHit, type DiscoverSection, type SearchHit } from "../api";
import { ChannelAddModal } from "../components/ChannelAddModal";
import { findExistingPlaylist } from "../components/playlistMatch";

async function kickQueue() {
  void api.processQueue().catch(() => undefined);
}

export function DiscoverPage() {
  const [sections, setSections] = useState<DiscoverSection[]>([]);
  const [libraryChannels, setLibraryChannels] = useState(0);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [picker, setPicker] = useState<SearchHit | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [enrich, setEnrich] = useState(true);

  const load = async (useEnrich = enrich) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.discover({ max_tags: 8, per_tag: 8, enrich: useEnrich });
      setSections(data.sections);
      setLibraryChannels(data.library_channels);
      setActiveTag((prev) => {
        if (prev && data.sections.some((s) => s.tag === prev)) return prev;
        return data.sections[0]?.tag ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(true);
  }, []);

  const visible = activeTag ? sections.filter((s) => s.tag === activeTag) : sections;

  const openAdd = (hit: DiscoverHit) => {
    setPicker({
      kind: hit.kind || "channel",
      title: hit.title,
      url: hit.url,
      id: hit.id,
      channel: hit.channel,
      thumbnail_url: hit.thumbnail_url,
      duration: hit.duration,
      description: hit.description,
      video_count: hit.video_count,
    });
  };

  const onConfirm = async (selection: {
    monitorUploads: boolean;
    uploadVideoIds: string[] | null;
    playlists: { hit: SearchHit; videoIds: string[] | null }[];
  }) => {
    if (!picker) return;
    setConfirming(true);
    setError(null);
    setMessage(null);
    try {
      const channelMode = selection.monitorUploads
        ? selection.uploadVideoIds != null
          ? "none"
          : "all"
        : "none";
      const channelSource = await api.addSource(picker.url, channelMode, {
        title: picker.title,
        yt_id: picker.id,
        thumbnail_url: picker.thumbnail_url,
        ...(selection.monitorUploads && selection.uploadVideoIds != null
          ? { wanted_video_ids: selection.uploadVideoIds }
          : {}),
      });

      const known = await api.sources();
      for (const { hit, videoIds } of selection.playlists) {
        const existing = findExistingPlaylist([...known, channelSource], hit);
        const playlistMode = videoIds != null ? "none" : "all";
        const playlistOpts = {
          title: hit.title,
          yt_id: hit.id,
          thumbnail_url: hit.thumbnail_url,
          parent_source_id: channelSource.id,
          ...(videoIds != null ? { wanted_video_ids: videoIds } : {}),
        };
        if (!existing) {
          await api.addSource(hit.url, playlistMode, playlistOpts);
        } else if (!existing.enabled) {
          await api.patchSource(existing.id, {
            enabled: true,
            monitor_mode: playlistMode,
          });
          if (videoIds != null) await api.addSource(hit.url, playlistMode, playlistOpts);
          else {
            await api.backfillSource(existing.id, false);
            await api.addSource(hit.url, playlistMode, {
              parent_source_id: channelSource.id,
              title: hit.title,
              yt_id: hit.id,
            });
          }
        } else if (videoIds != null) {
          await api.addSource(hit.url, playlistMode, playlistOpts);
        } else {
          await api.addSource(hit.url, "all", {
            parent_source_id: channelSource.id,
            title: hit.title,
            yt_id: hit.id,
          });
        }
      }

      await kickQueue();
      setMessage(`Added ${channelSource.title}.`);
      setPicker(null);
      await load(enrich);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setConfirming(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Discover</h1>
          <p>
            Channels similar to your library — mined from channel names, video-title tags, and
            YouTube metadata (Radarr Discover for YouTube).
          </p>
        </div>
        <div className="row">
          <label className="mode-option" style={{ margin: 0 }}>
            <input
              type="checkbox"
              checked={enrich}
              onChange={(e) => setEnrich(e.target.checked)}
            />
            <span>
              <strong>Use metadata tags</strong>
              <small>Slower — pulls tags from your channels via yt-dlp</small>
            </span>
          </label>
          <button
            className="btn"
            type="button"
            disabled={loading}
            onClick={() => void load(enrich)}
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success">{message}</div>}

      {!loading && libraryChannels === 0 && (
        <div className="panel empty-library">
          <h2 style={{ marginTop: 0 }}>Add channels first</h2>
          <p className="muted">
            Discover needs at least one channel in your library so it can read tags and suggest
            similar creators.
          </p>
          <Link className="btn btn-primary" to="/add">
            Add New
          </Link>
        </div>
      )}

      {!loading && libraryChannels > 0 && sections.length === 0 && !error && (
        <div className="panel">
          <p className="muted" style={{ margin: 0 }}>
            No recommendations yet. Try Refresh with metadata tags enabled, or add more videos so
            title tags can be mined.
          </p>
        </div>
      )}

      {sections.length > 0 && (
        <div className="discover-tags">
          <button
            type="button"
            className={`discover-tag ${activeTag == null ? "active" : ""}`}
            onClick={() => setActiveTag(null)}
          >
            All
          </button>
          {sections.map((section) => (
            <button
              key={section.tag}
              type="button"
              className={`discover-tag ${activeTag === section.tag ? "active" : ""}`}
              onClick={() => setActiveTag(section.tag)}
              title={
                section.based_on
                  ? `Based on ${section.based_on} (${section.source})`
                  : section.source
              }
            >
              {section.tag}
            </button>
          ))}
        </div>
      )}

      {loading && <p className="muted">Scanning library tags and searching YouTube…</p>}

      {visible.map((section) => (
        <section key={section.tag} className="discover-section">
          <div className="section-head">
            <h2>{section.tag}</h2>
            <span className="muted">
              {section.source === "library_channel"
                ? `More like ${section.based_on || section.tag}`
                : section.source === "metadata_tag"
                  ? `Tag from ${section.based_on || "library metadata"}`
                  : "From titles in your library"}
            </span>
          </div>
          <div className="discover-grid">
            {section.results.map((hit) => (
              <article key={hit.url} className="discover-card">
                <div className="discover-card-art">
                  {hit.thumbnail_url ? (
                    <img src={hit.thumbnail_url} alt="" />
                  ) : (
                    <div className="poster-card-placeholder">No art</div>
                  )}
                </div>
                <div className="discover-card-body">
                  <div className="discover-card-title" title={hit.title}>
                    {hit.title}
                  </div>
                  {hit.description && (
                    <p className="muted discover-card-desc">{hit.description}</p>
                  )}
                  <button className="btn btn-primary" type="button" onClick={() => openAdd(hit)}>
                    Add
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}

      {picker && (
        <ChannelAddModal
          channel={picker}
          busy={confirming}
          onClose={() => !confirming && setPicker(null)}
          onConfirm={(sel) => void onConfirm(sel)}
        />
      )}
    </>
  );
}
