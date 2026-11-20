import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, ApiError, describeError, query } from "../api";
import type {
  CampaignDetail, CampaignSummary, KeitaroCampaign, Notify, OfferDetail, OfferItem,
} from "../types";

type Props = { notify: Notify };
type OfferOption = { id: number; label: string; hint?: string };
type ConfirmRequest = {
  title: string;
  message: string;
  confirmLabel: string;
  tone?: "danger" | "primary";
};

const STATUS_TEXT: Record<string, string> = {
  synced: "Синхронизировано",
  modified: "Изменено локально",
  uploading: "Отправка",
  error: "Ошибка",
};

const BUSY_TEXT: Record<string, string> = {
  select: "Загрузка кампании",
  fetch: "Обновление из Keitaro",
  offer: "Сохранение оффера",
  upload: "Отправка в Keitaro",
};

function campaignOptionLabel(item: KeitaroCampaign): string {
  return `#${item.id} ${item.name} (${item.alias})${item.state ? ` · ${item.state}` : ""}`;
}

export default function EditCampaign({ notify }: Props) {
  const [remoteCampaigns, setRemoteCampaigns] = useState<KeitaroCampaign[]>([]);
  const [campaignLoading, setCampaignLoading] = useState(true);
  const [localCampaigns, setLocalCampaigns] = useState<CampaignSummary[]>([]);
  const [campaignQuery, setCampaignQuery] = useState("");
  const [campaignOpen, setCampaignOpen] = useState(false);
  const [campaignActive, setCampaignActive] = useState(-1);
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [flowId, setFlowId] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const busyRef = useRef(false);
  const campaignPickerRef = useRef<HTMLDivElement>(null);
  const [offerSearch, setOfferSearch] = useState("");
  const [offerResults, setOfferResults] = useState<OfferItem[]>([]);
  const [offerReloadNonce, setOfferReloadNonce] = useState(0);
  const [offersLoading, setOffersLoading] = useState(false);
  const [offersOpen, setOffersOpen] = useState(false);
  const [offerActive, setOfferActive] = useState(-1);
  const offerPickerRef = useRef<HTMLDivElement>(null);
  const [draftShares, setDraftShares] = useState<Record<number, string>>({});
  const [forceUpload, setForceUpload] = useState(false);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const confirmResolver = useRef<((ok: boolean) => void) | null>(null);

  function askConfirm(request: ConfirmRequest): Promise<boolean> {
    return new Promise((resolve) => {
      confirmResolver.current = resolve;
      setConfirmRequest(request);
    });
  }

  function closeConfirm(ok: boolean) {
    const resolve = confirmResolver.current;
    confirmResolver.current = null;
    setConfirmRequest(null);
    resolve?.(ok);
  }

  function begin(label: string): boolean {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(label);
    return true;
  }

  function end(): void {
    busyRef.current = false;
    setBusy(null);
  }

  const refreshLocal = useCallback(async () => {
    try {
      setLocalCampaigns(await api<CampaignSummary[]>("/api/campaigns"));
    } catch (error) {
      notify("error", `Список локальных кампаний недоступен: ${describeError(error)}`);
    }
  }, [notify]);

  useEffect(() => {
    void refreshLocal();
  }, [refreshLocal]);

  // Список нужен один раз: поиск ниже фильтрует его локально, без вызовов Keitaro.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setCampaignLoading(true);
      try {
        const rows = await api<KeitaroCampaign[]>(`/api/keitaro/campaigns${query({ limit: 200 })}`);
        if (!cancelled) setRemoteCampaigns(rows);
      } catch (error) {
        if (!cancelled) notify("error", `Кампании Keitaro недоступны: ${describeError(error)}`);
      } finally {
        if (!cancelled) setCampaignLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [notify]);

  useEffect(() => {
    function closeOnOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (campaignPickerRef.current && !campaignPickerRef.current.contains(target)) setCampaignOpen(false);
      if (offerPickerRef.current && !offerPickerRef.current.contains(target)) setOffersOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutside);
    return () => document.removeEventListener("mousedown", closeOnOutside);
  }, []);

  const flows = campaign?.flows ?? [];
  const landingFlows = flows.filter((item) => item.schema === "landings");
  const flow = landingFlows.find((item) => item.id === flowId) ?? landingFlows[0] ?? null;
  const campaignText = campaignQuery.trim().toLowerCase();
  const visibleCampaigns = remoteCampaigns.filter((item) =>
    !campaignText
    || item.name.toLowerCase().includes(campaignText)
    || item.alias.toLowerCase().includes(campaignText)
    || String(item.id).includes(campaignText));

  // Подсказки показываются сразу при фокусе, в том числе на пустом поиске.
  useEffect(() => {
    if (!flow) {
      setOfferResults([]);
      setOffersLoading(false);
      return;
    }
    const term = offerSearch.trim();
    let cancelled = false;
    const controller = new AbortController();
    setOffersLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const rows = await api<OfferItem[]>(
          `/api/keitaro/offers${query({ search: term, limit: 20 })}`,
          { signal: controller.signal },
        );
        if (!cancelled) setOfferResults(rows);
      } catch (error) {
        if (!cancelled && !(error instanceof ApiError && error.code === "NETWORK" && controller.signal.aborted)) {
          notify("error", `Каталог офферов недоступен: ${describeError(error)}`);
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
  }, [offerSearch, offerReloadNonce, flow?.id, notify]);

  const selectedOfferIds = new Set(flow?.offers.map((item) => item.keitaro_offer_id) ?? []);
  const availableOffers = offerResults.filter((item) => !selectedOfferIds.has(item.id));
  const rawCustomId = offerSearch.trim();
  const customOfferId = /^\d+$/.test(rawCustomId) && Number(rawCustomId) > 0 ? Number(rawCustomId) : null;
  const customAlreadyAdded = customOfferId !== null && selectedOfferIds.has(customOfferId);
  const customInCatalog = customOfferId !== null && availableOffers.some((item) => item.id === customOfferId);
  const offerOptions: OfferOption[] = [
    ...availableOffers.map((offer) => ({
      id: offer.id,
      label: `#${offer.id} — ${offer.name}`,
      hint: "из каталога",
    })),
    ...(customOfferId !== null && !customAlreadyAdded && !customInCatalog
      ? [{ id: customOfferId, label: `Добавить оффер #${customOfferId}`, hint: "по ID, название может быть недоступно" }]
      : []),
  ];

  function applyDetail(detail: CampaignDetail, resetDrafts = false) {
    setCampaign(detail);
    // Остаёмся на том же редактируемом потоке, если он ещё есть;
    // потоки со схемой не landings не выбираются.
    const landings = detail.flows.filter((item) => item.schema === "landings");
    setFlowId((current) =>
      landings.some((item) => item.id === current)
        ? current
        : landings[0]?.id ?? null,
    );
    if (resetDrafts) setDraftShares({});
  }

  async function fetchKeitaro(keitaroId: number, force = false): Promise<CampaignDetail> {
    try {
      return await api<CampaignDetail>("/api/campaigns/fetch", {
        method: "POST",
        body: JSON.stringify({ keitaro_id: keitaroId, force }),
      });
    } catch (error) {
      if (error instanceof ApiError && error.code === "LOCAL_CHANGES" && !force) {
        const confirmed = await askConfirm({
          title: "Перезаписать локальные изменения?",
          message: "Есть локальные изменения. Fetch перезапишет их. Продолжить?",
          confirmLabel: "Продолжить",
          tone: "primary",
        });
        if (confirmed) return fetchKeitaro(keitaroId, true);
      }
      throw error;
    }
  }

  async function selectCampaign(selected: KeitaroCampaign) {
    if (!selected || !begin("select")) return;
    try {
      const local = localCampaigns.find((item) => item.keitaro_id === selected.id);
      const detail = local
        ? await api<CampaignDetail>(`/api/campaigns/${local.id}`)
        : await fetchKeitaro(selected.id);
      applyDetail(detail, true);
      setCampaignQuery(campaignOptionLabel(selected));
      setCampaignOpen(false);
      setCampaignActive(-1);
      if (!local) notify("success", `Локальная копия кампании ${selected.id} создана через Fetch`);
      await refreshLocal();
    } catch (error) {
      notify("error", describeError(error));
    } finally {
      end();
    }
  }

  async function runFetch() {
    if (!campaign || !begin("fetch")) return;
    try {
      const detail = await fetchKeitaro(campaign.keitaro_id);
      applyDetail(detail, true);
      notify("success", "Fetch из Keitaro выполнен");
      await refreshLocal();
    } catch (error) {
      notify("error", describeError(error));
    } finally {
      end();
    }
  }

  async function mutate(path: string, method: string, body?: unknown, success?: string): Promise<boolean> {
    if (!begin("offer")) return false;
    try {
      const detail = await api<CampaignDetail>(path, {
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      applyDetail(detail);
      if (success) notify("success", success);
      await refreshLocal();
      return true;
    } catch (error) {
      notify("error", describeError(error));
      return false;
    } finally {
      end();
    }
  }

  async function commitShare(offer: OfferDetail) {
    if (!campaign || !flow) return;
    const raw = draftShares[offer.keitaro_offer_id];
    if (raw === undefined) return;
    if (!/^\d+$/.test(raw) || Number(raw) < 1 || Number(raw) > 100) {
      notify("error", "Share — целое число от 1 до 100");
      setDraftShares((current) => ({ ...current, [offer.keitaro_offer_id]: String(offer.share) }));
      return;
    }
    const ok = await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers/${offer.keitaro_offer_id}`,
      "PATCH",
      { share: Number(raw) },
      `Share оффера ${offer.keitaro_offer_id} обновлён`,
    );
    if (ok) {
      setDraftShares((current) => {
        const next = { ...current };
        delete next[offer.keitaro_offer_id];
        return next;
      });
    }
  }

  async function toggleFixed(offer: OfferDetail, isFixed: boolean) {
    if (!campaign || !flow) return;
    await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers/${offer.keitaro_offer_id}`,
      "PATCH",
      { is_fixed: isFixed },
      `Fixed оффера ${offer.keitaro_offer_id}: ${isFixed ? "вкл" : "выкл"}`,
    );
  }

  async function deleteOffer(offer: OfferDetail) {
    if (!campaign || !flow) return;
    const confirmed = await askConfirm({
      title: "Удалить оффер?",
      message: `Оффер #${offer.keitaro_offer_id} будет перемещён в Deleted Offers. Доли остальных офферов будут пересчитаны.`,
      confirmLabel: "Удалить",
      tone: "danger",
    });
    if (!confirmed) return;
    await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers/${offer.keitaro_offer_id}`,
      "DELETE",
      undefined,
      `Оффер ${offer.keitaro_offer_id} удалён локально`,
    );
  }

  async function restoreOffer(offer: OfferDetail) {
    if (!campaign || !flow) return;
    await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers/${offer.keitaro_offer_id}/restore`,
      "POST",
      undefined,
      `Оффер ${offer.keitaro_offer_id} восстановлен`,
    );
  }

  async function addOffer(offerId: number) {
    if (!campaign || !flow) return;
    const ok = await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers`,
      "POST",
      { offer_id: offerId },
      `Оффер ${offerId} добавлен в поток`,
    );
    if (ok) {
      setOfferSearch("");
      setOffersOpen(false);
      setOfferActive(-1);
      setOfferReloadNonce((value) => value + 1);
    }
  }

  async function upload(force = forceUpload) {
    if (!flow || !begin("upload")) return;
    if (force) {
      const confirmed = await askConfirm({
        title: "Force upload",
        message: "Force upload перезапишет офферы потока в Keitaro. Продолжить?",
        confirmLabel: "Перезаписать",
        tone: "danger",
      });
      if (!confirmed) {
        end();
        return;
      }
    }
    try {
      const path = `/api/flows/${flow.id}/upload`;
      const send = (withForce: boolean) => api<CampaignDetail>(path, {
        method: "POST",
        body: JSON.stringify({ force: withForce }),
      });
      let detail: CampaignDetail;
      try {
        detail = await send(force);
      } catch (error) {
        const confirmed = error instanceof ApiError && error.code === "REMOTE_CHANGED" && !force
          ? await askConfirm({
            title: "Поток изменился в Keitaro",
            message: "Перезаписать его локальной версией (force upload)?",
            confirmLabel: "Перезаписать",
            tone: "danger",
          })
          : false;
        if (confirmed) {
          detail = await send(true);
        } else {
          throw error;
        }
      }
      applyDetail(detail);
      setForceUpload(false);
      notify("success", "Upload в Keitaro выполнен");
      await refreshLocal();
    } catch (error) {
      notify("error", describeError(error));
    } finally {
      end();
    }
  }

  function campaignKeys(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setCampaignOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!visibleCampaigns.length) return;
      event.preventDefault();
      setCampaignOpen(true);
      setCampaignActive((current) => event.key === "ArrowDown"
        ? Math.min(current + 1, visibleCampaigns.length - 1)
        : Math.max(current - 1, 0));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const selected = visibleCampaigns[campaignActive]
        ?? (visibleCampaigns.length === 1 ? visibleCampaigns[0] : undefined);
      if (!selected) return;
      setCampaignOpen(false);
      void selectCampaign(selected);
    }
  }

  function offerKeys(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOffersOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!offerOptions.length) return;
      event.preventDefault();
      setOffersOpen(true);
      setOfferActive((current) => event.key === "ArrowDown"
        ? Math.min(current + 1, offerOptions.length - 1)
        : Math.max(current - 1, 0));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const selected = offerOptions[offerActive]
        ?? (offerOptions.length === 1 ? offerOptions[0] : undefined);
      if (selected) void addOffer(selected.id);
    }
  }

  function localStatus(offer: OfferDetail) {
    if (!offer.is_active) return { text: "Inactive", tone: "error" };
    if (offer.readonly) return { text: "Read-only", tone: "modified" };
    if (flow?.sync_status === "error") return { text: "Error", tone: "error" };
    if (flow?.sync_status === "uploading") return { text: "Uploading", tone: "uploading" };
    if (flow?.sync_status === "modified") return { text: "Modified", tone: "modified" };
    return { text: "Active", tone: "active" };
  }

  return (
    <div className="edit-layout">
      <section className="card">
        <h2>Edit Campaign</h2>
        <p className="muted">
          Выберите кампанию Keitaro. При первом выборе backend выполнит Fetch и создаст локальную копию.
          Изменения сначала сохраняются локально; в Keitaro уходят только по Upload.
        </p>
        <div className="picker" ref={campaignPickerRef}>
          <input
            role="combobox"
            aria-label="Кампания Keitaro"
            aria-expanded={campaignOpen}
            aria-controls="campaign-options"
            aria-autocomplete="list"
            aria-activedescendant={campaignOpen && campaignActive >= 0 ? `campaign-option-${campaignActive}` : undefined}
            value={campaignQuery}
            onChange={(event) => {
              setCampaignQuery(event.target.value);
              setCampaignActive(-1);
              setCampaignOpen(true);
            }}
            onFocus={() => { setCampaignOpen(true); setCampaignActive(-1); }}
            onKeyDown={campaignKeys}
            placeholder="Поиск по названию, alias или ID"
            disabled={busy !== null}
          />
          {campaignOpen && (
            <div className="picker-menu" id="campaign-options" role="listbox">
              {campaignLoading && <div className="picker-empty">Загрузка списка…</div>}
              {!campaignLoading && visibleCampaigns.map((item, index) => (
                <div
                  key={item.id}
                  id={`campaign-option-${index}`}
                  role="option"
                  aria-selected={campaign?.keitaro_id === item.id}
                  tabIndex={-1}
                  className={`picker-option ${index === campaignActive ? "active" : ""} ${campaign?.keitaro_id === item.id ? "selected" : ""}`}
                  onMouseEnter={() => setCampaignActive(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    setCampaignOpen(false);
                    void selectCampaign(item);
                  }}
                >
                  <span>#{item.id} {item.name}</span>
                  <small>{item.alias}{item.state ? ` · ${item.state}` : ""}</small>
                </div>
              ))}
              {!campaignLoading && !visibleCampaigns.length && <div className="picker-empty">Кампании не найдены</div>}
            </div>
          )}
        </div>

        {campaign && (
          <div className="campaign-head">
            <h3>{campaign.name}</h3>
            <p className="muted">
              Keitaro ID: {campaign.keitaro_id} · alias: <code>{campaign.alias}</code> ·
              статус: <span className={`badge ${campaign.status}`}>{STATUS_TEXT[campaign.status] ?? campaign.status}</span>
            </p>
            <button disabled={busy !== null} onClick={runFetch}>
              {busy === "fetch" ? "Fetch…" : "Fetch from Keitaro"}
            </button>
          </div>
        )}
      </section>

      {campaign && flows.length > 0 && (
        <section className="card">
          <h2>Потоки</h2>
          <div className="flow-tabs">
            {flows.map((item) => {
              const selectable = item.schema === "landings";
              return (
                <button
                  key={item.id}
                  className={`flow-tab ${item.id === flow?.id ? "active" : ""} ${selectable ? "" : "disabled"}`}
                  disabled={!selectable || busy !== null}
                  aria-disabled={!selectable}
                  tabIndex={selectable ? undefined : -1}
                  title={selectable ? undefined : "Поток не редактируется: схема не landings"}
                  onClick={selectable ? () => { setFlowId(item.id); setDraftShares({}); } : undefined}
                  onContextMenu={selectable ? undefined : (event) => event.preventDefault()}
                >
                  <b>{item.name}</b>
                  <small>{item.schema} · {STATUS_TEXT[item.sync_status] ?? item.sync_status}</small>
                </button>
              );
            })}
          </div>

          {!flow && (
            <p className="muted">Потоки не редактируются: схема не landings. Остальные потоки показаны серыми выше.</p>
          )}

          {flow && (
            <div className="flow-panel">
              <div className="flow-toolbar">
                <div>
                  <b>Поток #{flow.keitaro_flow_id}</b> · позиция {flow.position} ·{" "}
                  <span className={`badge ${flow.sync_status}`}>{STATUS_TEXT[flow.sync_status] ?? flow.sync_status}</span>
                  <div className="muted">
                    Сумма shares (от backend): <b className={flow.shares_valid ? "ok" : "err"}>{flow.shares_sum}</b>
                    {!flow.shares_valid && " · конфигурация некорректна"}
                  </div>
                </div>
                <div className="toolbar-actions">
                  <label className="check-line">
                    <input
                      type="checkbox"
                      checked={forceUpload}
                      disabled={busy !== null}
                      onChange={(event) => setForceUpload(event.target.checked)}
                    />
                    Force upload
                  </label>
                  <button className="primary" disabled={busy !== null} onClick={() => upload()}>
                    {busy === "upload" ? "Upload…" : "Upload to Keitaro"}
                  </button>
                </div>
              </div>

              {flow.last_error && <p className="err">Последняя ошибка: {flow.last_error}</p>}
              {busy && <p className="muted">Операция: {BUSY_TEXT[busy] ?? "Выполнение"}…</p>}

              <div className="table-head">
                <h3>Offers</h3>
                <div className="offer-add">
                  <div className="picker" ref={offerPickerRef}>
                    <input
                      role="combobox"
                      aria-label="Найти оффер для добавления"
                      aria-expanded={offersOpen}
                      aria-controls="offer-options"
                      aria-autocomplete="list"
                      aria-activedescendant={offersOpen && offerActive >= 0 ? `offer-option-${offerActive}` : undefined}
                      value={offerSearch}
                      onChange={(event) => {
                        setOfferSearch(event.target.value);
                        setOfferActive(-1);
                        setOffersOpen(true);
                      }}
                      onFocus={() => { setOffersOpen(true); setOfferActive(-1); }}
                      onKeyDown={offerKeys}
                      placeholder="Название или ID оффера"
                      disabled={busy !== null}
                    />
                    {offersOpen && (
                      <div className="picker-menu" id="offer-options" role="listbox">
                        {offersLoading && !offerResults.length && <div className="picker-empty">Загрузка каталога…</div>}
                        {offerOptions.map((option, index) => (
                          <div
                            key={option.id}
                            id={`offer-option-${index}`}
                            role="option"
                            aria-selected={index === offerActive}
                            tabIndex={-1}
                            className={`picker-option ${index === offerActive ? "active" : ""}`}
                            onMouseEnter={() => setOfferActive(index)}
                            onMouseDown={(event) => event.preventDefault()}
                            onClick={() => void addOffer(option.id)}
                          >
                            <span>{option.label}</span>
                            {option.hint && <small>{option.hint}</small>}
                          </div>
                        ))}
                        {customAlreadyAdded && (
                          <div className="picker-empty">Оффер #{customOfferId} уже в потоке</div>
                        )}
                        {!offersLoading && !offerResults.length && <div className="picker-empty">Ничего не найдено</div>}
                        {!offersLoading && offerResults.length > 0 && !offerOptions.length && !customAlreadyAdded && (
                          <div className="picker-empty">Все найденные офферы уже добавлены</div>
                        )}
                      </div>
                    )}
                  </div>
                  <p className="muted offer-hint">Введите название или ID; уже добавленные офферы скрыты.</p>
                </div>
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Offer ID</th><th>Offer Name</th><th>Share</th>
                      <th>Fixed</th><th>Local Status</th><th>Keitaro State</th><th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {flow.offers.map((offer) => {
                      const status = localStatus(offer);
                      const hasDraft = draftShares[offer.keitaro_offer_id] !== undefined;
                      return (
                        <tr key={offer.id}>
                          <td>{offer.keitaro_offer_id}</td>
                          <td>
                            {offer.name_unavailable
                              ? <>Offer #{offer.keitaro_offer_id} <span className="muted">(название недоступно)</span></>
                              : offer.offer_name}
                          </td>
                          <td>
                            <div className="share-edit">
                              <input
                                className={`share-input ${hasDraft ? "dirty" : ""}`}
                                type="number"
                                min={1}
                                max={100}
                                step={1}
                                title="Целое число от 1 до 100; Enter сохраняет изменение"
                                aria-label={`Share оффера ${offer.keitaro_offer_id}`}
                                value={draftShares[offer.keitaro_offer_id] ?? String(offer.share)}
                                disabled={busy !== null}
                                onChange={(event) => setDraftShares((current) => ({
                                  ...current, [offer.keitaro_offer_id]: event.target.value,
                                }))}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter") {
                                    event.preventDefault();
                                    void commitShare(offer);
                                  }
                                }}
                              />
                              <button
                                type="button"
                                disabled={busy !== null || !hasDraft}
                                onClick={() => void commitShare(offer)}
                              >
                                Save
                              </button>
                            </div>
                          </td>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`Fixed оффера ${offer.keitaro_offer_id}`}
                              checked={offer.is_fixed}
                              disabled={busy !== null}
                              onChange={(event) => toggleFixed(offer, event.target.checked)}
                            />
                          </td>
                          <td>
                            <span
                              className={`badge ${status.tone}`}
                              title={offer.readonly ? "Keitaro помечает оффер как доступный только для чтения" : undefined}
                            >
                              {status.text}
                            </span>
                          </td>
                          <td>{offer.keitaro_state || "—"}</td>
                          <td>
                            <button
                              className="danger"
                              disabled={busy !== null}
                              onClick={() => deleteOffer(offer)}
                            >
                              Delete
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                    {!flow.offers.length && (
                      <tr><td colSpan={7} className="muted">В потоке нет активных офферов</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="muted share-hint">Share — целое число 1–100; ручной ввод делает оффер Fixed. Изменение сохраняется по Enter или кнопке Save.</p>

              <h3>Deleted Offers</h3>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Offer ID</th><th>Offer Name</th><th>Share</th><th>Keitaro State</th><th>Actions</th></tr></thead>
                  <tbody>
                    {flow.deleted_offers.map((offer) => (
                      <tr key={offer.id}>
                        <td>{offer.keitaro_offer_id}</td>
                        <td>{offer.name_unavailable ? `Offer #${offer.keitaro_offer_id}` : offer.offer_name}</td>
                        <td>{offer.share}</td>
                        <td>{offer.keitaro_state || "—"}</td>
                        <td>
                          <button
                            disabled={busy !== null}
                            onClick={() => restoreOffer(offer)}
                          >
                            Restore
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!flow.deleted_offers.length && (
                      <tr><td colSpan={5} className="muted">Удалённых офферов нет</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}

      {campaign && !flows.length && (
        <section className="card"><p className="muted">В кампании нет потоков.</p></section>
      )}

      {confirmRequest && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeConfirm(false);
          }}
        >
          <div
            className="modal card"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            aria-describedby="confirm-message"
            onKeyDown={(event) => {
              if (event.key === "Escape") closeConfirm(false);
            }}
          >
            <h2 id="confirm-title">{confirmRequest.title}</h2>
            <p id="confirm-message" className="muted">{confirmRequest.message}</p>
            <div className="modal-actions">
              <button type="button" autoFocus onClick={() => closeConfirm(false)}>Отмена</button>
              <button
                type="button"
                className={confirmRequest.tone === "danger" ? "danger" : "primary"}
                onClick={() => closeConfirm(true)}
              >
                {confirmRequest.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
