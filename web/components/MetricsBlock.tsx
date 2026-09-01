/**
 * MetricsBlock — indivisible unit.
 *
 * ALWAYS renders Sharpe, Deflated Sharpe (DSR), trial count, and cost drag together.
 * There is no code path that displays Sharpe alone (FRONTEND_SPEC §11 / §22).
 */

export type MetricsBlockProps = {
  /** Net Sharpe at 1.0× costs */
  sharpe: number;
  /** Deflated Sharpe Ratio */
  dsr: number;
  /** Trial registry count for this strategy / search */
  trialCount: number;
  /** Cost drag as % of gross P&L */
  costDragPct: number;
};

function fmt(n: number, digits = 3): string {
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

export function MetricsBlock({
  sharpe,
  dsr,
  trialCount,
  costDragPct,
}: MetricsBlockProps) {
  return (
    <div
      className="metrics-block"
      role="group"
      aria-label="Sharpe, DSR, trial count, and cost drag"
    >
      <div className="metric-cell">
        <span className="metric-label">Sharpe</span>
        <span className="metric-value num">{fmt(sharpe)}</span>
      </div>
      <div className="metric-cell">
        <span className="metric-label">DSR</span>
        <span className="metric-value num">{fmt(dsr)}</span>
      </div>
      <div className="metric-cell">
        <span className="metric-label">Trials</span>
        <span className="metric-value num">{trialCount}</span>
      </div>
      <div className="metric-cell">
        <span className="metric-label">Cost drag</span>
        <span className="metric-value num">{fmt(costDragPct, 1)}%</span>
      </div>
    </div>
  );
}
