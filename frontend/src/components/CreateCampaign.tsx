import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, ApiError, describeError, query } from "../api";
import type {
  CampaignCreateResult, Country, Defaults, DomainItem, Notify,
  OfferItem, ReferenceItem,
} from "../types";

type Props = { notify: Notify };

const MAX_CREATE_OFFERS = 20;

export default function CreateCampaign({ notify }: Props) {
  const [countries, setCountries] = useState<Country[]>([]);
  const [domains, setDomains] = useState<DomainItem[]>([]);
  const [groups, setGroups] = useState<ReferenceItem[]>([]);
  const [sources, setSources] = useState<ReferenceItem[]>([]);
  const [geoSearch, setGeoSearch] = useState("");
  const [offerSearch, setOfferSearch] = useState("");
  const [offers, setOffers] = useState<OfferItem[]>([]);
  const [offersReloadNonce, setOffersReloadNonce] = useState(0);
  const [offersLoading, setOffersLoading] = useState(false);
  const [offersOpen, setOffersOpen] = useState(false);
  const [offerActive, setOfferActive] = useState(-1);
  const offerPickerRef = useRef<HTMLDivElement>(null);
  const [selectedOffers, setSelectedOffers] = useState<OfferItem[]>([]);
  const [newGroup, setNewGroup] = useState("");
  const [form, setForm] = useState({
    name: "",
    geo: [] as string[],
    offerIds: [] as number[],
    domainId: 0,
    groupId: 0,
    sourceId: 0,
  });
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

  // Список офферов показываем сразу при фокусе/пустом поиске: backend кэширует ответ.
  useEffect(() => {
    const term = offerSearch.trim();
    let cancelled = false;
    const controller = new AbortController();
    setOffersLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const rows = await api<OfferItem[]>(
          `/api/keitaro/offers${query({ search: term, limit: MAX_CREATE_OFFERS })}`,
          { signal: controller.signal },
        );
        if (!cancelled) setOffers(rows);
      } catch (error) {
        if (!cancelled && !(error instanceof ApiError && error.code === "NETWORK" && controller.signal.aborted)) {
          notify("error", `Офферы недоступны: ${describeError(error)}`);
        }
      } finally {
        if (!cancelled) setOffersLoading(false);
      }
    }, 150);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [offerSearch, offersReloadNonce, notify]);

  useEffect(() => {
    function closeOnOutside(event: MouseEvent) {
      if (offerPickerRef.current && !offerPickerRef.current.contains(event.target as Node)) setOffersOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutside);
    return () => document.removeEventListener("mousedown", closeOnOutside);
  }, []);

  const geoQuery = geoSearch.trim().toLowerCase();
  const filteredCountries = countries.filter((country) =>
    !geoQuery || country.code.toLowerCase().includes(geoQuery) || country.name.toLowerCase().includes(geoQuery));
  // Порядок списка стабилен: выбранные страны остаются в нём на своих местах,
  // а их полный перечень показан в чипсах под полем поиска.
  const visibleCountries = filteredCountries.slice(0, 12);

  const selectedOfferIds = new Set(form.offerIds);
  const availableOffers = offers.filter((offer) => !selectedOfferIds.has(offer.id));
  const offerLimitReached = form.offerIds.length >= MAX_CREATE_OFFERS;
  const visibleOffers = offerLimitReached ? [] : availableOffers;
  const formDisabled = busy !== null;

  function toggleGeo(code: string) {
    setForm((current) => ({
      ...current,
      geo: current.geo.includes(code)
        ? current.geo.filter((item) => item !== code)
        : [...current.geo, code],
    }));
  }

  function addSelectedOffer(offer: OfferItem) {
    if (offerLimitReached || selectedOfferIds.has(offer.id)) return;
    setSelectedOffers((current) =>
      current.some((item) => item.id === offer.id) ? current : [...current, offer],
    );
    setForm((current) => ({
      ...current,
      offerIds: current.offerIds.includes(offer.id) ? current.offerIds : [...current.offerIds, offer.id],
    }));
    setOfferSearch("");
    setOffersOpen(false);
    setOfferActive(-1);
    setOffersReloadNonce((value) => value + 1);
  }

  function removeSelectedOffer(offerId: number) {
    setSelectedOffers((current) => current.filter((item) => item.id !== offerId));
    setForm((current) => ({
      ...current,
      offerIds: current.offerIds.filter((id) => id !== offerId),
    }));
  }

  function offerKeys(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOffersOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!visibleOffers.length) return;
      event.preventDefault();
      setOffersOpen(true);
      setOfferActive((current) => event.key === "ArrowDown"
        ? Math.min(current + 1, visibleOffers.length - 1)
        : Math.max(current - 1, 0));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const selected = visibleOffers[offerActive]
        ?? (visibleOffers.length === 1 ? visibleOffers[0] : undefined);
      if (selected) addSelectedOffer(selected);
    }
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
    if (busy) return; // защита от двойного клика
    if (!form.name.trim() || !form.geo.length || !form.offerIds.length || !form.domainId || !form.groupId || !form.sourceId) {
      notify("error", "Заполните поля Name, GEO, Offers, Domain, Group и Source.");
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
          offer_ids: form.offerIds,
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
        <p className="muted">Кампания и два потока создаются в Keitaro через backend.</p>
        <form onSubmit={submit}>
          <label className="field">
            <span>Name *</span>
            <input
              value={form.name}
              maxLength={255}
              disabled={formDisabled}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Название кампании"
            />
          </label>

          <div className="field">
            <span>GEO * (поиск по коду или названию)</span>
            <input
              aria-label="Поиск GEO по коду или названию"
              value={geoSearch}
              disabled={formDisabled}
              onChange={(event) => setGeoSearch(event.target.value)}
              placeholder="Например: AU или Australia"
            />
            {!!form.geo.length && (
              <div className="chips">
                {form.geo.map((code) => (
                  <button
                    key={code}
                    type="button"
                    className="chip"
                    disabled={formDisabled}
                    title={`Убрать ${code}`}
                    aria-label={`Убрать GEO ${code}`}
                    onClick={() => toggleGeo(code)}
                  >
                    {code} ×
                  </button>
                ))}
              </div>
            )}
            <div className="geo-list">
              {visibleCountries.map((country) => (
                <label key={country.code} className="check-line">
                  <input
                    type="checkbox"
                    checked={form.geo.includes(country.code)}
                    disabled={formDisabled}
                    onChange={() => toggleGeo(country.code)}
                  />
                  {country.code} — {country.name}
                </label>
              ))}
              {!filteredCountries.length && <span className="muted">Страны не найдены</span>}
            </div>
            <p className="muted geo-hint">
              Показано {visibleCountries.length} из {filteredCountries.length}.
              {visibleCountries.length < filteredCountries.length && " Уточните поиск, чтобы увидеть остальные страны."}
            </p>
          </div>

          <div className="field">
            <span>Offers * (можно выбрать несколько, до {MAX_CREATE_OFFERS})</span>
            <div className="picker" ref={offerPickerRef}>
              <input
                role="combobox"
                aria-label="Поиск оффера для добавления"
                aria-expanded={offersOpen}
                aria-controls="create-offer-options"
                aria-autocomplete="list"
                aria-activedescendant={offersOpen && offerActive >= 0 ? `create-offer-option-${offerActive}` : undefined}
                value={offerSearch}
                disabled={formDisabled || offerLimitReached}
                onChange={(event) => {
                  setOfferSearch(event.target.value);
                  setOfferActive(-1);
                  setOffersOpen(true);
                }}
                onFocus={() => { if (!offerLimitReached) { setOffersOpen(true); setOfferActive(-1); } }}
                onKeyDown={offerKeys}
                placeholder="Название или ID оффера"
              />
              {offersOpen && !offerLimitReached && (
                <div className="picker-menu" id="create-offer-options" role="listbox">
                  {offersLoading && !offers.length && <div className="picker-empty">Загрузка каталога…</div>}
                  {visibleOffers.map((offer, index) => (
                    <div
                      key={offer.id}
                      id={`create-offer-option-${index}`}
                      role="option"
                      aria-selected={index === offerActive}
                      tabIndex={-1}
                      className={`picker-option ${index === offerActive ? "active" : ""}`}
                      onMouseEnter={() => setOfferActive(index)}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => addSelectedOffer(offer)}
                    >
                      <span>#{offer.id} — {offer.name}</span>
                    </div>
                  ))}
                  {!offersLoading && !offers.length && <div className="picker-empty">Ничего не найдено</div>}
                  {!offersLoading && offers.length > 0 && !visibleOffers.length && (
                    <div className="picker-empty">Все найденные офферы уже выбраны</div>
                  )}
                </div>
              )}
            </div>
            {!!selectedOffers.length && (
              <div className="chips">
                {selectedOffers.map((offer) => (
                  <button
                    key={offer.id}
                    type="button"
                    className="chip"
                    disabled={formDisabled}
                    title="Убрать оффер"
                    aria-label={`Убрать оффер ${offer.id}`}
                    onClick={() => removeSelectedOffer(offer.id)}
                  >
                    #{offer.id} — {offer.name} ×
                  </button>
                ))}
              </div>
            )}
            {offerLimitReached && (
              <p className="muted offer-hint">Достигнут лимит в {MAX_CREATE_OFFERS} офферов.</p>
            )}
          </div>

          <label className="field">
            <span>Domain *</span>
            <select
              value={form.domainId || ""}
              disabled={formDisabled}
              onChange={(event) => setForm({ ...form, domainId: Number(event.target.value) })}
            >
              <option value="">— выберите —</option>
              {domains.map((item) => <option key={item.id} value={item.id}>{item.name} (#{item.id})</option>)}
            </select>
          </label>

          <div className="field">
            <span>Group *</span>
            <select
              value={form.groupId || ""}
              disabled={formDisabled}
              onChange={(event) => setForm({ ...form, groupId: Number(event.target.value) })}
            >
              <option value="">— выберите —</option>
              {groups.map((item) => <option key={item.id} value={item.id}>{item.name} (#{item.id})</option>)}
            </select>
            <div className="inline">
              <input
                value={newGroup}
                disabled={formDisabled}
                onChange={(event) => setNewGroup(event.target.value)}
                placeholder="Новая группа"
              />
              <button type="button" disabled={formDisabled || !newGroup.trim()} onClick={createGroup}>
                {busy === "group" ? "Создание…" : "Создать группу"}
              </button>
            </div>
          </div>

          <label className="field">
            <span>Source *</span>
            <select
              value={form.sourceId || ""}
              disabled={formDisabled}
              onChange={(event) => setForm({ ...form, sourceId: Number(event.target.value) })}
            >
              <option value="">— выберите —</option>
              {sources.map((item) => <option key={item.id} value={item.id}>{item.name} (#{item.id})</option>)}
            </select>
          </label>

          <button type="submit" className="primary" disabled={formDisabled}>
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
            <p>Offers: {result.offers.map((offer) => `#${offer.id} — ${offer.name}`).join("; ")}</p>
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
