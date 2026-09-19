import { ArrowUpRight, ShieldAlert, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useNavigation } from '../../context/NavigationContext';
import { cn, formatValue, pct, relativeChange } from '../../lib/format';
import type { RouteId } from '../../lib/routes';
import { RISK_STYLES } from '../../lib/risk';
import { waterProvenance } from '../../lib/waterSource';
import type { RiskLevel } from '../../types/agents';
import type { TrendPoint } from '../../types/environment';
import { AGENT_META } from '../agents/agentMeta';
import { AnimatedNumber } from '../ui/AnimatedNumber';
import { DashboardCard } from '../ui/DashboardCard';
import { DataModeBadge } from '../ui/DataModeBadge';
import { LoadingState } from '../ui/LoadingState';
import { TrendDelta } from '../ui/primitives';
import { RiskBadge } from '../ui/RiskBadge';
import { RiskGauge } from '../ui/RiskGauge';

interface StatCardProps {
  title: string;
  icon: LucideIcon;
  color: string;
  level: RiskLevel | null;
  pending: boolean;
  failure: string | null;
  hasData: boolean;
  change: number | null;
  route: RouteId;
  delay: number;
  children: ReactNode;
}

function StatCard({ title, icon: Icon, color, level, pending, failure, hasData, change, route, delay, children }: StatCardProps) {
  const { navigate } = useNavigation();
  return (
    <DashboardCard interactive delay={delay} accent={level ? RISK_STYLES[level].color : undefined} bodyClassName="flex flex-col p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ background: `${color}14`, color, border: `1px solid ${color}26` }}>
            <Icon className="size-4" />
          </span>
          <span className="line-clamp-2 text-[13px] leading-tight font-medium text-fg-muted">{title}</span>
        </div>
        {pending ? <LoadingState label="" /> : failure ? <RiskBadge level={null} emptyLabel="Unavailable" /> : <RiskBadge level={level} />}
      </div>

      <div className="relative mt-4 min-h-[92px] flex-1">
        {failure ? (
          <p className="text-xs leading-relaxed text-risk-high">Agent unavailable — {failure}</p>
        ) : !hasData ? (
          <LoadingState variant="skeleton" lines={3} />
        ) : (
          <div className={cn('transition-opacity duration-300', pending && 'opacity-15')}>{children}</div>
        )}
        {pending && hasData && (
          <div className="absolute inset-0 grid place-items-center">
            <span className="rounded-full border border-white/10 bg-ink-900/90 px-3 py-1.5 shadow-lg">
              <LoadingState label="Agent updating…" />
            </span>
          </div>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-white/[0.05] pt-3">
        <TrendDelta change={change} />
        <button type="button" onClick={() => navigate(route)} className="inline-flex items-center gap-0.5 text-[11px] font-medium text-fg-subtle transition hover:text-fg">
          Details
          <ArrowUpRight className="size-3" />
        </button>
      </div>
    </DashboardCard>
  );
}

function MainValue({ label, value, unit, decimals = 0 }: { label: string; value: number | null; unit?: string; decimals?: number }) {
  return (
    <div>
      <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">{label}</p>
      <p className="mt-1.5 flex items-baseline gap-1.5">
        <span className="text-[30px] leading-none font-semibold tracking-tight text-fg">
          {value === null ? '—' : <AnimatedNumber value={value} decimals={decimals} />}
        </span>
        {unit && <span className="text-xs text-fg-subtle">{unit}</span>}
      </p>
    </div>
  );
}

function Secondary({ items }: { items: Array<{ label: string; value: number | string | null; unit?: string }> }) {
  return (
    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {items.map((item) => (
        <span key={item.label} className="text-fg-subtle">
          {item.label}{' '}
          <span className="font-medium text-fg-muted tabular">
            {typeof item.value === 'string' ? item.value : formatValue(item.value)}
            {item.unit && item.value !== null ? ` ${item.unit}` : ''}
          </span>
        </span>
      ))}
    </div>
  );
}

function change(history: TrendPoint[] | undefined, key: 'pm25' | 'turbidity' | 'wasteCount') {
  if (!history?.length) return null;
  return relativeChange(history[0][key], history[history.length - 1][key]);
}

export function OverviewCards() {
  const { display, pending, failures, environment, state } = useAnalysis();
  const { air, water, waste, coordinator } = display;
  const history = environment && state.result && environment.location.name === state.result.location ? environment.history['24h'] : undefined;

  const deltas = [change(history, 'pm25'), change(history, 'turbidity'), change(history, 'wasteCount')].filter((value): value is number => value !== null);
  const overallChange = deltas.length ? deltas.reduce((sum, value) => sum + value, 0) / deltas.length : null;

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        title="Overall Environmental Risk"
        icon={ShieldAlert}
        color="#2dd4bf"
        level={coordinator?.overallRiskLevel ?? null}
        pending={pending.coordinator}
        failure={null}
        hasData={!!coordinator}
        change={overallChange}
        route="coordinator"
        delay={0}
      >
        {coordinator && (
          <div className="flex items-center gap-4">
            <RiskGauge score={coordinator.overallScore} level={coordinator.overallRiskLevel} size={88} stroke={7} label="" />
            <div className="min-w-0">
              <p className={cn('text-[26px] leading-none font-semibold tracking-tight', RISK_STYLES[coordinator.overallRiskLevel].text)}>{coordinator.overallRiskLevel}</p>
              <p className="mt-2 text-xs text-fg-subtle">
                Risk score <span className="font-medium text-fg tabular">{pct(coordinator.overallScore)}%</span>
              </p>
              <p className="mt-0.5 text-xs text-fg-subtle">
                Confidence <span className="font-medium text-fg-muted tabular">{pct(coordinator.confidence)}%</span>
              </p>
            </div>
          </div>
        )}
      </StatCard>

      <StatCard
        title="Air Quality"
        icon={AGENT_META.air.icon}
        color={AGENT_META.air.color}
        level={air?.riskLevel ?? null}
        pending={pending.air}
        failure={failures.air}
        hasData={!!air}
        change={change(history, 'pm25')}
        route="air"
        delay={0.05}
      >
        {air && (
          <>
            <MainValue label="PM2.5" value={air.pm25} unit="µg/m³" />
            <Secondary
              items={[
                { label: 'PM10', value: air.pm10, unit: 'µg/m³' },
                { label: 'AQI', value: air.aqi === null ? null : `${air.aqi} · ${air.aqiCategory}` },
              ]}
            />
          </>
        )}
      </StatCard>

      <StatCard
        title="Water Quality"
        icon={AGENT_META.water.icon}
        color={AGENT_META.water.color}
        level={water?.riskLevel ?? null}
        pending={pending.water}
        failure={failures.water}
        hasData={!!water}
        change={change(history, 'turbidity')}
        route="water"
        delay={0.1}
      >
        {water && (
          <>
            <MainValue label="pH" value={water.ph} decimals={1} />
            <Secondary
              items={[
                { label: 'Turbidity', value: water.turbidity, unit: 'NTU' },
                { label: 'Temp', value: water.temperature, unit: '°C' },
              ]}
            />
            <div className="mt-2.5">
              <DataModeBadge tone={waterProvenance(water).tone} label={waterProvenance(water).label} />
            </div>
          </>
        )}
      </StatCard>

      <StatCard
        title="Waste Density"
        icon={AGENT_META.waste.icon}
        color={AGENT_META.waste.color}
        level={waste?.riskLevel ?? null}
        pending={pending.waste}
        failure={failures.waste}
        hasData={!!waste}
        change={change(history, 'wasteCount')}
        route="waste"
        delay={0.15}
      >
        {waste && (
          <>
            <MainValue label="Detected objects" value={waste.totalObjects} />
            <Secondary
              items={[
                { label: 'Plastic', value: waste.counts.plastic },
                { label: 'Paper', value: waste.counts.paper },
                { label: 'Other', value: waste.counts.other },
              ]}
            />
          </>
        )}
      </StatCard>
    </div>
  );
}
