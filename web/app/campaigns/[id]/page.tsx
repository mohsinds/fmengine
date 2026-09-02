"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/api";

type CampaignDetail = {
  campaign_id: string;
  status: string;
  generation: number;
  config: {
    name: string;
    strategy: string;
    max_generations: number;
    use_stub_llm?: boolean;
  };
  active_ingredients?: string[];
  budget?: {
    per_campaign_usd: number;
    spent_usd: number;
  };
  last_error?: string | null;
};

type TraceResponse = {
  events: Array<{
    generation: number;
    critique?: string;
    decision?: string;
  }>;
  count: number;
};

type GenList = {
  generations: Array<{
    n: number;
    status: string;
    survivor_count: number;
    ingredients: string[];
  }>;
};

export default function CampaignDetailPage() {
  const params = useParams();
  const id = String(params.id ?? "");
  const [detail, setDetail] = useState<CampaignDetail | null>(null);
  const [trace, setTrace] = useState<TraceResponse | null>(null);
  const [gens, setGens] = useState<GenList | null>(null);
  const [journal, setJournal] = useState("");
  const [selectedGen, setSelectedGen] = useState<number | null>(null);
  const [genDetail, setGenDetail] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [d, t, g, j] = await Promise.all([
        apiGet<CampaignDetail>(`/api/campaigns/${id}`),
        apiGet<TraceResponse>(`/api/campaigns/${id}/trace`),
        apiGet<GenList>(`/api/campaigns/${id}/generations`),
        apiGet<{ markdown: string }>(`/api/campaigns/${id}/journal`),
      ]);
      setDetail(d);
      setTrace(t);
      setGens(g);
      setJournal(j.markdown || "");
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [load]);

  async function signal(action: "pause" | "resume" | "abort") {
    setBusy(true);
    try {
      await apiPost(`/api/campaigns/${id}/${action}`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function openGen(n: number) {
    setSelectedGen(n);
    try {
      setGenDetail(await apiGet(`/api/campaigns/${id}/generations/${n}`));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  const maxG = detail?.config.max_generations ?? 1;
  const cur = detail?.generation ?? 0;
  const pct = Math.min(100, Math.round((cur / Math.max(1, maxG)) * 100));
  const spent = detail?.budget?.spent_usd ?? 0;
  const cap = detail?.budget?.per_campaign_usd ?? 0;

  return (
    <div>
      <p className="muted">
        <Link href="/campaigns">← Campaigns</Link>
      </p>
      <h1>{detail?.config.name ?? "Campaign"}</h1>
      <p className="muted num">{id}</p>
      {error && <p className="err">{error}</p>}

      <div className="panel-box mb-2">
        {!detail ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            <p>
              Status <span className="pill">{detail.status}</span> · strategy{" "}
              <code>{detail.config.strategy}</code> · stub=
              {String(!!detail.config.use_stub_llm)}
            </p>
            <p>
              Generation{" "}
              <strong>
                {cur} / {maxG}
              </strong>{" "}
              ({pct}%)
            </p>
            <div
              style={{
                height: 8,
                background: "var(--border, #333)",
                borderRadius: 4,
                overflow: "hidden",
                marginBottom: 12,
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: "var(--accent, #6af)",
                }}
              />
            </div>
            <p>
              LLM spend ${spent.toFixed(4)}
              {cap > 0 ? ` / $${cap.toFixed(2)} cap` : ""}
            </p>
            {!!detail.active_ingredients?.length && (
              <p>
                Ingredients:{" "}
                {detail.active_ingredients.map((x) => (
                  <span key={x} className="pill" style={{ marginRight: 4 }}>
                    {x}
                  </span>
                ))}
              </p>
            )}
            {detail.last_error && <p className="err">{detail.last_error}</p>}
            <div className="row-actions">
              <button
                type="button"
                className="btn"
                disabled={busy || detail.status === "paused"}
                onClick={() => void signal("pause")}
              >
                Pause
              </button>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => void signal("resume")}
              >
                Resume
              </button>
              <button
                type="button"
                className="btn"
                disabled={busy || detail.status === "aborted"}
                onClick={() => void signal("abort")}
              >
                Abort
              </button>
            </div>
          </>
        )}
      </div>

      <h2>Generations</h2>
      <div className="panel-box">
        {!gens ? (
          <p className="muted">Loading…</p>
        ) : gens.generations.length === 0 ? (
          <p className="muted">No generations yet</p>
        ) : (
          <table className="dense">
            <thead>
              <tr>
                <th>#</th>
                <th>Status</th>
                <th>Survivors</th>
                <th>Ingredients</th>
              </tr>
            </thead>
            <tbody>
              {gens.generations.map((g) => (
                <tr key={g.n}>
                  <td className="num">
                    <button type="button" className="btn" onClick={() => void openGen(g.n)}>
                      {g.n}
                    </button>
                  </td>
                  <td>
                    <span className="pill">{g.status}</span>
                  </td>
                  <td className="num">{g.survivor_count}</td>
                  <td>{(g.ingredients || []).join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selectedGen != null && genDetail && (
        <>
          <h2>Generation {selectedGen} detail</h2>
          <div className="panel-box">
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
              {typeof genDetail.markdown === "string" && genDetail.markdown
                ? String(genDetail.markdown)
                : JSON.stringify(genDetail.event ?? genDetail, null, 2)}
            </pre>
          </div>
        </>
      )}

      <h2>Decision timeline</h2>
      <div className="panel-box">
        {!trace || trace.events.length === 0 ? (
          <p className="muted">No structured decisions yet</p>
        ) : (
          <ol>
            {trace.events.map((e) => (
              <li key={e.generation} style={{ marginBottom: 12 }}>
                <strong>Gen {e.generation}</strong>
                <div className="muted" style={{ fontSize: 13 }}>
                  {(e.decision || "").slice(0, 240)}
                </div>
                {e.critique && (
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    Critique: {e.critique.slice(0, 200)}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>

      <h2>Journal</h2>
      <div className="panel-box">
        <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, maxHeight: 480, overflow: "auto" }}>
          {journal || "(empty)"}
        </pre>
      </div>
    </div>
  );
}
