import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, describeError, query } from "../api";
import type {
  CampaignCreateResult, Country, Defaults, DomainItem, Notify,
  OfferItem, ReferenceItem,
} from "../types";

type Props = { notify: Notify };

export default function CreateCampaign({ notify }: Props) {
  const [countries, setCountries] = useState<Country[]>([]);
  const [domains, setDomains] = useState<DomainItem[]>([]);
  const [groups, setGroups] = useState<ReferenceItem[]>([]);
  const [sources, setSources] = useState<ReferenceItem[]>([]);
  const [geoSearch, setGeoSearch] = useState("");
  const [offerSearch, setOfferSearch] = useState("");
  const [offers, setOffers] = useState<OfferItem[]>([]);
  const [newGroup, setNewGroup] = useState("");
  const [form, setForm] = useState({
    name: "",
    geo: [] as string[],
    offerId: 0,
    domainId: 0,
    groupId: 0,
    sourceId: 0,
  });
  const [selectedOffer, setSelectedOffer] = useState<OfferItem | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<CampaignCreateResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [geo, defaults, domainRows, groupRows, sourceRows] = await Promise.all([
          api<Country[]>("/api/geo"),
          api<Defaults>("/api/keitaro/defaults"),
          api<DomainItem[]>("/api/keitaro/domains"),
          api<ReferenceItem[]>("/api/keitaro/groups"),
          api<ReferenceItem[]>("/api/keitaro/sources"),
        ]);
        if (cancelled) return;
        setCountries(geo);
        setDomains(domainRows);
        setGroups(groupRows);
        setSources(sourceRows);
        setForm((current) => ({
          ...current,
          domainId: defaults.domain_id ?? domainRows[0]?.id ?? 0,
          groupId: defaults.group_id ?? groupRows[0]?.id ?? 0,
          sourceId: defaults.source_id ?? sourceRows[0]?.id ?? 0,
        }));
      } catch (error) {
        notify("error", `Не удалось загрузить справочники: ${describeError(error)}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [notify]);

  // Пустой/короткий запрос не дёргает Keitaro: список офферов большой.
  useEffect(() => {
    const term = offerSearch.trim();
    if (!/^\d+$/.test(term) && term.length < 2) {
      setOffers([]);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const rows = await api<OfferItem[]>(
          `/api/keitaro/offers${query({ search: term, limit: 20 })}`,
          { signal: controller.signal },
        );
        if (!cancelled) setOffers(rows);
      } catch (error) {
        if (!cancelled && !(error instanceof ApiError && error.code === "NETWORK" && controller.signal.aborted)) {
          notify("error", `Офферы недоступны: ${describeError(error)}`);
        }
      }
    }, 250);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [offerSearch, notify]);

  const geoQuery = geoSearch.trim().toLowerCase();
  const filteredCountries = countries.filter((country) =>
    !geoQuery || country.code.toLowerCase().includes(geoQuery) || country.name.toLowerCase().includes(geoQuery));
  // Не рендерим все 249 чекбоксов: сначала выбранные, затем первые 12 страны.
  // Поиск показывает до 20 совпадений — нужную страну всегда можно найти.
  const visibleCountries = geoQuery
    ? filteredCountries.slice(0, 20)
    : [
        ...filteredCountries.filter((country) => form.geo.includes(country.code)),
        ...filteredCountries.filter((country) => !form.geo.includes(country.code)).slice(0, 12),
      ];

  function toggleGeo(code: string) {
    setForm((current) => ({
      ...current,
      geo: current.geo.includes(code)
        ? current.geo.filter((item) => item !== code)
        : [...current.geo, code],
    }));
  }

  async function createGroup() {
    const name = newGroup.trim();
    if (!name || busy) return;
    setBusy("group");
    try {
      const created = await api<ReferenceItem>("/api/keitaro/groups", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      setGroups(await api<ReferenceItem[]>("/api/keitaro/groups"));
      setForm((current) => ({ ...current, groupId: created.id }));
      setNewGroup("");
      notify("success", `Группа «${created.name}» создана`);
    } catch (error) {
      notify("error", describeError(error));
    } finally {
      setBusy(null);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return; // защита от двойного клика (§3.5)
    if (!form.name.trim() || !form.geo.length || !form.offerId || !form.domainId || !form.groupId || !form.sourceId) {
      notify("error", "Заполните Name, GEO, Offer, Domain, Group и Source");
      return;
    }
    setBusy("create");
    setResult(null);
    try {
      const created = await api<CampaignCreateResult>("/api/campaigns", {
        method: "POST",
        body: JSON.stringify({
          name: form.name.trim(),
          geo: form.geo,
          offer_id: form.offerId,
          domain_id: form.domainId,
          group_id: form.groupId,
          source_id: form.sourceId,
        }),
      });
      setResult(created);
      notify("success", `Кампания ${created.keitaro_id} создана (alias ${created.alias})`);
      if (created.local_sync_failed) notify("error", created.warning ?? "Локальная копия не подготовлена");
    } catch (error) {
      notify("error", describeError(error));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid-two">
      <section className="card">
        <h2>Create Campaign</h2>
        <p className="muted">Форма §3.2 ТЗ. Кампания и два потока создаются в Keitaro через backend.</p>
        <form onSubmit={submit}>
          <label className="field">
            <span>Name *</span>
            <input
              value={form.name}
              maxLength={255}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Название кампании"
            />
          </label>

          <div className="field">
            <span>GEO * (поиск по коду или названию)</span>
            <input
              value={geoSearch}
              onChange={(event) => setGeoSearch(event.target.value)}
              placeholder="Например: AU или Australia"
            />
            <div className="geo-list">
              {visibleCountries.map((country) => (
                <label key={country.code} className="check-line">
                  <input
                    type="checkbox"
                    checked={form.geo.includes(country.code)}
                    onChange={() => toggleGeo(country.code)}
                  />
                  {country.code} — {country.name}
                </label>
              ))}
              {!filteredCountries.length && <span className="muted">Страны не найдены</span>}
            </div>
            <p className="muted geo-hint">
              Показано {visibleCountries.length} из {filteredCountries.length}.
              {!geoQuery && " Уточните поиск, чтобы выбрать другую страну."}
            </p>
            <div className="chips">
              {form.geo.map((code) => (
                <button key={code} type="button" className="chip" onClick={() => toggleGeo(code)}>
                  {code} ×
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <span>Offer * (autocomplete)</span>
            {selectedOffer && (
              <div className="selected">
               Выбрано: #{selectedOffer.id} — {selectedOffer.name}{" "}
               <button
                  type="button"
                  className="link"
                  onClick={() => {
                    setSelectedOffer(null);
                    setForm((current) => ({ ...current, offerId: 0 }));
                    setOfferSearch("");
                    setOffers([]);
                  }}
                >
                  сменить
                </button>
              </div>
            )}
            {!selectedOffer && (
              <>
                <input
                  value={offerSearch}
                  onChange={(event) => setOfferSearch(event.target.value)}
                  placeholder="Название или ID оффера"
                />
                <div className="suggestions">
                  {offers.map((offer) => (
                    <button
                      key={offer.id}
                      type="button"
                      onClick={() => {
                        setSelectedOffer(offer);
                        setForm((current) => ({ ...current, offerId: offer.id }));
                        setOfferSearch("");
                        setOffers([]);
                      }}
                    >
                      #{offer.id} — {offer.name}
                    </button>
                  ))}
                  {!offers.length && <span className="muted">Ничего не найдено</span>}
                </div>
              </>
            )}
          </div>

          <label className="field">
            <span>Domain *</span>
            <select value={form.domainId || ""} onChange={(event) => setForm({ ...form, domainId: Number(event.target.value) })}>
              <option value="">— выберите —</option>
              {domains.map((item) => <option key={item.id} value={item.id}>{item.name} (#{item.id})</option>)}
            </select>
          </label>

          <div className="field">
            <span>Group *</span>
            <select value={form.groupId || ""} onChange={(event) => setForm({ ...form, groupId: Number(event.target.value) })}>
              <option value="">— выберите —</option>
              {groups.map((item) => <option key={item.id} value={item.id}>{item.name} (#{item.id})</option>)}
            </select>
            <div className="inline">
              <input
                value={newGroup}
                onChange={(event) => setNewGroup(event.target.value)}
                placeholder="Новая группа"
              />
              <button type="button" disabled={busy !== null || !newGroup.trim()} onClick={createGroup}>
                {busy === "group" ? "Создание…" : "Создать группу"}
              </button>
            </div>
          </div>

          <label className="field">
            <span>Source *</span>
            <select value={form.sourceId || ""} onChange={(event) => setForm({ ...form, sourceId: Number(event.target.value) })}>
              <option value="">— выберите —</option>
              {sources.map((item) => <option key={item.id} value={item.id}>{item.name} (#{item.id})</option>)}
            </select>
          </label>

          <button type="submit" className="primary" disabled={busy !== null}>
            {busy === "create" ? "Создание…" : "Create Campaign"}
          </button>
        </form>
      </section>

      <section className="card">
        <h2>Результат создания</h2>
        {!result && <p className="muted">Заполните форму и нажмите Create Campaign.</p>}
        {result && (
          <div className="result">
            <p><b>{result.name}</b> · ID Keitaro: {result.keitaro_id} · alias: <code>{result.alias}</code></p>
            <p>
              Tracking URL:{" "}
              {result.tracking_url
                ? <a href={result.tracking_url} target="_blank" rel="noreferrer">{result.tracking_url}</a>
                : <span className="warn">не сформирован — проверьте domain и alias</span>}
            </p>
            <p>Domain: {result.domain.name} (#{result.domain.id})</p>
            <p>Group: {result.group.name} (#{result.group.id})</p>
            <p>Source: {result.source.name} (#{result.source.id})</p>
            <p>Offer: {result.offer.name} (#{result.offer.id})</p>
            <p>GEO: {result.geo.join(", ")}</p>
            <h3>Потоки</h3>
            <table>
              <thead><tr><th>ID</th><th>Name</th><th>Schema</th><th>Position</th></tr></thead>
              <tbody>
                {result.streams.map((stream) => (
                  <tr key={stream.id}>
                    <td>{stream.id}</td><td>{stream.name}</td>
                    <td><code>{stream.schema}</code></td><td>{stream.position}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {result.local_sync_failed && <p className="warn">{result.warning}</p>}
          </div>
        )}
      </section>
    </div>
  );
}
