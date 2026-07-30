export type ThemeId = "forest" | "youtube";

export const THEME_OPTIONS: { id: ThemeId; label: string; blurb: string }[] = [
  { id: "forest", label: "Forest (Lidarr green)", blurb: "Default dark green accent" },
  { id: "youtube", label: "YouTube red", blurb: "Scarlet accent on a charcoal UI" },
];

const STORAGE_KEY = "ytarr_theme";

export function getStoredTheme(): ThemeId {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "youtube" || raw === "forest") return raw;
  } catch {
    /* ignore */
  }
  return "forest";
}

export function applyTheme(theme: ThemeId) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* ignore */
  }
}

export function initTheme(): ThemeId {
  const theme = getStoredTheme();
  applyTheme(theme);
  return theme;
}
