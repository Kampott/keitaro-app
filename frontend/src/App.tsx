import { useCallback, useEffect, useState, type FormEvent } from "react";
import { registerUnauthorized, setBasicAuth } from "./api";
import CreateCampaign from "./components/CreateCampaign";
import EditCampaign from "./components/EditCampaign";
import type { Notify } from "./types";

type Toast = { id: number; kind: "success" | "error" | "info"; text: string };

function LoginForm({
  username,
  onUsernameChange,
  onDone,
}: {
  username: string;
  onUsernameChange: (value: string) => void;
  onDone: () => void;
}) {
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
      <form
        className="modal card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="login-title"
        onSubmit={submit}
      >
        <h2 id="login-title">Доступ к Adrobot</h2>
        <p className="muted">
          Введите логин и пароль из <code>.env</code> (<code>APP_BASIC_AUTH_USER</code> /
          <code>APP_BASIC_AUTH_PASSWORD</code>). Значения хранятся только в памяти страницы.
        </p>
        <label className="field">
          <span>Логин</span>
          <input value={username} autoComplete="username" onChange={(e) => onUsernameChange(e.target.value)} />
        </label>
        <label className="field">
          <span>Пароль</span>
          <input type="password" value={password} autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" className="primary">Войти</button>
      </form>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<"create" | "edit">("create");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [loginUsername, setLoginUsername] = useState("");
  const [appKey, setAppKey] = useState(0);

  const notify = useCallback<Notify>((kind, text) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, kind, text }]);
    window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 6000);
  }, []);

  useEffect(() => {
    registerUnauthorized(() => setNeedsAuth(true));
  }, []);

  function loginDone() {
    setNeedsAuth(false);
    setAppKey((key) => key + 1); // перемонтируем формы, чтобы повторить загрузку данных
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

      <div className="toasts">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.kind}`} role="status" aria-live="polite">
            <span>
              {toast.kind === "success" ? "✓" : toast.kind === "error" ? "✗" : "i"} {toast.text}
            </span>
            <button
              type="button"
              aria-label="Закрыть уведомление"
              onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {needsAuth && (
        <LoginForm
          username={loginUsername}
          onUsernameChange={setLoginUsername}
          onDone={loginDone}
        />
      )}
    </main>
  );
}
