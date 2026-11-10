export type Step = 0 | 1 | 2 | 3;

export type Panel =
  | null
  | "help"
  | "providers"
  | "details"
  | "advanced"
  | "command"
  | "import"
  | "delivery"
  | "scenarios";

export interface Snapshot {
  purchased: boolean;
  connected: boolean;
  installed: boolean;
  active: Step;
  hidden: boolean;
  host: string;
  user: string;
  port: string;
  started: number | null;
}

export interface ProviderItem {
  name: string;
  product: string;
  kind: string;
  buy: string;
  console: string;
  guide: string;
}

export type PlatformId = "ios" | "android" | "mac" | "windows" | "linux";

export type NodeRole = "exit" | "relay" | "standalone";

export type NodeProtocolType = "vless" | "hysteria2";

export interface NodeData {
  name: string;
  host: string;
  port: number;
  role: NodeRole;
  type: NodeProtocolType;
  enabled?: boolean;
  health?: "ok" | "unknown" | "port" | "tls" | "timeout";
  exit_country?: string;
  exit_ip?: string;
  landing?: { host: string; port: number; name?: string };
}

export interface SubscriptionUserInfoModel {
  upload: number;
  download: number;
  total: number;
  expire?: number;
}

