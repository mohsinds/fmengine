"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiGet,
  apiPost,
  ApiError,
  type KillSwitchStatus,
  type VaultStatusResponse,
} from "@/lib/api";

export default function VaultPage() {
  const [status, setStatus] = useState<VaultStatusResponse | null>(null);
  const [kill, setKill] = useState<KillSwitchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [unlockStrategy, setUnlockStrategy] = useState("");
  const [unlockDataset, setUnlockDataset] = useState("");
  const [unlockJustification, setUnlockJustification] = useState("");
  const [unlockResult, setUnlockResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [v, k] = await Promise.all([
        apiGet<VaultStatusResponse>("/api/vault/status"),
        apiGet<KillSwitchStatus>("/api/vault/kill-switch"),
      ]);
      setStatus(v);
      setKill(k);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function engage() {
    if (!reason.trim()) {
      setError("Engage requires a reason");
      return;
    }
    setBusy(true);
    try {
      const k = await apiPost<KillSwitchStatus>("/api/vault/kill-switch/engage", {
        reason: reason.trim(),
        engaged_by: "operator",
      });
      setKill(k);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    setBusy(true);
    try {
      const k = await apiPost<KillSwitchStatus>("/api/vault/kill-switch/clear", {
        cleared_by: "operator",
      });
      setKill(k);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function unlockStub() {
    if (!unlockStrategy.trim() || !unlockDataset.trim() || !unlockJustification.trim()) {
      setError("Unlock requires strategy, dataset_id, and justification");
      return;
    }
    setBusy(true);
    setUnlockResult(null);
    try {
      const res = await apiPost<{ token?: { token_id?: string } }>(
        "/api/vault/unlock",
        {
          strategy: unlockStrategy.trim(),
          dataset_id: unlockDataset.trim(),
          justification: unlockJustification.trim(),
          actor: "operator",
        },
      );
      setUnlockResult(
        res.token?.token_id
          ? `Token issued: ${res.token.token_id}`
          : "Unlock ceremony completed",
      );
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Vault</h1>
      {error && <p className="err">{error}</p>}

      <h2>Kill switch</h2>
      <div className="panel-box">
        <p className="mb-2">
          Status{" "}
          <span className={`pill ${kill?.engaged ? "bad" : "ok"}`}>
            {kill?.engaged ? "engaged" : "clear"}
          </span>
          {kill?.reason && (
            <span className="muted ml-2">{kill.reason}</span>
          )}
        </p>
        <div className="field">
          <label htmlFor="ks-reason">Engage reason</label>
          <input
            id="ks-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why engage?"
          />
        </div>
        <div className="row-actions">
          <button
            type="button"
            className="btn danger"
            disabled={busy}
            onClick={() => void engage()}
          >
            Engage
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => void clear()}
          >
            Clear
          </button>
        </div>
      </div>

      <h2>Holdout status</h2>
      <div className="panel-box">
        {!status ? (
          <p className="muted">Loading…</p>
        ) : status.strategies.length === 0 ? (
          <p className="muted">No strategies registered</p>
        ) : (
          <table className="dense">
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Locked</th>
                <th>Consumed</th>
              </tr>
            </thead>
            <tbody>
              {status.strategies.map((s) => (
                <tr key={s.strategy}>
                  <td>{s.strategy}</td>
                  <td>
                    <span className={`pill ${s.locked ? "warn" : "ok"}`}>
                      {s.locked ? "locked" : "open"}
                    </span>
                  </td>
                  <td>
                    <span className={`pill ${s.consumed ? "bad" : "ok"}`}>
                      {s.consumed ? "yes" : "no"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>Unlock ceremony (stub)</h2>
      <div className="panel-box">
        <p className="muted mb-2 text-[11px]">
          One evaluation per strategy, ever. Justification is audit-logged.
        </p>
        <div className="field">
          <label htmlFor="ul-strategy">Strategy</label>
          <input
            id="ul-strategy"
            value={unlockStrategy}
            onChange={(e) => setUnlockStrategy(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="ul-dataset">Dataset ID</label>
          <input
            id="ul-dataset"
            value={unlockDataset}
            onChange={(e) => setUnlockDataset(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="ul-just">Justification</label>
          <textarea
            id="ul-just"
            value={unlockJustification}
            onChange={(e) => setUnlockJustification(e.target.value)}
          />
        </div>
        <button
          type="button"
          className="btn primary"
          disabled={busy}
          onClick={() => void unlockStub()}
        >
          Issue unlock token
        </button>
        {unlockResult && <p className="muted mt-2">{unlockResult}</p>}
      </div>
    </div>
  );
}
