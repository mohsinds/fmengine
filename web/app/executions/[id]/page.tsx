"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { EquityChart } from "@/components/EquityChart";
import { MetricsBlock } from "@/components/MetricsBlock";
import { OutcomeBlock } from "@/components/OutcomeBlock";
import {
  apiGet,
  apiPost,
  ApiError,
  type EquityResponse,
  type ExecutionDetailResponse,
} from "@/lib/api";

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

function num(
  obj: Record<string, unknown>,
  keys: string[],
  fallback = 0,
): number {
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return fallback;
}

const MANIFEST_KEYS = [
  "code",
  "data",
  "features",
  "strategy",
  "costs",
  "risk",
  "validation",
  "environment",
  "params",
  "metrics_gross",
  "metrics_net",
  "steps",
  "funnel",
] as const;

export default function ExecutionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [detail, setDetail] = useState<ExecutionDetailResponse | null>(null);
  const [equity, setEquity] = useState<EquityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [promoteMsg, setPromoteMsg] = useState<string | null>(null);
  const [promoting, setPromoting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, eq] = await Promise.all([
        apiGet<ExecutionDetailResponse>(`/api/executions/${id}`),
        apiGet<EquityResponse>(`/api/executions/${id}/equity?points=2000`),
      ]);
      setDetail(d);
      setEquity(eq);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const summary = useMemo(() => asRecord(detail?.summary), [detail]);
  const metricsNet = useMemo(
    () => asRecord(summary.metrics_net),
    [summary],
  );
  const metricsGross = useMemo(
    () => asRecord(summary.metrics_gross),
    [summary],
  );

  const sharpe = num(metricsNet, ["sharpe", "sharpe_net"]);
  const dsr = num(metricsNet, ["dsr", "deflated_sharpe"]);
  const trialCount = Math.round(
    num(metricsNet, ["trial_count", "trials", "n_trials"]),
  );
  const costDragPct = num(
    summary,
    ["cost_drag_pct"],
    num(metricsNet, ["cost_drag_pct"]),
  );
  const winRate = num(metricsNet, ["hit_rate", "win_rate", "hitRate"], NaN);
  const expectancy = num(
    metricsNet,
    ["expectancy", "expectancy_net"],
    num(metricsGross, ["expectancy"], NaN),
  );

  async function onPromote() {
    setPromoting(true);
    setPromoteMsg(null);
    try {
      const res = await apiPost<{ allowed: boolean; reason: string }>(
        `/api/executions/${id}/promote`,
        { override: false },
      );
      setPromoteMsg(res.reason || "Promoted");
    } catch (e) {
      if (e instanceof ApiError) {
        setPromoteMsg(e.message);
      } else {
        setPromoteMsg(String(e));
      }
    } finally {
      setPromoting(false);
    }
  }

  if (error && !detail) {
    return (
      <div>
        <h1>Execution</h1>
        <p className="err">{error}</p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div>
        <h1>Execution</h1>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  return (
    <div>
      <div className="row-actions mb-3">
        <h1 className="!mb-0">{id}</h1>
        {detail.verdict && <span className="pill">{detail.verdict}</span>}
        <span className="muted">{String(summary.strategy ?? "")}</span>
        <span className="muted">{String(summary.lane ?? "")}</span>
        <button
          type="button"
          className="btn primary ml-auto"
          disabled={promoting}
          onClick={() => void onPromote()}
        >
          Promote
        </button>
      </div>
      {promoteMsg && (
        <p className={promoteMsg.toLowerCase().includes("fail") || promoteMsg.toLowerCase().includes("dsr") ? "err" : "muted"}>
          {promoteMsg}
        </p>
      )}

      <h2>Metrics</h2>
      <MetricsBlock
        sharpe={sharpe}
        dsr={dsr}
        trialCount={trialCount}
        costDragPct={costDragPct}
      />

      {Number.isFinite(winRate) && Number.isFinite(expectancy) && (
        <>
          <h2>Outcome</h2>
          <OutcomeBlock winRate={winRate} expectancy={expectancy} />
        </>
      )}

      <h2>Equity</h2>
      {equity ? (
        <EquityChart t={equity.t} equity={equity.equity} />
      ) : (
        <p className="muted">No equity data</p>
      )}

      <h2>Manifest</h2>
      {MANIFEST_KEYS.map((key) => {
        const section = summary[key];
        if (section === undefined || section === null) return null;
        return (
          <div key={key} className="manifest-section panel-box">
            <strong className="text-xs uppercase tracking-wider text-panel-muted">
              {key}
            </strong>
            <pre>{JSON.stringify(section, null, 2)}</pre>
          </div>
        );
      })}

      <div className="manifest-section panel-box">
        <strong className="text-xs uppercase tracking-wider text-panel-muted">
          full summary
        </strong>
        <pre>{JSON.stringify(summary, null, 2)}</pre>
      </div>
    </div>
  );
}
