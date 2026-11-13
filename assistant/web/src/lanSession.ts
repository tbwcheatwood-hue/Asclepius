const TOKEN_KEY = "assistant.lan.token";
const CSRF_KEY = "assistant.lan.csrf";

export function isRemoteBrowser(): boolean {
  const host = window.location.hostname;
  return host !== "localhost" && host !== "127.0.0.1";
}

export function lanHeaders(): Record<string, string> {
  if (!isRemoteBrowser()) return {};
  const token = sessionStorage.getItem(TOKEN_KEY);
  const csrf = sessionStorage.getItem(CSRF_KEY);
  const headers: Record<string, string> = {};
  if (token) headers["x-assistant-lan-token"] = token;
  if (csrf) headers["x-assistant-csrf"] = csrf;
  return headers;
}

export function saveLanSession(token: string, csrf: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(CSRF_KEY, csrf);
}

export function clearLanSession(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(CSRF_KEY);
}
