import { useEffect, useState } from "react";
import { FluidButton } from "./FluidButton";
import { JarvisFrame } from "./JarvisFrame";

type JarvisStatus = {
  reachable: boolean;
  url: string;
  web_app: string;
  detail: string;
  version: string | null;
};

export function JarvisEmbed() {
  const [status, setStatus] = useState<JarvisStatus | null>(null);
  const [error, setError] = useState("");
  const [embedReady, setEmbedReady] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetch("/api/jarvis/status")
        .then(async (r) => {
          const body = await r.json().catch(() => ({}));
          if (!r.ok) {
            const detail = typeof body.detail === "string" ? body.detail : `HTTP ${r.status}`;
            if (r.status === 404) {
              throw new Error(
                "Assistant API is out of date (missing /api/jarvis/status). Restart assistant/start.sh.",
              );
            }
            throw new Error(detail);
          }
          return body as JarvisStatus;
        })
        .then((body) => {
          if (cancelled) return;
          if (body.reachable) setEmbedReady(true);
          setStatus(body);
          setError("");
        })
        .catch((err: Error) => {
          if (cancelled) return;
          if (!embedReady) setError(err.message);
          setStatus(null);
        });
    load();
    const timer = window.setInterval(load, 45000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [embedReady]);

  const embedded = embedReady || status?.reachable === true;

  if (!embedded && !status && !error) {
    return <p className="muted">Checking J.A.R.V.I.S.…</p>;
  }

  if (!embedded) {
    return (
      <section>
        <h2>J.A.R.V.I.S.</h2>
        {error && <p className="error" role="alert">{error}</p>}
        <p className="banner">{status?.detail || "J.A.R.V.I.S. is not reachable."}</p>
        <pre className="card" style={{ whiteSpace: "pre-wrap", fontSize: "0.85rem" }}>
{`export JARVIS_ROOT="$HOME/Downloads/PersonalJarvis-main"
assistant/scripts/jarvis.sh install   # once
assistant/scripts/jarvis.sh start`}
        </pre>
        <div className="row">
          <FluidButton type="button" variant="primary" onClick={() => window.location.reload()}>
            Check again
          </FluidButton>
          <a href={status?.web_app || "http://127.0.0.1:47821/"} target="_blank" rel="noreferrer">
            Open J.A.R.V.I.S. directly
          </a>
        </div>
      </section>
    );
  }

  const base = status?.url || "http://127.0.0.1:47821";

  return (
    <section className="jarvis-shell">
      <div className="jarvis-toolbar">
        <h2 className="jarvis-heading">J.A.R.V.I.S.</h2>
        <div className="row">
          <a href={status?.web_app || base} target="_blank" rel="noreferrer">
            Open full tab
          </a>
          <span className="muted" style={{ fontSize: "0.85rem" }}>
            {status?.version ? `v${status.version}` : ""} · Models and keys in J.A.R.V.I.S. Settings
          </span>
        </div>
      </div>
      {status && !status.reachable && (
        <p className="banner" role="status">
          J.A.R.V.I.S. is slow to answer status checks. The panel below stays loaded — use Open full tab if it freezes.
        </p>
      )}
      <JarvisFrame baseUrl={base} />
    </section>
  );
}
