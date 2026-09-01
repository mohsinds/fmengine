const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export function apiBase(): string {
  return API_BASE;
}

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    method: "GET",
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  const body = await parseBody(res);
  if (!res.ok) {
    throw new ApiError(
      typeof body === "object" && body && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `GET ${path} failed (${res.status})`,
      res.status,
      body,
    );
  }
  return body as T;
}

export async function apiPost<T>(
  path: string,
  payload?: unknown,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    cache: "no-store",
  });
  const body = await parseBody(res);
  if (!res.ok) {
    const detail =
      typeof body === "object" && body && "detail" in body
        ? (body as { detail: unknown }).detail
        : null;
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "reason" in detail
          ? String((detail as { reason: unknown }).reason)
          : `POST ${path} failed (${res.status})`;
    throw new ApiError(message, res.status, body);
  }
  return body as T;
}

/* —— response shapes (hand-maintained MVP stubs; OpenAPI codegen later) —— */

export type HealthService = {
  name: string;
  ok: boolean;
  latency_ms?: number | null;
  detail?: string | null;
};

export type HealthResponse = {
  ok: boolean;
  services: HealthService[];
};

export type ResourcesResponse = {
  total_gb: number;
  used_gb: number;
  available_gb: number;
  docker_gb: number;
  ollama_gb: number;
  python_workers_gb: number;
  within_budget: boolean;
  budget: {
    docker_gb: number;
    ollama_gb: number;
    workers_gb: number;
    headroom_gb: number;
    total_gb: number;
  };
};

export type ExecutionListItem = {
  id: string;
  strategy: string;
  dataset_id: string;
  lane: string;
  status: string;
  verdict?: string | null;
  metrics_net?: Record<string, unknown>;
  trade_count?: number;
  fragile?: boolean;
  started_at?: string | null;
  finished_at?: string | null;
};

export type ExecutionsListResponse = {
  items: ExecutionListItem[];
  count: number;
};

export type ExecutionDetailResponse = {
  id: string;
  summary: Record<string, unknown>;
  verdict?: string | null;
  gates?: unknown;
};

export type EquityResponse = {
  execution_id: string;
  t: number[];
  equity: number[];
  points: number;
};

export type CampaignListItem = {
  id: string;
  status: string;
  generation: number;
  strategy: string;
  dataset_id: string;
  name: string;
};

export type CampaignsListResponse = {
  items: CampaignListItem[];
  count: number;
};

export type VaultStatusResponse = {
  strategies: { strategy: string; consumed: boolean; locked: boolean }[];
  count: number;
};

export type KillSwitchStatus = {
  engaged: boolean;
  reason?: string | null;
  engaged_by?: string | null;
  engaged_at?: string | null;
  cleared_by?: string | null;
  cleared_at?: string | null;
};
