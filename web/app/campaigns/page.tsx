"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiGet,
  apiPost,
  ApiError,
  type CampaignsListResponse,
  type CampaignListItem,
} from "@/lib/api";

export default function CampaignsPage() {
  const [data, setData] = useState<CampaignsListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiGet<CampaignsListResponse>("/api/campaigns");
      setData(res);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function signal(id: string, action: "pause" | "resume") {
    setBusyId(id);
    try {
      await apiPost(`/api/campaigns/${id}/${action}`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <h1>Campaigns</h1>
      {error && <p className="err">{error}</p>}
      <div className="panel-box">
        {!data ? (
          <p className="muted">Loading…</p>
        ) : data.items.length === 0 ? (
          <p className="muted">No campaigns</p>
        ) : (
          <table className="dense">
            <thead>
              <tr>
                <th>Name</th>
                <th>ID</th>
                <th>Strategy</th>
                <th>Gen</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c: CampaignListItem) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td className="num">{c.id}</td>
                  <td>{c.strategy}</td>
                  <td className="num">{c.generation}</td>
                  <td>
                    <span className="pill">{c.status}</span>
                  </td>
                  <td>
                    <div className="row-actions">
                      <button
                        type="button"
                        className="btn"
                        disabled={busyId === c.id || c.status === "paused"}
                        onClick={() => void signal(c.id, "pause")}
                      >
                        Pause
                      </button>
                      <button
                        type="button"
                        className="btn"
                        disabled={busyId === c.id || c.status === "running"}
                        onClick={() => void signal(c.id, "resume")}
                      >
                        Resume
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
