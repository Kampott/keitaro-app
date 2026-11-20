import { useCallback, useEffect, useState } from "react";
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

function readonlyReason(flow: FlowDetail): string {
  if (flow.schema !== "landings") return `schema = ${flow.schema}`;
  const inactive = [...flow.offers, ...flow.deleted_offers].find((offer) => offer.keitaro_state !== "active");
  return inactive ? `оффер ${inactive.keitaro_offer_id}: state = ${inactive.keitaro_state}` : "";
}

export default function EditCampaign({ notify }: Props) {
  const [remoteCampaigns, setRemoteCampaigns] = useState<KeitaroCampaign[]>([]);
  const [localCampaigns, setLocalCampaigns] = useState<CampaignSummary[]>([]);
  const [campaignSearch, setCampaignSearch] = useState("");
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [flowId, setFlowId] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [offerSearch, setOfferSearch] = useState("");
  const [offerResults, setOfferResults] = useState<OfferItem[]>([]);
  const [draftShares, setDraftShares] = useState<Record<number, string>>({});
  const [forceUpload, setForceUpload] = useState(false);

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

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const rows = await api<KeitaroCampaign[]>(
          `/api/keitaro/campaigns${query({ search: campaignSearch, limit: 50 })}`,
        );
        if (!cancelled) setRemoteCampaigns(rows);
      } catch (error) {
        if (!cancelled) notify("error", `Кампании Keitaro недоступны: ${describeError(error)}`);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [campaignSearch, notify]);

  const flows = campaign?.flows ?? [];
  const flow = flows.find((item) => item.id === flowId) ?? flows[0] ?? null;

  useEffect(() => {
    let cancelled = false;
    if (!flow || flow.readonly) return;
    const timer = window.setTimeout(async () => {
      try {
        const rows = await api<OfferItem[]>(`/api/keitaro/offers${query({ search: offerSearch, limit: 20 })}`);
        if (!cancelled) setOfferResults(rows);
      } catch (error) {
        if (!cancelled) notify("error", `Каталог офферов недоступен: ${describeError(error)}`);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [offerSearch, flow?.id, flow?.readonly, notify]);

  function applyDetail(detail: CampaignDetail) {
    setCampaign(detail);
    setFlowId((current) =>
      detail.flows.some((item) => item.id === current)
        ? current
        : (detail.flows.find((item) => !item.readonly)?.id ?? detail.flows[0]?.id ?? null));
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
    if (!selected || busy) return;
    setBusy("select");
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
      setBusy(null);
    }
  }

  async function runFetch() {
    if (!campaign || busy) return;
    setBusy("fetch");
    try {
      const detail = await fetchKeitaro(campaign.keitaro_id);
      applyDetail(detail);
      notify("success", "Fetch из Keitaro выполнен");
      await refreshLocal();
    } catch (error) {
      notify("error", describeError(error));
    } finally {
      setBusy(null);
    }
  }

  async function mutate(path: string, method: string, body?: unknown, success?: string) {
    setBusy("offer");
    try {
      const detail = await api<CampaignDetail>(path, {
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      applyDetail(detail);
      if (success) notify("success", success);
      await refreshLocal();
    } catch (error) {
      notify("error", describeError(error));
    } finally {
      setBusy(null);
    }
  }

  async function commitShare(offer: OfferDetail) {
    if (!campaign || !flow || flow.readonly || offer.readonly || busy) return;
    const raw = draftShares[offer.keitaro_offer_id];
    if (raw === undefined) return;
    if (!/^\d+$/.test(raw) || Number(raw) < 1 || Number(raw) > 100) {
      notify("error", "Share — целое число от 1 до 100");
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
    if (!campaign || !flow || busy) return;
    await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers/${offer.keitaro_offer_id}`,
      "PATCH",
      { is_fixed: isFixed },
      `Fixed оффера ${offer.keitaro_offer_id}: ${isFixed ? "вкл" : "выкл"}`,
    );
  }

  async function deleteOffer(offer: OfferDetail) {
    if (!campaign || !flow || busy) return;
    if (!window.confirm(`Удалить оффер ${offer.keitaro_offer_id} из потока? Он перейдёт в Deleted Offers.`)) return;
    await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers/${offer.keitaro_offer_id}`,
      "DELETE",
      undefined,
      `Оффер ${offer.keitaro_offer_id} удалён локально`,
    );
  }

  async function restoreOffer(offer: OfferDetail) {
    if (!campaign || !flow || busy) return;
    await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers/${offer.keitaro_offer_id}/restore`,
      "POST",
      undefined,
      `Оффер ${offer.keitaro_offer_id} восстановлен`,
    );
  }

  async function addOffer(offer: OfferItem) {
    if (!campaign || !flow || busy) return;
    await mutate(
      `/api/campaigns/${campaign.id}/flows/${flow.id}/offers`,
      "POST",
      { offer_id: offer.id },
      `Оффер ${offer.id} добавлен в поток`,
    );
    setOfferSearch("");
  }

  async function upload(force = forceUpload) {
    if (!flow || flow.readonly || busy) return;
    if (force && !window.confirm("Force upload перезапишет офферы потока в Keitaro. Продолжить?")) return;
    setBusy("upload");
    try {
      const send = (withForce: boolean) => api<CampaignDetail>(`/api/flows/${flow.id}/upload`, {
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
      setBusy(null);
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
            value={campaignSearch}
            onChange={(event) => setCampaignSearch(event.target.value)}
            placeholder="Поиск по названию, alias или ID"
          />
          <select
            value={campaign?.keitaro_id ?? ""}
            disabled={busy !== null}
            onChange={(event) => selectById(event.target.value)}
          >
            <option value="">— выберите кампанию —</option>
            {remoteCampaigns.map((item) => (
              <option key={item.id} value={item.id}>
                #{item.id} {item.name} ({item.alias}){item.state ? ` · ${item.state}` : ""}
              </option>
            ))}
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
                  <button disabled={busy !== null || flow.readonly} onClick={runFetch}>Fetch</button>
                  <label className="check-line">
                    <input
                      type="checkbox"
                      checked={forceUpload}
                      disabled={busy !== null || flow.readonly}
                      onChange={(event) => setForceUpload(event.target.checked)}
                    />
                    Force upload
                  </label>
                  <button className="primary" disabled={busy !== null || flow.readonly} onClick={() => upload()}>
                    {busy === "upload" ? "Upload…" : "Upload to Keitaro"}
                  </button>
                </div>
              </div>

              {flow.readonly && (
                <p className="warn">
                  Поток только для чтения: {readonlyReason(flow) || "нельзя редактировать офферы"}.
                  Mutate и Upload отклоняются backend с FLOW_READONLY.
                </p>
              )}
              {flow.last_error && <p className="err">Последняя ошибка: {flow.last_error}</p>}
              {busy && <p className="muted">Операция: {busy}…</p>}

              <div className="table-head">
                <h3>Offers</h3>
                {!flow.readonly && (
                  <div className="inline">
                    <input
                      value={offerSearch}
                      onChange={(event) => setOfferSearch(event.target.value)}
                      placeholder="Найти оффер для добавления"
                      disabled={busy !== null}
                    />
                    <div className="suggestions inline-suggestions">
                      {offerResults.map((offer) => (
                        <button key={offer.id} type="button" disabled={busy !== null} onClick={() => addOffer(offer)}>
                          + #{offer.id} {offer.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
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
                            value={draftShares[offer.keitaro_offer_id] ?? String(offer.share)}
                            disabled={busy !== null || flow.readonly || offer.readonly}
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
                            checked={offer.is_fixed}
                            disabled={busy !== null || flow.readonly || offer.readonly}
                            onChange={(event) => toggleFixed(offer, event.target.checked)}
                          />
                        </td>
                        <td><span className="badge active">Active</span></td>
                        <td>{offer.keitaro_state}</td>
                        <td>
                          <button
                            className="danger"
                            disabled={busy !== null || flow.readonly || offer.readonly}
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
                            disabled={busy !== null || flow.readonly || offer.readonly}
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
