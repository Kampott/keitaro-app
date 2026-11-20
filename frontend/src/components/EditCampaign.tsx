import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, describeError, query } from "../api";
import type {
  CampaignDetail, CampaignSummary, FlowDetail, KeitaroCampaign, Notify, OfferDetail, OfferItem,
} from "../types";

type Props = { notify: Notify };

const STATUS_TEXT: Record<string, string> = {
  synced: "Синхронизировано",
  modified: "Изменено локально",
  uploading: "Отправка",
  error: "Ошибка",
};

export default function EditCampaign({ notify }: Props) {
  const [remoteCampaigns, setRemoteCampaigns] = useState<KeitaroCampaign[]>([]);
  const [campaignLoading, setCampaignLoading] = useState(true);
  const [localCampaigns, setLocalCampaigns] = useState<CampaignSummary[]>([]);
  const [campaignSearch, setCampaignSearch] = useState("");
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [flowId, setFlowId] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const busyRef = useRef(false);
  const [offerSearch, setOfferSearch] = useState("");
  const [offerResults, setOfferResults] = useState<OfferItem[]>([]);
  const [offersLoading, setOffersLoading] = useState(false);
  const [customOfferId, setCustomOfferId] = useState("");
  const [draftShares, setDraftShares] = useState<Record<number, string>>({});
  const [forceUpload, setForceUpload] = useState(false);

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

  const flows = campaign?.flows ?? [];
  const flow = flows.find((item) => item.id === flowId) ?? flows[0] ?? null;
  const searchText = campaignSearch.trim().toLowerCase();
  const visibleCampaigns = remoteCampaigns.filter((item) =>
    !searchText
    || item.name.toLowerCase().includes(searchText)
    || item.alias.toLowerCase().includes(searchText)
    || String(item.id).includes(searchText));

  //Autocomplete показывает каталог сразу (в том числе на пустом поиске),
  //поэтому список появляется при фокусе, а не только после двух символов.
  useEffect(() => {
    if (!flow) {
      setOfferResults([]);
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
  }, [offerSearch, flow?.id, notify]);

  function applyDetail(detail: CampaignDetail) {
    setCampaign(detail);
    setFlowId(detail.flows[0]?.id ?? null);
    setDraftShares({});
  }

  async function fetchKeitaro(keitaroId: number, force = false): Promise<CampaignDetail> {
    try {
      return await api<CampaignDetail>("/api/campaigns/fetch", {
        method: "POST",
        body: JSON.stringify({ keitaro_id: keitaroId, force }),
      });
    } catch (error) {
      if (error instanceof ApiError && error.code === "LOCAL_CHANGES" && !force) {
        if (window.confirm("Есть локальные изменения. Fetch перезапишет их. Продолжить?")) {
          return fetchKeitaro(keitaroId, true);
        }
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
      applyDetail(detail);
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
      applyDetail(detail);
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
    await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers/${offer.keitaro_offer_id}`,
      "PATCH",
      { share: Number(raw) },
      `Share оффера ${offer.keitaro_offer_id} обновлён`,
    );
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
    if (!window.confirm(`Удалить оффер ${offer.keitaro_offer_id} из потока? Он перейдёт в Deleted Offers.`)) return;
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
      setOfferResults([]);
      setCustomOfferId("");
    }
  }

  async function addCustomOffer() {
    const raw = customOfferId.trim();
    if (!/^\d+$/.test(raw) || Number(raw) <= 0) {
      notify("error", "Offer ID — положительное целое число");
      return;
    }
    await addOffer(Number(raw));
  }

  async function upload(force = forceUpload) {
    if (!flow || !begin("upload")) return;
    if (force && !window.confirm("Force upload перезапишет офферы потока в Keitaro. Продолжить?")) {
      end();
      return;
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
        if (error instanceof ApiError && error.code === "REMOTE_CHANGED" && !force &&
            window.confirm("Поток изменился в Keitaro. Перезаписать его локальной версией (force upload)?")) {
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

  function selectById(value: string) {
    const item = remoteCampaigns.find((campaignItem) => campaignItem.id === Number(value));
    if (item) void selectCampaign(item);
  }

  return (
    <div className="edit-layout">
      <section className="card">
        <h2>Edit Campaign</h2>
        <p className="muted">
          Выберите кампанию Keitaro. При первом выборе backend выполнит Fetch и создаст локальную копию.
          Изменения сначала сохраняются локально; в Keitaro уходят только по Upload.
        </p>
        <div className="inline">
          <input
            aria-label="Поиск кампании по названию, alias или ID"
            value={campaignSearch}
            onChange={(event) => setCampaignSearch(event.target.value)}
            placeholder="Поиск по названию, alias или ID"
          />
          <select
            aria-label="Кампания Keitaro"
            value={campaign?.keitaro_id ?? ""}
            disabled={busy !== null}
            onChange={(event) => selectById(event.target.value)}
          >
            <option value="">— выберите кампанию —</option>
            {campaignLoading && <option disabled>Загрузка списка…</option>}
            {visibleCampaigns.map((item) => (
              <option key={item.id} value={item.id} title={`${item.name} (${item.alias})`}>
                #{item.id} {item.name} ({item.alias}){item.state ? ` · ${item.state}` : ""}
              </option>
            ))}
            {!campaignLoading && !visibleCampaigns.length && <option disabled>Ничего не найдено</option>}
          </select>
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
            {flows.map((item) => (
              <button
                key={item.id}
                className={`flow-tab ${item.id === flow?.id ? "active" : ""}`}
                disabled={busy !== null}
                onClick={() => { setFlowId(item.id); setDraftShares({}); }}
              >
                <b>{item.name}</b>
                <small>{item.schema} · {STATUS_TEXT[item.sync_status] ?? item.sync_status}</small>
              </button>
            ))}
          </div>

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
                  <button disabled={busy !== null} onClick={runFetch}>Fetch</button>
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
              {busy && <p className="muted">Операция: {busy}…</p>}

              <div className="table-head">
                <h3>Offers</h3>
                <div className="offer-add">
                  <div className="inline">
                    <input
                      aria-label="Найти оффер для добавления"
                      value={offerSearch}
                      onChange={(event) => setOfferSearch(event.target.value)}
                      placeholder="Название или ID оффера"
                      disabled={busy !== null}
                    />
                    <div className="suggestions inline-suggestions">
                      {offersLoading && <span className="muted">Загрузка…</span>}
                      {!offersLoading && offerResults.map((offer) => (
                        <button key={offer.id} type="button" disabled={busy !== null} onClick={() => addOffer(offer.id)}>
                          + #{offer.id} {offer.name}
                        </button>
                      ))}
                      {!offersLoading && !offerResults.length && <span className="muted">Ничего не найдено</span>}
                    </div>
                  </div>
                  <div className="inline">
                    <input
                      aria-label="Произвольный Offer ID"
                      value={customOfferId}
                      onChange={(event) => setCustomOfferId(event.target.value)}
                      onKeyDown={(event) => { if (event.key === "Enter") void addCustomOffer(); }}
                      placeholder="Произвольный Offer ID"
                      disabled={busy !== null}
                    />
                    <button type="button" disabled={busy !== null || !customOfferId.trim()} onClick={addCustomOffer}>
                      Добавить по ID
                    </button>
                  </div>
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
                    {flow.offers.map((offer) => (
                      <tr key={offer.id}>
                        <td>{offer.keitaro_offer_id}</td>
                        <td>
                          {offer.name_unavailable
                            ? <>Offer #{offer.keitaro_offer_id} <span className="muted">(название недоступно)</span></>
                            : offer.offer_name}
                        </td>
                        <td>
                          <input
                            className="share-input"
                            type="number"
                            min={1}
                            max={100}
                            step={1}
                            title="Целое число от 1 до 100"
                            aria-label={`Share оффера ${offer.keitaro_offer_id}`}
                            value={draftShares[offer.keitaro_offer_id] ?? String(offer.share)}
                            disabled={busy !== null}
                            onChange={(event) => setDraftShares((current) => ({
                              ...current, [offer.keitaro_offer_id]: event.target.value,
                            }))}
                            onBlur={() => commitShare(offer)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                void commitShare(offer);
                              }
                            }}
                          />
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
                        <td><span className="badge active">Active</span></td>
                        <td>{offer.keitaro_state}</td>
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
                    ))}
                    {!flow.offers.length && (
                      <tr><td colSpan={7} className="muted">В потоке нет активных офферов</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="muted share-hint">Share — целое число 1–100; ручной ввод делает оффер Fixed.</p>

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
                        <td>{offer.keitaro_state}</td>
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
    </div>
  );
}
