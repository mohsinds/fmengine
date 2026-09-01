"use client";

import { useEffect, useState } from "react";
import {
  apiGet,
  ApiError,
  type HealthResponse,
  type ResourcesResponse,
} from "@/lib/api";

export default function HealthDashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [resources, setResources] = useState<ResourcesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, r] = await Promise.all([
          apiGet<HealthResponse>("/api/system/health"),
          apiGet<ResourcesResponse>("/api/system/resources"),
        ]);
        if (!cancelled) {
          setHealth(h);
          setResources(r);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1>System health</h1>
      {error && <p className="err">{error}</p>}

      <h2>Services</h2>
      <div className="panel-box">
        {!health ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            <p className="mb-2">
              Overall{" "}
              <span className={`pill ${health.ok ? "ok" : "bad"}`}>
                {health.ok ? "ok" : "degraded"}
              </span>
            </p>
            <table className="dense">
              <thead>
                <tr>
                  <th>Service</th>
                  <th>Status</th>
                  <th>Latency</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {health.services.map((s) => (
                  <tr key={s.name}>
                    <td>{s.name}</td>
                    <td>
                      <span className={`pill ${s.ok ? "ok" : "bad"}`}>
                        {s.ok ? "ok" : "down"}
                      </span>
                    </td>
                    <td className="num">
                      {s.latency_ms != null ? `${s.latency_ms.toFixed(0)} ms` : "—"}
                    </td>
                    <td className="muted">{s.detail ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      <h2>Resources</h2>
      <div className="panel-box">
        {!resources ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            <p className="mb-2">
              Budget{" "}
              <span
                className={`pill ${resources.within_budget ? "ok" : "warn"}`}
              >
                {resources.within_budget ? "within" : "over"}
              </span>
              <span className="num muted ml-2">
                {resources.used_gb.toFixed(2)} / {resources.budget.total_gb.toFixed(1)}{" "}
                GB used
              </span>
            </p>
            <table className="dense">
              <thead>
                <tr>
                  <th>Bucket</th>
                  <th>Used</th>
                  <th>Budget</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Docker</td>
                  <td className="num">{resources.docker_gb.toFixed(2)} GB</td>
                  <td className="num">{resources.budget.docker_gb.toFixed(1)} GB</td>
                </tr>
                <tr>
                  <td>Ollama</td>
                  <td className="num">{resources.ollama_gb.toFixed(2)} GB</td>
                  <td className="num">{resources.budget.ollama_gb.toFixed(1)} GB</td>
                </tr>
                <tr>
                  <td>Workers</td>
                  <td className="num">
                    {resources.python_workers_gb.toFixed(2)} GB
                  </td>
                  <td className="num">{resources.budget.workers_gb.toFixed(1)} GB</td>
                </tr>
                <tr>
                  <td>Available</td>
                  <td className="num">{resources.available_gb.toFixed(2)} GB</td>
                  <td className="num">
                    headroom {resources.budget.headroom_gb.toFixed(1)} GB
                  </td>
                </tr>
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
