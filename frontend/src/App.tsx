import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, describeError, registerUnauthorized, setBasicAuth } from "./api";
import CreateCampaign from "./components/CreateCampaign";
import EditCampaign from "./components/EditCampaign";
import type { Notify } from "./types";

type Check = { label: string; state: "loading" | "ok" | "error"; text: string };
type Toast = { id: number; kind: "success" | "error" | "info"; text: string };

async function check(label: string, url: string, okText: (body: any) => string): Promise<Check> {
  try {
    const body = await api<any>(url);
    return { label, state: "ok", text: okText(body) };
  } catch (error) {
    return { label, state: "error", text: describeError(error) };
  }
}

function LoginForm({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!username || !password) return;
    setBasicAuth(username, password);
    setPassword("");
    onDone();
  }

  return (
    <div className="modal-backdrop">
      <form className="modal card" onSubmit={submit}>
        <h2>Доступ к Adrobot</h2>
        <p className="muted">
          Введите логин и пароль из <code>.env</code> (<code>APP_BASIC_AUTH_USER</code> /
          <code> APP_BASIC_AUTH_PASSWORD</code>). Значения хранятся только в памяти страницы.
        </p>
        <label className="field"><span>Логин</span><input value={username} onChange={(e) => setUsername(e.target.value)} /></label>
        <label className="field"><span>Пароль</span><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <button type="submit" className="primary">Войти</button>
      </form>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<"create" | "edit">("create");
  const [checks, setChecks] = useState<Check[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [appKey, setAppKey] = useState(0);

  const notify = useCallback<Notify>((kind, text) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, kind, text }]);
    window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 6000);
  }, []);

  const runChecks = useCallback(() => {
    setChecks([
      { label: "Backend + БД", state: "loading", text: "" },
      { label: "Keitaro", state: "loading", text: "" },
    ]);
    (async () => {
      const health = await check("Backend + БД", "/healthz", (body) =>
        body.db ? "ok" : "backend жив, БД недоступна");
      setChecks([health, { label: "Keitaro", state: "loading", text: "" }]);
      const ping = await check("Keitaro", "/api/keitaro/ping", (body) =>
        `ключ принят, кампаний в выборке: ${body.campaigns_returned}`);
      setChecks([health, ping]);
    })();
  }, []);

  useEffect(() => {
    registerUnauthorized(() => setNeedsAuth(true));
    runChecks();
  }, [runChecks]);

  function loginDone() {
    setNeedsAuth(false);
    setAppKey((key) => key + 1); // перемонтируем формы, чтобы повторить загрузку данных
    runChecks();
  }

  return (
    <main>
      <h1>Adrobot</h1>
      <nav>
        <button className={tab === "create" ? "active" : ""} onClick={() => setTab("create")}>
          Create Campaign
        </button>
        <button className={tab === "edit" ? "active" : ""} onClick={() => setTab("edit")}>
          Edit Campaign
        </button>
      </nav>

      {tab === "create"
        ? <CreateCampaign key={`create-${appKey}`} notify={notify} />
        : <EditCampaign key={`edit-${appKey}`} notify={notify} />}

      <section className="card">
        <b>Статус</b>
        {checks.map((item) => (
          <p key={item.label} className={item.state === "ok" ? "ok" : item.state === "error" ? "err" : "muted"}>
            {item.state === "ok" ? "✓" : item.state === "error" ? "✗" : "…"} {item.label}: {item.text}
          </p>
        ))}
      </section>

      <div className="toasts">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.kind}`} onClick={() =>
            setToasts((current) => current.filter((item) => item.id !== toast.id))}>
            {toast.kind === "success" ? "✓" : toast.kind === "error" ? "✗" : "i"} {toast.text}
          </div>
        ))}
      </div>

      {needsAuth && <LoginForm onDone={loginDone} />}
    </main>
  );
}
