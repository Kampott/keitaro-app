export type ReferenceItem = { id: number; name: string };
export type DomainItem = ReferenceItem & { is_ssl: boolean };
export type Country = { code: string; name: string };
export type OfferItem = { id: number; name: string };

export type Defaults = {
  domain_id: number | null;
  group_id: number | null;
  source_id: number | null;
  google_redirect_url: string;
};

export type KeitaroCampaign = {
  id: number;
  name: string;
  alias: string;
  state: string | null;
};

export type StreamResult = {
  id: number;
  name: string;
  schema: string;
  position: number;
};

export type CampaignCreateResult = {
  status: string;
  keitaro_id: number;
  name: string;
  alias: string;
  tracking_url: string | null;
  domain: ReferenceItem;
  group: ReferenceItem;
  source: ReferenceItem;
  offer: OfferItem;
  geo: string[];
  streams: StreamResult[];
  local_sync_failed: boolean;
  warning: string | null;
};

export type OfferDetail = {
  id: number;
  keitaro_offer_id: number;
  offer_name: string;
  share: number;
  is_fixed: boolean;
  keitaro_state: string;
  is_active: boolean;
  readonly: boolean;
  name_unavailable: boolean;
};

export type FlowDetail = {
  id: number;
  keitaro_flow_id: number;
  name: string;
  position: number;
  type: string;
  schema: string;
  state: string;
  sync_status: string;
  revision: number;
  shares_valid: boolean;
  shares_sum: number;
  readonly: boolean;
  last_error: string | null;
  last_fetched_at: string | null;
  last_uploaded_at: string | null;
  offers: OfferDetail[];
  deleted_offers: OfferDetail[];
};

export type CampaignSummary = {
  id: number;
  keitaro_id: number;
  name: string;
  alias: string;
  status: string;
  domain_id: number | null;
  group_id: number;
  source_id: number;
  last_fetched_at: string | null;
};

export type CampaignDetail = CampaignSummary & { flows: FlowDetail[] };

export type Notify = (kind: "success" | "error" | "info", text: string) => void;
