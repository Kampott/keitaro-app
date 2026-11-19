import { useEffect, useState } from "react";

type Check = { label: string; state: "loading" | "ok" | "error"; text: string };

// Бэкенд отвечает {code, message} при ошибке (ТЗ §8); здесь только показываем это человеку.
async function check(label: string, url: string, okText: (b: any) => string): Promise<Check> {
  try {
    const r = await fetch(url);
    const body = await r.json().catch(() => null);
    if (r.ok) return { label, state: "ok", text: okText(body) };
    return { label, state: "error", text: body ? `${body.code}: ${body.message}` : `HTTP ${r.status}` };
  } catch {
    return { label, state: "error", text: "backend недоступен" };
  }
}

export default function App() {
  const [tab, setTab] = useState<"create" | "edit">("create");
  const [checks, setChecks] = useState<Check[]>([]);

  useEffect(() => {
    // последовательно: при включённом Basic auth браузер спросит логин один раз
    (async () => {
      const health = await check("Backend + БД", "/healthz", (b) => (b.db ? "ok" : "backend жив, БД недоступна"));
      setChecks([health]);
      const ping = await check("Keitaro", "/api/keitaro/ping", (b) => `ключ принят, кампаний в выборке: ${b.campaigns_returned}`);
      setChecks([health, ping]);
    })();
  }, []);

  return (
    <main>
      <h1>Adrobot</h1>
      <nav>
        <button className={tab === "create" ? "active" : ""} onClick={() => setTab("create")}>Create Campaign</button>
        <button className={tab === "edit" ? "active" : ""} onClick={() => setTab("edit")}>Edit Campaign</button>
      </nav>
      <div className="card">
        {tab === "create" ? "Create Campaign: форма будет здесь (ТЗ §3)" : "Edit Campaign: редактор офферов будет здесь (ТЗ §4)"}
      </div>
      <div className="card">
        <b>Статус</b>
        {checks.length === 0 && <p className="muted">проверяю…</p>}
        {checks.map((c) => (
          <p key={c.label} className={c.state === "ok" ? "ok" : "err"}>
            {c.state === "ok" ? "✓" : "✗"} {c.label}: {c.text}
          </p>
        ))}
      </div>
    </main>
  );
}
