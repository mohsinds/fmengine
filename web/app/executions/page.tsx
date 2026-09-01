"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  apiGet,
  ApiError,
  type ExecutionsListResponse,
} from "@/lib/api";

export default function ExecutionsPage() {
  const [data, setData] = useState<ExecutionsListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiGet<ExecutionsListResponse>("/api/executions");
        if (!cancelled) {
          setData(res);
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
      <h1>Executions</h1>
      {error && <p className="err">{error}</p>}
      <div className="panel-box">
        {!data ? (
          <p className="muted">Loading…</p>
        ) : data.items.length === 0 ? (
          <p className="muted">No executions recorded</p>
        ) : (
          <table className="dense">
            <thead>
              <tr>
                <th>ID</th>
                <th>Strategy</th>
                <th>Lane</th>
                <th>Status</th>
                <th>Verdict</th>
                <th>Trades</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <Link href={`/executions/${item.id}`}>{item.id}</Link>
                  </td>
                  <td>{item.strategy}</td>
                  <td>{item.lane}</td>
                  <td>{item.status}</td>
                  <td>
                    {item.verdict ? (
                      <span className="pill">{item.verdict}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="num">{item.trade_count ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
