import { CircleSlash } from 'lucide-react';
import { PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip } from 'recharts';
import type { Measurement } from '../../types/agents';

interface RadarTooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: { label?: string; value?: number | null; unit?: string; subScore?: number } }>;
}

function RadarTooltip({ active, payload }: RadarTooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="rounded-lg border border-white/10 bg-ink-850/95 px-3 py-2 shadow-xl backdrop-blur">
      <p className="text-[10.5px] text-fg-subtle">{point.label}</p>
      <p className="mt-0.5 text-xs text-fg">
        {point.value === null || point.value === undefined ? '—' : point.value} {point.unit}
      </p>
      <p className="text-[10.5px] text-fg-subtle">Relative sub-score: {point.subScore === undefined ? '—' : Math.round(point.subScore * 100)}%</p>
    </div>
  );
}

/**
 * "Relative Parameter Profile" — a normalized comparison chart across whatever measurements the
 * agent reported, using EACH measurement's own `subScore` (0..1), already computed deterministically
 * by the backend/agent (never recalculated here). Parameters have different units and scales, so raw
 * values are never plotted on one axis — only the agent's own normalized sub-scores are, and the
 * chart is explicitly labelled as relative, not a risk score.
 */
export function ParameterRadar({ measurements, color = '#7c9cff', height = 260 }: { measurements: Measurement[]; color?: string; height?: number }) {
  const points = measurements
    .filter((m) => m.subScore !== null && m.subScore !== undefined)
    .map((m) => ({ label: m.label, subScore: m.subScore as number, value: m.value, unit: m.unit }));

  if (points.length < 3) {
    return (
      <div className="grid place-items-center text-center" style={{ height }}>
        <div>
          <CircleSlash className="mx-auto size-5 text-fg-subtle" />
          <p className="mt-2 max-w-56 text-xs text-fg-muted">Not enough normalized parameters to plot a profile yet.</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={points} outerRadius="72%">
          <PolarGrid stroke="rgba(255,255,255,0.08)" />
          <PolarAngleAxis dataKey="label" tick={{ fill: '#9aa5ad', fontSize: 11 }} />
          <Radar dataKey="subScore" stroke={color} fill={color} fillOpacity={0.28} strokeWidth={2} isAnimationActive animationDuration={700} />
          <Tooltip content={<RadarTooltip />} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
