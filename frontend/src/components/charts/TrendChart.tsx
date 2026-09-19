import { CircleSlash, type LucideIcon } from 'lucide-react';
import { useId, type ReactNode } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { DashboardCard } from '../ui/DashboardCard';
import { TrendDelta } from '../ui/primitives';

export interface TrendDatum {
  label: string;
  value: number | null;
}

const AXIS_TICK = { fill: '#69757e', fontSize: 10.5 };
const GRID_STROKE = 'rgba(255,255,255,0.05)';

interface ChartTooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ value?: unknown }>;
  label?: string | number;
  unit: string;
  decimals: number;
  color: string;
  series: string;
}

function ChartTooltip({ active, payload, label, unit, decimals, color, series }: ChartTooltipProps) {
  if (!active || !payload?.length) return null;
  const value = payload[0]?.value;
  return (
    <div className="rounded-lg border border-white/10 bg-ink-850/95 px-3 py-2 shadow-xl backdrop-blur">
      <p className="text-[10.5px] text-fg-subtle">{label}</p>
      <p className="mt-0.5 flex items-center gap-1.5 text-xs text-fg-muted">
        <span className="size-2 rounded-full" style={{ background: color }} />
        {series}
        <span className="font-semibold text-fg tabular">
          {typeof value === 'number' ? value.toFixed(decimals) : '—'} {unit}
        </span>
      </p>
    </div>
  );
}

interface TrendChartProps {
  title: string;
  icon: LucideIcon;
  color: string;
  unit: string;
  data: TrendDatum[];
  rangeLabel: string;
  decimals?: number;
  threshold?: { value: number; label: string };
  variant?: 'area' | 'bar';
  height?: number;
  current?: number | null;
  change?: number | null;
  emptyMessage?: string;
  delay?: number;
  className?: string;
  toolbar?: ReactNode;
}

export function TrendChart({
  title,
  icon,
  color,
  unit,
  data,
  rangeLabel,
  decimals = 0,
  threshold,
  variant = 'area',
  height = 190,
  current,
  change = null,
  emptyMessage,
  delay,
  className,
  toolbar,
}: TrendChartProps) {
  const gradientId = `trend-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const hasData = data.some((point) => point.value !== null);
  const tooltip = <ChartTooltip unit={unit} decimals={decimals} color={color} series={title.replace(/ Trend$/, '')} />;
  const reference = threshold && (
    <ReferenceLine
      y={threshold.value}
      stroke="#f5b544"
      strokeOpacity={0.6}
      strokeDasharray="4 4"
      ifOverflow="extendDomain"
    />
  );

  return (
    <DashboardCard
      title={title}
      subtitle={rangeLabel}
      icon={icon}
      iconColor={color}
      delay={delay}
      className={className}
      actions={
        <div className="text-right">
          <p className="text-lg leading-none font-semibold text-fg">
            {current === null || current === undefined ? '—' : current.toFixed(decimals)}
            <span className="ml-1 text-[11px] font-normal text-fg-subtle">{unit}</span>
          </p>
          <TrendDelta change={change} label="in range" className="mt-1 justify-end" />
        </div>
      }
    >
      {toolbar && <div className="mb-3 flex justify-end">{toolbar}</div>}
      {!hasData ? (
        <div className="grid place-items-center text-center" style={{ height }}>
          <div>
            <CircleSlash className="mx-auto size-5 text-fg-subtle" />
            <p className="mt-2 max-w-52 text-xs text-fg-muted">{emptyMessage ?? 'No monitoring data for this range.'}</p>
          </div>
        </div>
      ) : (
        <div style={{ height }} className="-ml-3">
          <ResponsiveContainer width="100%" height="100%">
            {variant === 'bar' ? (
              <BarChart data={data} margin={{ top: 10, right: 6, bottom: 0, left: 0 }} barCategoryGap="24%">
                <CartesianGrid vertical={false} stroke={GRID_STROKE} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={AXIS_TICK} minTickGap={24} interval="preserveStartEnd" />
                <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} width={34} allowDecimals={false} />
                <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} content={tooltip} />
                {reference}
                <Bar dataKey="value" fill={color} fillOpacity={0.85} radius={[4, 4, 0, 0]} maxBarSize={14} animationDuration={700} />
              </BarChart>
            ) : (
              <AreaChart data={data} margin={{ top: 10, right: 6, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={color} stopOpacity={0.28} />
                    <stop offset="100%" stopColor={color} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke={GRID_STROKE} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={AXIS_TICK} minTickGap={24} interval="preserveStartEnd" />
                <YAxis tickLine={false} axisLine={false} tick={AXIS_TICK} width={34} />
                <Tooltip cursor={{ stroke: 'rgba(255,255,255,0.18)', strokeWidth: 1 }} content={tooltip} />
                {reference}
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke={color}
                  strokeWidth={2}
                  fill={`url(#${gradientId})`}
                  connectNulls
                  dot={false}
                  activeDot={{ r: 4, fill: color, stroke: '#0a0d10', strokeWidth: 2 }}
                  animationDuration={800}
                />
              </AreaChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
      {threshold && hasData && (
        <p className="mt-2 flex items-center gap-2 text-[10.5px] text-fg-subtle">
          <span className="w-4 border-t border-dashed border-risk-moderate/70" aria-hidden />
          {threshold.label} · {threshold.value} {unit}
        </p>
      )}
    </DashboardCard>
  );
}

export function Sparkline({ data, color, unit, series, height = 56, decimals = 0 }: { data: TrendDatum[]; color: string; unit: string; series: string; height?: number; decimals?: number }) {
  if (!data.some((point) => point.value !== null)) {
    return (
      <div className="grid place-items-center text-[11px] text-fg-subtle" style={{ height }}>
        No history available
      </div>
    );
  }
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 2, bottom: 2, left: 2 }}>
          <XAxis dataKey="label" hide />
          <YAxis hide domain={['dataMin - 4', 'dataMax + 4']} />
          <Tooltip cursor={{ stroke: 'rgba(255,255,255,0.15)' }} content={<ChartTooltip unit={unit} decimals={decimals} color={color} series={series} />} />
          <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 3.5, fill: color, stroke: '#0a0d10', strokeWidth: 2 }} connectNulls animationDuration={700} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
