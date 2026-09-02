"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { MetricsBlock } from "@/components/MetricsBlock";
import { OutcomeBlock } from "@/components/OutcomeBlock";
import {
  apiGet,
  apiPost,
  ApiError,
  type ExecutionsListResponse,
} from "@/lib/api";

type StrategyItem = { name: string; params_schema: JsonSchema };
type StrategiesResponse = { items: StrategyItem[]; count: number };
type DatasetItem = {
  id: string;
  symbol: string;
  timeframe: string;
  rows: number;
  has_volume: boolean;
};
type DatasetsResponse = { items: DatasetItem[]; count: number };
type CountsResponse = { total: number; by_strategy: Record<string, number> };

type JsonSchema = {
  properties?: Record<
    string,
    {
      type?: string;
      title?: string;
      default?: unknown;
      minimum?: number;
      maximum?: number;
      description?: string;
    }
  >;
  required?: string[];
};

type RunResult = {
  id: string;
  execution_id: string;
  strategy: string;
  params: Record<string, unknown>;
  metrics_net?: Record<string, unknown>;
  metrics_gross?: Record<string, unknown>;
  cost_drag_pct?: number | null;
  trade_count?: number;
  fragile?: boolean;
  cost_sensitivity?: Record<string, { sharpe?: number }>;
};

const SESSION_KEY = "fmtrader.lab.session_trials";

