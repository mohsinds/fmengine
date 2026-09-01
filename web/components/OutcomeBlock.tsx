/**
 * OutcomeBlock — win rate never renders without expectancy beside it
 * (FRONTEND_SPEC §15.1).
 */

export type OutcomeBlockProps = {
  winRate: number;
  /** Expectancy per trade (prefer net) */
  expectancy: number;
  label?: string;
};

function fmtPct(n: number): string {
  if (!Number.isFinite(n)) return "—";
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${pct.toFixed(1)}%`;
}

function fmtExp(n: number): string {
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(4);
}

export function OutcomeBlock({
  winRate,
  expectancy,
  label = "Outcome",
}: OutcomeBlockProps) {
  return (
    <div
      className="outcome-block"
      role="group"
      aria-label={`${label}: win rate and expectancy`}
    >
      <div className="metric-cell">
        <span className="metric-label">Win rate</span>
        <span className="metric-value num">{fmtPct(winRate)}</span>
      </div>
      <div className="metric-cell">
        <span className="metric-label">Expectancy</span>
        <span className="metric-value num">{fmtExp(expectancy)}</span>
      </div>
    </div>
  );
}
