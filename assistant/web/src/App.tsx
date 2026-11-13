import { useCallback, useEffect, useState, type ReactNode } from "react";
import { CascadeItem, CascadeNav } from "./CascadeNav";
import { confirmedPayload, useConfirm } from "./useConfirm";
import { FluidButton } from "./FluidButton";
import { JarvisEmbed } from "./JarvisEmbed";
import { clearLanSession, isRemoteBrowser, lanHeaders, saveLanSession } from "./lanSession";

type View = "today" | "jarvis" | "calendar" | "medications" | "reminders" | "notes" | "memory" | "records" | "settings";

type JarvisAction = {
  summary: string;
  method: string;
  path: string;
  body: Record<string, unknown> | null;
  confirm: boolean;
};

type JarvisTurn = {
  reply: string;
  proposal: { id: number; summary: string; status: string } | null;
  action: JarvisAction | null;
};

async function performJarvisAction(action: JarvisAction): Promise<string> {
  const init: RequestInit = { method: action.method };
  if (action.body != null) init.body = JSON.stringify(action.body);
  const body = await api<unknown>(action.path, init);
  if (body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string") {
    return (body as { detail: string }).detail;
  }
  return "Done.";
}

type Settings = {
  provider: string;
  lmstudio_url: string;
  als_url: string;
  als_api_token: string;
  lmstudio_model: string;
  consent: boolean;
  timezone: string;
  text_scale: string;
  contrast: string;
  reduced_motion: boolean;
  gsconnect_push: boolean;
  gsconnect_device: string;
  google_client_id: string;
  google_client_secret: string;
  voice_speak_replies: boolean;
  butler_mode: boolean;
  file_search_roots: string;
};

type GoogleStatus = {
  linked: boolean;
  client_id_set: boolean;
  events_cached: number;
  redirect_uri: string;
  scope: string;
};

type GsDevice = { path: string; name: string; connected: boolean };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...lanHeaders(), ...(options?.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(typeof body.detail === "string" ? body.detail : "Request failed");
  }
  return response.json();
}

const VIEWS: { id: View; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "jarvis", label: "J.A.R.V.I.S." },
  { id: "calendar", label: "Calendar" },
  { id: "medications", label: "Meds Tracker" },
  { id: "reminders", label: "Reminders" },
  { id: "notes", label: "Notes" },
  { id: "memory", label: "Fasten Health" },
  { id: "records", label: "Quick save" },
  { id: "settings", label: "Settings" },
];

function LanGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(!isRemoteBrowser());
  const [code, setCode] = useState("");
  const [device, setDevice] = useState("Phone");
  const [message, setMessage] = useState("");
  if (ready) return <>{children}</>;
  return (
    <section className="lan-gate card">
      <h2>Pair this device</h2>
      <p className="muted">
        Enter the six-digit pairing code from the terminal that started the mobile tunnel (or Settings → Phone on your Wi‑Fi on this computer).
        After ngrok Google sign-in, your session is stored on this device until it expires.
      </p>
      <label>
        <span>Six-digit code</span>
        <input aria-label="Pairing code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
      </label>
      <label>
        <span>Device name</span>
        <input aria-label="Device name" value={device} onChange={(e) => setDevice(e.target.value)} />
      </label>
      {message && <p className="error" role="alert">{message}</p>}
      <FluidButton
        type="button"
        variant="primary"
        onClick={async () => {
          try {
            const body = await api<{ token: string; csrf_token: string }>("/api/lan/pair", {
              method: "POST",
              body: JSON.stringify({ code, device_label: device }),
            });
            saveLanSession(body.token, body.csrf_token);
            setReady(true);
          } catch (err) {
            setMessage(err instanceof Error ? err.message : "Pairing failed");
          }
        }}
      >
        Pair
      </FluidButton>
    </section>
  );
}

