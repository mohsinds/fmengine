/**
 * EquityChart — Phase 11 MVP uses a simple SVG polyline.
 *
 * Production target: uPlot with server-downsampled (~2000) points and
 * range-fetched full resolution on zoom (FRONTEND_SPEC §10).
 */

export type EquityChartProps = {
  t: number[];
  equity: number[];
  height?: number;
};

export function EquityChart({ t, equity, height = 220 }: EquityChartProps) {
  if (!t.length || !equity.length || t.length !== equity.length) {
    return (
      <div className="panel-box text-panel-muted text-sm">No equity series</div>
    );
  }

  const w = 800;
  const h = height;
  const pad = 8;
  const minY = Math.min(...equity);
  const maxY = Math.max(...equity);
  const minX = Math.min(...t);
  const maxX = Math.max(...t);
  const spanY = maxY - minY || 1;
  const spanX = maxX - minX || 1;

  const points = equity
    .map((y, i) => {
      const x = pad + ((t[i]! - minX) / spanX) * (w - pad * 2);
      const yy = h - pad - ((y - minY) / spanY) * (h - pad * 2);
      return `${x.toFixed(2)},${yy.toFixed(2)}`;
    })
    .join(" ");

  return (
    <div className="panel-box overflow-hidden">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full"
        role="img"
        aria-label="Equity curve"
        preserveAspectRatio="none"
        style={{ height }}
      >
        <polyline
          fill="none"
          stroke="#5b8def"
          strokeWidth="1.5"
          points={points}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <p className="mt-1 text-[10px] text-panel-muted">
        {equity.length} pts (LTTB) · uPlot is the production chart target
      </p>
    </div>
  );
}
