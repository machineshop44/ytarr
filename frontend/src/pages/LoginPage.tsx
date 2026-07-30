import { type FormEvent, useState } from "react";
import { api, setApiKey } from "../api";
import { BrandMark } from "../icons";

const SAVED_USERNAME_KEY = "ytarr_saved_username";

function readSavedUsername(): string {
  try {
    return localStorage.getItem(SAVED_USERNAME_KEY)?.trim() || "";
  } catch {
    return "";
  }
}

type LoginPageProps = {
  onLoggedIn: (username: string) => void;
};

export function LoginPage({ onLoggedIn }: LoginPageProps) {
  const savedUsername = readSavedUsername();
  const [username, setUsername] = useState(savedUsername);
  const [password, setPassword] = useState("");
  const [saveUsername, setSaveUsername] = useState(!!savedUsername);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const persistUsernamePreference = (name: string, remember: boolean) => {
    try {
      if (remember && name) {
        localStorage.setItem(SAVED_USERNAME_KEY, name);
      } else {
        localStorage.removeItem(SAVED_USERNAME_KEY);
      }
    } catch {
      /* ignore quota / private mode */
    }
  };

  const onSaveUsernameChange = (checked: boolean) => {
    setSaveUsername(checked);
    if (!checked) {
      persistUsernamePreference("", false);
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const trimmed = username.trim();
    try {
      const res = await api.login(trimmed, password);
      if (res.api_key) setApiKey(res.api_key);
      persistUsernamePreference(trimmed, saveUsername);
      onLoggedIn(res.username);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-shell">
      <form className="login-panel" onSubmit={(e) => void onSubmit(e)}>
        <div className="login-brand">
          <BrandMark size={48} />
          <div>
            <div className="brand-name">ytarr</div>
            <div className="brand-sub">Sign in</div>
          </div>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          Same username and password as your other *arr apps.
        </p>
        {error && <div className="error">{error}</div>}
        <div className="field">
          <label htmlFor="login-user">Username</label>
          <input
            id="login-user"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={busy}
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="login-pass">Password</label>
          <input
            id="login-pass"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy}
          />
        </div>
        <label className="mode-option" style={{ marginBottom: 0, padding: "0.35rem 0" }}>
          <input
            type="checkbox"
            checked={saveUsername}
            onChange={(e) => onSaveUsernameChange(e.target.checked)}
            disabled={busy}
          />
          <span>
            <strong>Save username</strong>
            <small>Remember this username on this device. Password is not saved.</small>
          </span>
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Log in"}
        </button>
      </form>
    </div>
  );
}