export function App() {
  const [view, setView] = useState<View>("jarvis");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  const [listening, setListening] = useState(false);
  const [jarvisNote, setJarvisNote] = useState("");
  const ask = useConfirm();
  useEffect(() => {
    api<Settings>("/api/settings").then(setSettings).catch((err: Error) => setError(err.message));
    const params = new URLSearchParams(window.location.search);
    const nextView = params.get("view");
    if (nextView && VIEWS.some((item) => item.id === nextView)) {
      setView(nextView as View);
    }
    if (params.get("google") === "linked") {
      setError("");
      window.history.replaceState({}, "", window.location.pathname);
    }
    const onChronos = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (event.data?.type === "chronos-open-settings") setView("settings");
    };
    window.addEventListener("message", onChronos);
    return () => window.removeEventListener("message", onChronos);
  }, []);

  useEffect(() => {
    const tick = () => api("/api/alerts/tick", { method: "POST" }).catch(() => undefined);
    tick();
    const timer = window.setInterval(tick, 30000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!settings) return;
    document.documentElement.dataset.scale = settings.text_scale;
    document.documentElement.dataset.contrast = settings.contrast;
    document.documentElement.dataset.motion = settings.reduced_motion ? "reduce" : "no-preference";
  }, [settings]);

  const runJarvis = useCallback(async (message: string, tab: View) => {
    const result = await api<JarvisTurn>("/api/assistant/message", {
      method: "POST",
      body: JSON.stringify({ message, tab }),
    });
    setJarvisNote(result.reply);
    setError("");
    const follow = async (action: JarvisAction) => {
      try {
        setJarvisNote(await performJarvisAction(action));
      } catch (err) {
        setJarvisNote(err instanceof Error ? err.message : "J.A.R.V.I.S. could not do that.");
      }
    };
    if (result.proposal) {
      ask({
        title: "Confirm",
        description: result.proposal.summary,
        confirmLabel: "Confirm",
        onConfirm: () => api(`/api/assistant/proposals/${result.proposal!.id}/confirm`, { method: "POST" })
          .then(() => setJarvisNote("Saved."))
          .catch((err: Error) => setJarvisNote(err.message)),
      });
    } else if (result.action?.confirm) {
      ask({
        title: "Confirm",
        description: result.action.summary,
        confirmLabel: "Confirm",
        onConfirm: () => follow(result.action!),
      });
    } else if (result.action) {
      await follow(result.action);
    }
    return result;
  }, [ask]);

  useEffect(() => {
    const frame = document.querySelector("iframe.jarvis-frame") as HTMLIFrameElement | null;
    frame?.contentWindow?.postMessage({ type: "assistant-tab", tab: view }, "*");
  }, [view]);

  useEffect(() => {
    const onSpeech = (event: Event) => {
      const message = (event as CustomEvent<string>).detail?.trim();
      if (!message) return;
      void runJarvis(message, view).catch((err: Error) => setJarvisNote(err.message));
    };
    window.addEventListener("assistant-speech", onSpeech);
    return () => window.removeEventListener("assistant-speech", onSpeech);
  }, [view, runJarvis]);

  const speak = useCallback(() => {
    const SpeechRecognition = (window as unknown as { SpeechRecognition?: new () => SpeechRec; webkitSpeechRecognition?: new () => SpeechRec }).SpeechRecognition
      || (window as unknown as { webkitSpeechRecognition?: new () => SpeechRec }).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setError("This browser does not offer speech input.");
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.onresult = (event) => {
      const text = event.results[0][0].transcript;
      window.dispatchEvent(new CustomEvent("assistant-speech", { detail: text }));
      setListening(false);
    };
    recognition.onerror = () => {
      setError("Speech input could not use the microphone.");
      setListening(false);
    };
    setListening(true);
    recognition.start();
  }, []);

  return (
    <LanGate>
    <div className={view === "calendar" || view === "medications" || view === "memory" ? "layout layout-calendar" : "layout"}>
      <a className="skip" href="#main">Skip to content</a>
      <header>
        <h1>Assistant</h1>
        <p className="muted">J.A.R.V.I.S. for voice and agents. Calendar, meds tracker, and reminders stay here.</p>
        <CascadeNav label="Sections">
          {VIEWS.map((item, index) => (
            <CascadeItem key={item.id} index={index} active={view === item.id} onClick={() => setView(item.id)}>
              {item.label}
            </CascadeItem>
          ))}
        </CascadeNav>
        <FluidButton
          variant="primary"
          aria-pressed={listening}
          onClick={speak}
          style={{ marginTop: "1rem", width: "100%" }}
        >
          {listening ? "Listening" : "Speech input"}
        </FluidButton>
        {jarvisNote && <p className="muted" role="status">{jarvisNote}</p>}
      </header>
      <main id="main">
        {error && <p className="error" role="alert">{error}</p>}
        {view === "today" && <Today />}
        {view === "calendar" && <Calendar />}
        {view === "medications" && <Medications />}
        {view === "reminders" && <Reminders />}
        {view === "notes" && <Notes />}
        {view === "memory" && <Memory />}
        {view === "jarvis" && <JarvisEmbed />}
        {view === "records" && <Chat />}
        {view === "settings" && settings && <SettingsForm initial={settings} onSaved={setSettings} />}
      </main>
      <aside aria-label="Operations">
        <Operations />
      </aside>
    </div>
    </LanGate>
  );
}