function num(v: unknown, fallback = 0): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export default function LabPage() {
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const [strategy, setStrategy] = useState("ema_cross");
  const [datasetId, setDatasetId] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [maxBars, setMaxBars] = useState("5000");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blockReason, setBlockReason] = useState<string | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [prev, setPrev] = useState<RunResult | null>(null);
  const [trialTotal, setTrialTotal] = useState(0);
  const [sessionTrials, setSessionTrials] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);

  const schema = useMemo(
    () => strategies.find((s) => s.name === strategy)?.params_schema,
    [strategies, strategy],
  );

  const selectedDataset = datasets.find((d) => d.id === datasetId);

  const refreshCounts = useCallback(async () => {
    const c = await apiGet<CountsResponse>("/api/registry/counts");
    setTrialTotal(c.total);
  }, []);

  useEffect(() => {
    const raw = window.localStorage.getItem(SESSION_KEY);
    setSessionTrials(raw ? Number(raw) || 0 : 0);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, d] = await Promise.all([
          apiGet<StrategiesResponse>("/api/strategies"),
          apiGet<DatasetsResponse>("/api/datasets"),
        ]);
        if (cancelled) return;
        setStrategies(s.items);
        setDatasets(d.items);
        if (d.items[0]) setDatasetId(d.items[0].id);
        await refreshCounts();
      } catch (e) {
        if (!cancelled) {
          setLoadError(
            e instanceof ApiError
              ? e.message
              : "Failed to load Lab — is the API running on :8000?",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshCounts]);

  useEffect(() => {
    if (!schema?.properties) {
      setParams({});
      return;
    }
    const next: Record<string, string> = {};
    for (const [key, prop] of Object.entries(schema.properties)) {
      if (prop.default !== undefined && prop.default !== null) {
        next[key] = String(prop.default);
      } else {
        next[key] = "";
      }
    }
    setParams(next);
  }, [schema]);

  useEffect(() => {
    // Capability gate — volume strategies vs XAUUSD bid-only
    if (strategy.toLowerCase().includes("volume") && selectedDataset && !selectedDataset.has_volume) {
      setBlockReason(
        `Dataset ${selectedDataset.id} has has_volume=false; strategy ${strategy} requires volume.`,
      );
    } else {
      setBlockReason(null);
    }
  }, [strategy, selectedDataset]);

  async function onRun() {
    setBusy(true);
    setError(null);
    try {
      const parsed: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(params)) {
        const prop = schema?.properties?.[k];
        if (prop?.type === "integer") parsed[k] = Number.parseInt(v, 10);
        else if (prop?.type === "number") parsed[k] = Number(v);
        else if (prop?.type === "boolean") parsed[k] = v === "true";
        else parsed[k] = v;
      }

      const validation = await apiPost<{
        ok: boolean;
        missing_capabilities?: string[];
        errors?: unknown;
      }>(`/api/strategies/${strategy}/validate`, {
        params: parsed,
        dataset_id: datasetId,
      });
      if (!validation.ok) {
        const miss = validation.missing_capabilities?.join(", ");
        setError(
          miss
            ? `Missing capability: ${miss}`
            : `Params invalid: ${JSON.stringify(validation.errors)}`,
        );
        return;
      }

      const run = await apiPost<RunResult>("/api/runs", {
        strategy,
        dataset_id: datasetId,
        params: parsed,
        lane: "vectorbt",
        max_bars: Number.parseInt(maxBars, 10) || 5000,
        run_sensitivity: true,
      });
      setPrev(result);
      setResult(run);
      const nextSession = sessionTrials + 1;
      setSessionTrials(nextSession);
      window.localStorage.setItem(SESSION_KEY, String(nextSession));
      await refreshCounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const net = result?.metrics_net ?? {};
  const sens15 = result?.cost_sensitivity?.["1.5x"]?.sharpe;

  return (
    <div className="stack">
      <div className="panel">
        <div className="panel-h" style={{ display: "flex", justifyContent: "space-between" }}>
          <span>Strategy Lab</span>
          <span className="num muted">
            session trials: {sessionTrials} · registry: {trialTotal}
          </span>
        </div>
        <div className="panel-b">
          {loadError && <p className="err">{loadError}</p>}
          <div className="lab-grid">
            <label>
              Strategy
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
                disabled={busy}
              >
                {strategies.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
              <span className="muted" style={{ fontSize: 12, display: "block", marginTop: 4 }}>
                Indicator family is fixed by the strategy module (e.g. ema_cross → EMA).
                The LLM does not pick indicators — see docs/INDICATORS_AND_EXPERIMENTS.md
              </span>
            </label>
            <label>
              Dataset
              <select
                value={datasetId}
                onChange={(e) => setDatasetId(e.target.value)}
                disabled={busy}
              >
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.id} ({d.rows.toLocaleString()} bars
                    {d.has_volume ? "" : ", no volume"})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Max bars
              <input
                className="num"
                value={maxBars}
                onChange={(e) => setMaxBars(e.target.value)}
                disabled={busy}
              />
            </label>
          </div>

          <div className="lab-params">
            <div className="muted" style={{ marginBottom: 8 }}>
              Parameters (from JSON Schema)
            </div>
            {schema?.properties ? (
              Object.entries(schema.properties).map(([key, prop]) => (
                <label key={key}>
                  {prop.title ?? key}
                  <input
                    className="num"
                    value={params[key] ?? ""}
                    onChange={(e) =>
                      setParams((p) => ({ ...p, [key]: e.target.value }))
                    }
                    disabled={busy}
                  />
                </label>
              ))
            ) : (
              <p className="muted">No parameters</p>
            )}
          </div>

          {blockReason && <p className="warn">{blockReason}</p>}
          {error && <p className="err">{error}</p>}

          <button
            type="button"
            className="btn"
            disabled={busy || !!blockReason || !datasetId}
            onClick={() => void onRun()}
          >
            {busy ? "Running…" : "Run (manual trial)"}
          </button>
        </div>
      </div>

      {result && (
        <div className="panel">
          <div className="panel-h">
            Result{" "}
            <Link href={`/executions/${result.execution_id}`}>
              {result.execution_id.slice(0, 12)}…
            </Link>
            {result.fragile ? (
              <span className="pill amber"> fragile</span>
            ) : null}
          </div>
          <div className="panel-b stack">
            <MetricsBlock
              sharpe={num(net.sharpe)}
              dsr={num(net.dsr ?? net.deflated_sharpe)}
              trialCount={trialTotal}
              costDragPct={num(result.cost_drag_pct)}
            />
            <OutcomeBlock
              winRate={num(net.hit_rate ?? net.win_rate)}
              expectancy={num(net.expectancy ?? net.expectancy_net)}
            />
            <p className="muted num">
              trades={result.trade_count ?? 0}
              {sens15 !== undefined ? ` · net Sharpe @1.5×=${num(sens15).toFixed(3)}` : ""}
            </p>
            {prev && (
              <div className="delta">
                <div className="muted">Delta vs previous Lab run</div>
                <p className="num">
                  ΔSharpe={(num(net.sharpe) - num(prev.metrics_net?.sharpe)).toFixed(3)} ·
                  Δtrades=
                  {(result.trade_count ?? 0) - (prev.trade_count ?? 0)} · Δcost drag=
                  {(num(result.cost_drag_pct) - num(prev.cost_drag_pct)).toFixed(1)}%
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panel-h">Recent executions</div>
        <div className="panel-b">
          <RecentHint />
        </div>
      </div>
    </div>
  );
}

function RecentHint() {
  const [items, setItems] = useState<ExecutionsListResponse["items"]>([]);
  useEffect(() => {
    void apiGet<ExecutionsListResponse>("/api/executions")
      .then((r) => setItems(r.items.slice(0, 8)))
      .catch(() => setItems([]));
  }, []);
  if (!items.length) return <p className="muted">No executions yet.</p>;
  return (
    <table className="dense">
      <thead>
        <tr>
          <th>id</th>
          <th>strategy</th>
          <th>status</th>
        </tr>
      </thead>
      <tbody>
        {items.map((it) => (
          <tr key={it.id}>
            <td className="num">
              <Link href={`/executions/${it.id}`}>{it.id.slice(0, 10)}…</Link>
            </td>
            <td>{it.strategy}</td>
            <td>{it.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