type SpeechRec = {
  lang: string;
  onresult: (event: { results: { 0: { 0: { transcript: string } } } }) => void;
  onerror: () => void;
  start: () => void;
};

function Operations() {
  const [data, setData] = useState<{
    assistant: string;
    provider: string;
    notice: string;
    capabilities: string[];
    jarvis?: { reachable: boolean; detail: string; version: string | null };
    upcoming: { title: string; state: string }[];
    actions: { summary: string; status: string }[];
    repairs: { status: string }[];
    background_jobs: unknown[];
  } | null>(null);
  useEffect(() => {
    const load = () => api<NonNullable<typeof data>>("/api/dashboard").then(setData).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, []);
  if (!data) return <p>Loading status.</p>;
  return (
    <>
      <h2>Status</h2>
      <div className="card">
        <p>Assistant: {data.assistant === "off" ? "off" : "available"}</p>
        <p>Provider: {data.provider}</p>
        <p>Background work: {data.background_jobs.length === 0 ? "nothing is running" : "running"}</p>
        <p className="muted">{data.notice}</p>
        <p className="muted">
          J.A.R.V.I.S.: {data.jarvis?.reachable ? `running (v${data.jarvis.version || "?"})` : data.jarvis?.detail || "unknown"}
        </p>
      </div>
      <h2>Coming up</h2>
      {data.upcoming.length === 0 && <p>No upcoming items.</p>}
      {data.upcoming.map((item, index) => (
        <p key={index}>{item.state}: {item.title}</p>
      ))}
      <h2>Recent actions</h2>
      {data.actions.length === 0 && <p>No actions yet.</p>}
      {data.actions.map((item, index) => (
        <p key={index}>{item.status}: {item.summary}</p>
      ))}
      <h2>Repairs</h2>
      {data.repairs.length === 0 && <p>No repair proposal. The program is not changing itself.</p>}
      {data.repairs.map((item, index) => (
        <p key={index}>{item.status}</p>
      ))}
    </>
  );
}

function Today() {
  const ask = useConfirm();
  const [items, setItems] = useState<{ kind: string; id: number; title: string; due_at: string; state: string; demo: boolean }[]>([]);
  const [zone, setZone] = useState("");
  const load = () => api<{ items: typeof items; timezone: string }>("/api/upcoming").then((body) => {
    setItems(body.items);
    setZone(body.timezone);
  });
  useEffect(() => { load().catch(() => undefined); }, []);
  const due = items.filter((item) => item.state === "missed");
  return (
    <section>
      <h2>Today</h2>
      <p className="muted">Times use {zone || "the saved time zone"}. A missed item stayed due because the page was not open when it came up. Acknowledging it does not delete the record.</p>
      {due.length > 0 && (
        <FluidButton
          type="button"
          onClick={() =>
            ask({
              title: "Dismiss all due notifications?",
              description: `This will acknowledge ${due.length} due notification(s) on your list. Records stay saved; only the alerts are cleared.`,
              confirmLabel: "Dismiss all",
              onConfirm: () => api("/api/dismissals/due", { method: "POST", body: confirmedPayload() }).then(load),
            })
          }
        >
          Dismiss all due
        </FluidButton>
      )}
      {due.map((item) => (
        <div className="banner" role="status" key={`${item.kind}-${item.id}`}>
          <p>{item.title} is due.</p>
          {item.kind === "appointment" && (
            <button
              type="button"
              onClick={() =>
                ask({
                  title: "Dismiss appointment reminder?",
                  description: `Dismiss the notification for “${item.title}”. The appointment remains on your calendar.`,
                  confirmLabel: "Dismiss",
                  onConfirm: () =>
                    api(`/api/appointments/${item.id}/acknowledge`, { method: "POST", body: confirmedPayload() }).then(load),
                })
              }
            >
              Dismiss
            </button>
          )}
          {item.kind === "reminder" && (
            <button
              type="button"
              onClick={() =>
                ask({
                  title: "Dismiss reminder?",
                  description: `Dismiss the notification for “${item.title}”. The reminder record stays unless you delete it.`,
                  confirmLabel: "Dismiss",
                  onConfirm: () =>
                    api(`/api/reminders/${item.id}/acknowledge`, { method: "POST", body: confirmedPayload() }).then(load),
                })
              }
            >
              Dismiss
            </button>
          )}
        </div>
      ))}
      {items.length === 0 && <p>Nothing is scheduled.</p>}
      <ul>
        {items.map((item) => (
          <li key={`${item.kind}-${item.id}-${item.due_at}`}>{item.title} · {item.state}{item.demo ? " · sample" : ""}</li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() =>
          ask({
            title: "Delete sample data?",
            description: "Remove demo appointments, medications, and reminders. Your own records are not affected.",
            confirmLabel: "Delete sample data",
            onConfirm: () => api("/api/demo", { method: "DELETE", body: confirmedPayload() }).then(load),
          })
        }
      >
        Delete sample data
      </button>
    </section>
  );
}

function Calendar() {
  return (
    <iframe
      className="chronos-frame"
      title="Chronos calendar"
      src="/chronos.html"
    />
  );
}

function Medications() {
  return (
    <iframe
      className="chronos-frame"
      title="Meds Tracker"
      src="http://127.0.0.1:9255/?v=list"
    />
  );
}

function Reminders() {
  const ask = useConfirm();
  const [items, setItems] = useState<{ id: number; title: string; due_at: string; recurrence: string; acknowledged: number }[]>([]);
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");
  const [recurrence, setRecurrence] = useState("none");
  const [zone, setZone] = useState("");
  const load = () => api<{ items: typeof items; timezone: string }>("/api/reminders").then((body) => {
    setItems(body.items);
    setZone(body.timezone);
  });
  useEffect(() => { load().catch(() => undefined); }, []);
  useEffect(() => {
    const onSpeech = (event: Event) => setTitle((event as CustomEvent<string>).detail);
    window.addEventListener("assistant-speech", onSpeech);
    return () => window.removeEventListener("assistant-speech", onSpeech);
  }, []);
  return (
    <section>
      <h2>Reminders</h2>
      <p className="muted">Schedule time zone: {zone}. Daily and weekly reminders move to the next time after you acknowledge them. Daylight-saving gaps move forward one hour.</p>
      {items.map((item) => (
        <article className="card" key={item.id}>
          <h3>{item.title}</h3>
          <p>{new Date(item.due_at).toLocaleString()} · {item.recurrence} · {item.acknowledged ? "done" : "open"}</p>
          <div className="row">
            <button
              type="button"
              onClick={() =>
                ask({
                  title: "Dismiss reminder?",
                  description: `Dismiss “${item.title}” due ${new Date(item.due_at).toLocaleString()}. Repeating reminders advance to the next time.`,
                  confirmLabel: "Dismiss",
                  onConfirm: () =>
                    api(`/api/reminders/${item.id}/acknowledge`, { method: "POST", body: confirmedPayload() }).then(load),
                })
              }
            >
              Dismiss
            </button>
            <FluidButton
              type="button"
              onClick={() => api(`/api/reminders/${item.id}/push`, { method: "POST" }).catch((err: Error) => window.alert(err.message))}
            >
              Push to phone
            </FluidButton>
            <button
              type="button"
              onClick={() =>
                ask({
                  title: "Delete reminder?",
                  description: `Permanently delete “${item.title}” and its history.`,
                  confirmLabel: "Delete",
                  onConfirm: () =>
                    api(`/api/reminders/${item.id}`, { method: "DELETE", body: confirmedPayload() }).then(load),
                })
              }
            >
              Delete
            </button>
          </div>
        </article>
      ))}
      <form onSubmit={async (event) => {
        event.preventDefault();
        const due = new Date(when);
        await api("/api/reminders", { method: "POST", body: JSON.stringify({ title, due_at: due.toISOString(), recurrence, body: "" }) });
        setTitle("");
        await load();
      }}>
        <label><span>Title</span><input aria-label="Reminder title" value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
        <label><span>When</span><input aria-label="Reminder time" type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} required /></label>
        <label><span>Repeat</span>
          <select aria-label="Repeat" value={recurrence} onChange={(event) => setRecurrence(event.target.value)}>
            <option value="none">Once</option>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
          </select>
        </label>
        <FluidButton variant="primary" type="submit">Save reminder</FluidButton>
      </form>
    </section>
  );
}

function TextList({ kind }: { kind: "notes" | "memories" }) {
  const ask = useConfirm();
  const [items, setItems] = useState<{ id: number; title: string; body: string }[]>([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const path = kind === "notes" ? "/api/notes" : "/api/memories";
  const load = () => api<{ items: typeof items }>(path).then((result) => setItems(result.items));
  useEffect(() => { load().catch(() => undefined); }, [path]);
  return (
    <section>
      <h2>{kind === "notes" ? "Notes" : "Memory"}</h2>
      <p className="muted">{kind === "memories" ? "Memories are text you choose to keep. Chat can read them only after you save them." : "Notes are private to this computer."}</p>
      <button type="button" onClick={async () => {
        const data = await api<Record<string, unknown>>("/api/export");
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "assistant-export.json";
        link.click();
        URL.revokeObjectURL(url);
      }}>Export all records</button>
      {items.map((item) => (
        <article className="card" key={item.id}>
          {editing === item.id ? (
            <form onSubmit={async (event) => {
              event.preventDefault();
              await api(`${path}/${item.id}`, { method: "PUT", body: JSON.stringify({ title, body }) });
              setEditing(null);
              await load();
            }}>
              <label><span>Title</span><input aria-label="Edit title" value={title} onChange={(event) => setTitle(event.target.value)} /></label>
              <label><span>Text</span><textarea aria-label="Edit text" value={body} onChange={(event) => setBody(event.target.value)} /></label>
              <button className="primary" type="submit">Save changes</button>
            </form>
          ) : (
            <>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
              <button type="button" onClick={() => { setEditing(item.id); setTitle(item.title); setBody(item.body); }}>Edit</button>
              <button
                type="button"
                onClick={() =>
                  ask({
                    title: `Delete ${kind === "notes" ? "note" : "memory"}?`,
                    description: `Permanently delete “${item.title}”.`,
                    confirmLabel: "Delete",
                    onConfirm: () => api(`${path}/${item.id}`, { method: "DELETE", body: confirmedPayload() }).then(load),
                  })
                }
              >
                Delete
              </button>
            </>
          )}
        </article>
      ))}
      <form onSubmit={async (event) => {
        event.preventDefault();
        await api(path, { method: "POST", body: JSON.stringify({ title, body }) });
        setTitle(""); setBody("");
        await load();
      }}>
        <label><span>Title</span><input aria-label="Title" value={editing ? "" : title} onChange={(event) => setTitle(event.target.value)} required={editing === null} /></label>
        <label><span>Text</span><textarea aria-label="Text" value={editing ? "" : body} onChange={(event) => setBody(event.target.value)} /></label>
        <button className="primary" type="submit">Add</button>
      </form>
    </section>
  );
}

function Notes() { return <TextList kind="notes" />; }
type FastenStatus = {
  reachable: boolean;
  url: string;
  detail: string;
};

function Memory() {
  const [status, setStatus] = useState<FastenStatus | null>(null);
  const [error, setError] = useState("");
  const load = () => api<FastenStatus>("/api/fasten/status").then(setStatus).catch((err: Error) => setError(err.message));
  useEffect(() => { load(); }, []);
  if (status?.reachable) {
    return (
      <section className="fasten-shell">
        <div className="row">
          <h2>Fasten Health</h2>
          <a href={status.url} target="_blank" rel="noreferrer">Open in a new tab</a>
        </div>
        <p className="muted">
          On-prem personal health record from this computer. The first screen asks you to create an encryption key that stays on this machine.
        </p>
        <iframe className="fasten-frame" title="Fasten Health on-prem" src={status.url} />
      </section>
    );
  }
  return (
    <section>
      <h2>Fasten Health</h2>
      <p className="muted">
        This section is the self-hosted Fasten Health on-prem personal health record. It keeps records on your machine. You enter information yourself or upload FHIR bundles you already exported. It does not sign in to clinics or insurers.
      </p>
      <p className="banner" role="status">{error || status?.detail || "Checking whether Fasten is running…"}</p>
      <article className="card">
        <h3>Start it on this computer</h3>
        <p>Docker is required. After it starts, this section embeds <code>http://127.0.0.1:9091</code>.</p>
        <pre className="card">{`bash assistant/scripts/fasten.sh start`}</pre>
        <p className="muted">To point at a Fasten you already run, set <code>FASTEN_URL</code> before starting the Assistant API.</p>
        <FluidButton type="button" variant="primary" onClick={() => { setError(""); load(); }}>Check again</FluidButton>
      </article>
    </section>
  );
}

function Chat() {
  const ask = useConfirm();
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState("");
  const [proposal, setProposal] = useState<{ id: number; summary: string; status: string } | null>(null);
  return (
    <section>
      <h2>Quick save</h2>
      <p className="muted">
        Staging only: note:, remember:, remind me:, project: (confirm before write). For open conversation use J.A.R.V.I.S.
        Medical questions are refused. Other tabs' commands work here when you name them.
      </p>
      <form onSubmit={async (event) => {
        event.preventDefault();
        const result = await api<JarvisTurn>("/api/assistant/message", { method: "POST", body: JSON.stringify({ message, tab: "records" }) });
        setReply(result.reply);
        setProposal(result.proposal);
        if (!result.action) return;
        const perform = () => performJarvisAction(result.action!).then(setReply).catch((err: Error) => setReply(err.message));
        if (result.action.confirm) {
          ask({ title: "Confirm", description: result.action.summary, confirmLabel: "Confirm", onConfirm: perform });
        } else {
          await perform();
        }
      }}>
        <label><span>Message</span><textarea aria-label="Message" value={message} onChange={(event) => setMessage(event.target.value)} required /></label>
        <button className="primary" type="submit">Send</button>
      </form>
      {reply && <p role="status">{reply}</p>}
      {proposal && (
        <div className="banner">
          <p>Waiting for approval: {proposal.summary}</p>
          <button type="button" className="primary" onClick={() => api(`/api/assistant/proposals/${proposal.id}/confirm`, { method: "POST" }).then(() => setProposal(null))}>Confirm</button>
          <button type="button" onClick={() => api(`/api/assistant/proposals/${proposal.id}/reject`, { method: "POST" }).then(() => setProposal(null))}>Decline</button>
        </div>
      )}
    </section>
  );
}

function LanSettingsPanel() {
  const ask = useConfirm();
  const [lan, setLan] = useState<{
    enabled: boolean;
    urls: string[];
    pairing_code: string;
    pairing_expires: string;
    sessions: { id: number; device_label: string }[];
    notice: string;
  } | null>(null);
  const [message, setMessage] = useState("");
  const load = () => api<NonNullable<typeof lan>>("/api/lan/status").then(setLan).catch((err: Error) => setMessage(err.message));
  useEffect(() => { void load(); }, []);
  if (!lan) return <p className="muted">Loading LAN settings…</p>;
  return (
    <fieldset>
      <legend>Phone on your Wi‑Fi (LAN)</legend>
      <p className="muted">{lan.notice}</p>
      <p>{lan.enabled ? "LAN access is enabled." : "LAN access is off. Only this computer can use the app."}</p>
      {lan.enabled && (
        <>
          {lan.urls.length === 0 && <p className="banner">No LAN address found. Check your network connection.</p>}
          <ul>
            {lan.urls.map((url) => (
              <li key={url}><code>{url}</code></li>
            ))}
          </ul>
          {lan.pairing_code && (
            <p>
              Pairing code: <strong aria-label="LAN pairing code">{lan.pairing_code}</strong>
              {lan.pairing_expires && <span className="muted"> (expires {new Date(lan.pairing_expires).toLocaleString()})</span>}
            </p>
          )}
          <h3>Paired devices</h3>
          {lan.sessions.length === 0 && <p className="muted">No paired phones yet.</p>}
          {lan.sessions.map((session) => (
            <div className="row" key={session.id}>
              <span>{session.device_label}</span>
              <button
                type="button"
                onClick={() =>
                  ask({
                    title: "Revoke phone access?",
                    description: `Remove LAN access for “${session.device_label}”.`,
                    confirmLabel: "Revoke",
                    onConfirm: () =>
                      api(`/api/lan/sessions/${session.id}`, { method: "DELETE", body: confirmedPayload() }).then(load),
                  })
                }
              >
                Revoke
              </button>
            </div>
          ))}
        </>
      )}
      <div className="row">
        {!lan.enabled && (
          <FluidButton type="button" variant="primary" onClick={() => api("/api/lan/enable", { method: "POST" }).then(load).then(() => setMessage("LAN enabled. Restart assistant/start.sh to listen on your network."))}>
            Enable LAN access
          </FluidButton>
        )}
        {lan.enabled && (
          <button
            type="button"
            onClick={() =>
              ask({
                title: "Disable LAN access?",
                description: "Phones on your network will lose access until you enable LAN again and pair.",
                confirmLabel: "Disable",
                onConfirm: () => api("/api/lan/disable", { method: "POST" }).then(load),
              })
            }
          >
            Disable LAN access
          </button>
        )}
      </div>
      {message && <p role="status">{message}</p>}
    </fieldset>
  );
}

function SettingsForm({ initial, onSaved }: { initial: Settings; onSaved: (value: Settings) => void }) {
  const ask = useConfirm();
  const [form, setForm] = useState(initial);
  const [status, setStatus] = useState<string>("");
  const [message, setMessage] = useState("");
  const [google, setGoogle] = useState<GoogleStatus | null>(null);
  const [devices, setDevices] = useState<GsDevice[]>([]);
  useEffect(() => {
    api<GoogleStatus>("/api/google/status").then(setGoogle).catch(() => undefined);
    api<{ items: GsDevice[] }>("/api/gsconnect/devices").then((body) => setDevices(body.items)).catch(() => undefined);
  }, []);
  async function check() {
    const body = await api<{ providers: { id: string; state: string; detail: string; chat: boolean }[]; sent_when_enabled: string }>("/api/providers/status");
    setStatus(body.providers.map((item) => `${item.id}: ${item.state}. ${item.detail}`).join(" "));
  }
  async function linkGoogle() {
    const body = await api<{ url: string }>("/api/google/auth/url");
    window.location.href = body.url;
  }
  return (
    <section>
      <h2>Settings</h2>
      <form onSubmit={async (event) => {
        event.preventDefault();
        await api("/api/settings", { method: "PUT", body: JSON.stringify(form) });
        onSaved(form);
        setMessage("Saved.");
      }}>
        <fieldset>
          <legend>AI provider</legend>
          <label><input type="radio" name="provider" checked={form.provider === "off"} onChange={() => setForm({ ...form, provider: "off" })} /> Off. No message leaves this app.</label>
          <label><input type="radio" name="provider" checked={form.provider === "lmstudio"} onChange={() => setForm({ ...form, provider: "lmstudio" })} /> LM Studio, local OpenAI-compatible API</label>
          <label>
            <input type="radio" name="provider" checked={form.provider === "als"} onChange={() => setForm({ ...form, provider: "als" })} />
            ALS Chat (Loop Studio on this machine)
          </label>
        </fieldset>
        <label><span>LM Studio URL</span><input aria-label="LM Studio URL" value={form.lmstudio_url} onChange={(event) => setForm({ ...form, lmstudio_url: event.target.value })} /></label>
        <label><span>LM Studio model id</span><input aria-label="LM Studio model" value={form.lmstudio_model} onChange={(event) => setForm({ ...form, lmstudio_model: event.target.value })} /></label>
        <label><span>ALS URL</span><input aria-label="ALS URL" value={form.als_url} onChange={(event) => setForm({ ...form, als_url: event.target.value })} /></label>
        <label>
          <span>ALS access token</span>
          <input
            aria-label="ALS access token"
            type="password"
            autoComplete="off"
            value={form.als_api_token}
            onChange={(event) => setForm({ ...form, als_api_token: event.target.value })}
          />
        </label>
        <p className="muted">Copy the token from ALS → Config → Access token (header <code>X-Router-Token</code>).</p>
        <label>
          <input type="checkbox" checked={form.consent} onChange={(event) => setForm({ ...form, consent: event.target.checked })} />
          I agree to send only the current Quick save message to the selected provider (LM Studio or ALS).
        </label>
        <label><span>Time zone</span><input aria-label="Time zone" value={form.timezone} onChange={(event) => setForm({ ...form, timezone: event.target.value })} /></label>
        <label><span>Text size</span>
          <select aria-label="Text size" value={form.text_scale} onChange={(event) => setForm({ ...form, text_scale: event.target.value })}>
            <option value="100">100%</option>
            <option value="125">125%</option>
            <option value="150">150%</option>
          </select>
        </label>
        <label><span>Contrast</span>
          <select aria-label="Contrast" value={form.contrast} onChange={(event) => setForm({ ...form, contrast: event.target.value })}>
            <option value="default">Default</option>
            <option value="high">High contrast</option>
          </select>
        </label>
        <label><input type="checkbox" checked={form.reduced_motion} onChange={(event) => setForm({ ...form, reduced_motion: event.target.checked })} /> Reduce motion</label>
        <fieldset>
          <legend>Phone alerts (GSConnect)</legend>
          <p className="muted">Uses GNOME Shell GSConnect to mirror notify-send to a paired Android phone while this page is open.</p>
          <label>
            <input type="checkbox" checked={form.gsconnect_push} onChange={(event) => setForm({ ...form, gsconnect_push: event.target.checked })} />
            Push due reminders to phone
          </label>
          <label>
            <span>Device (optional)</span>
            <select
              aria-label="GSConnect device"
              value={form.gsconnect_device}
              onChange={(event) => setForm({ ...form, gsconnect_device: event.target.value })}
            >
              <option value="">First connected device</option>
              {devices.map((device) => (
                <option key={device.path} value={device.path}>
                  {device.name}{device.connected ? " · connected" : " · offline"}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
        <LanSettingsPanel />
        <fieldset>
          <legend>Google Calendar (read-only)</legend>
          <p className="muted">
            Create an OAuth client in Google Cloud with redirect URI{" "}
            <code>{google?.redirect_uri || "http://127.0.0.1:9242/api/google/callback"}</code>.
          </p>
          <label><span>OAuth client ID</span><input aria-label="Google client ID" value={form.google_client_id} onChange={(event) => setForm({ ...form, google_client_id: event.target.value })} /></label>
          <label><span>OAuth client secret</span><input aria-label="Google client secret" type="password" autoComplete="off" value={form.google_client_secret} onChange={(event) => setForm({ ...form, google_client_secret: event.target.value })} /></label>
          <p className="muted">{google?.linked ? "Google Calendar is linked." : "Not linked yet. Save client ID and secret, then connect."}</p>
          <div className="row">
            <FluidButton type="button" variant="primary" onClick={() => linkGoogle().catch((err: Error) => setMessage(err.message))}>
              Connect Google Calendar
            </FluidButton>
            <FluidButton type="button" disabled={!google?.linked} onClick={() => api("/api/google/sync", { method: "POST" }).then(() => setMessage("Calendar synced.")).catch((err: Error) => setMessage(err.message))}>
              Sync now
            </FluidButton>
          </div>
        </fieldset>
        <div className="row">
          <FluidButton variant="primary" type="submit">Save settings</FluidButton>
          <button type="button" onClick={() => check().catch((err: Error) => setMessage(err.message))}>Check connections</button>
          <button
            type="button"
            onClick={() =>
              ask({
                title: "Delete all records?",
                description: "Permanently remove appointments, medications, reminders, notes, memories, and projects from this assistant.",
                confirmLabel: "Delete everything",
                onConfirm: () => api("/api/data", { method: "DELETE", body: confirmedPayload() }),
              })
            }
          >
            Delete all records
          </button>
        </div>
        {message && <p role="status">{message}</p>}
        {status && <p>{status}</p>}
      </form>
      <Repair />
    </section>
  );
}

function Repair() {
  const [explanation, setExplanation] = useState("");
  const [diff, setDiff] = useState("");
  const [id, setId] = useState<number | null>(null);
  const [result, setResult] = useState("");
  return (
    <form onSubmit={async (event) => {
      event.preventDefault();
      const body = await api<{ id: number; diff: string }>("/api/repair/proposals", { method: "POST", body: JSON.stringify({ explanation }) });
      setId(body.id);
      setDiff(body.diff);
    }}>
      <h3>Repair proposal</h3>
      <p className="muted">This prepares a diff and, if you approve, saves that file. It does not change the running program or run shell commands.</p>
      <label><span>What looks wrong</span><textarea aria-label="Repair explanation" value={explanation} onChange={(event) => setExplanation(event.target.value)} /></label>
      <button type="submit">Prepare diff</button>
      {diff && <pre>{diff}</pre>}
      {id && <button type="button" onClick={async () => {
        const body = await api<{ applied: boolean; path: string }>(`/api/repair/proposals/${id}/approve`, { method: "POST" });
        setResult(body.applied ? "Applied" : `Saved only. Program unchanged. ${body.path}`);
      }}>Approve and save the diff</button>}
      {result && <p role="status">{result}</p>}
    </form>
  );
}
