/**
 * The dashboard's opening hero — one big contextual photograph standing in for a dozen small
 * flat cards. The background is one frame of the landing page's day-to-night valley sequence,
 * chosen by the coordinator's overall risk level, so "things are getting worse" always reads as
 * "the scenery is getting more polluted" — the same visual language as the landing story.
 *
 * Content is identical to what the old OverviewCards grid showed (overall risk, air, water,
 * waste), just laid out as one primary stat plus three secondary rows, weather-app style.
 */
import { motion } from 'framer-motion';
import { Bell, RefreshCw, Search, ShieldAlert, type LucideIcon } from 'lucide-react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useNavigation } from '../../context/NavigationContext';
import { cn, pct } from '../../lib/format';
import { RISK_STYLES } from '../../lib/risk';
import type { RiskLevel, SpecialistAgentId } from '../../types/agents';
import { AGENT_META } from '../agents/agentMeta';
import { LoadingState } from '../ui/LoadingState';
import { heroBackgroundFor } from './heroBackground';

const HEADLINES: Record<RiskLevel | 'none', string> = {
  LOW: 'Conditions look clear',
  MODERATE: 'Moderate signals detected',
  HIGH: 'Elevated environmental risk',
  none: 'Awaiting analysis',
};

function IconButton({
  icon: Icon,
  label,
  onClick,
  spinning,
}: {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
  spinning?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="grid size-9 shrink-0 place-items-center rounded-full border border-white/15 bg-white/10 text-white backdrop-blur-sm transition hover:bg-white/20"
    >
      <Icon className={cn('size-4', spinning && 'animate-spin')} />
    </button>
  );
}

function SecondaryRow({
  agentId,
  label,
  value,
  unit,
  level,
  pending,
  failure,
  hasData,
}: {
  agentId: SpecialistAgentId;
  label: string;
  value: string | null;
  unit?: string;
  level: RiskLevel | null;
  pending: boolean;
  failure: string | null;
  hasData: boolean;
}) {
  const { navigate } = useNavigation();
  const meta = AGENT_META[agentId];
  const Icon = meta.icon;
  const dotColor = level ? RISK_STYLES[level].color : 'rgba(255,255,255,0.35)';

  return (
    <button
      type="button"
      onClick={() => navigate(meta.route)}
      className="flex items-center justify-between gap-3 rounded-2xl border border-white/10 px-4 py-3 text-left backdrop-blur-md transition hover:border-white/25"
      style={{ background: `${meta.color}17` }}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="size-1.5 shrink-0 rounded-full" style={{ background: dotColor }} aria-hidden />
        <div className="min-w-0">
          <p className="text-[10.5px] font-medium tracking-wide text-white/55 uppercase">{label}</p>
          <p className="truncate text-sm font-semibold text-white">{meta.short}</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2.5">
        {pending ? (
          <LoadingState label="" />
        ) : failure ? (
          <span className="text-xs text-risk-high">Unavailable</span>
        ) : !hasData || value === null ? (
          <span className="text-xs text-white/50">Awaiting</span>
        ) : (
          <span className="flex items-baseline gap-1">
            <span className="text-lg leading-none font-semibold text-white tabular">{value}</span>
            {unit && <span className="text-xs text-white/60">{unit}</span>}
          </span>
        )}
        <Icon className="size-5" style={{ color: meta.color }} />
      </div>
    </button>
  );
}

export function HeroOverview() {
  const { display, pending, failures, environment, state, runAnalysis } = useAnalysis();
  const { air, water, waste, coordinator } = display;
  const { navigate } = useNavigation();

  const location = state.result?.location ?? state.selectedLocation ?? environment?.location.name ?? 'No location selected';
  const level = coordinator?.overallRiskLevel ?? null;
  const background = heroBackgroundFor(level);
  const running = state.phase === 'running';

  const history =
    environment && state.result && environment.location.name === state.result.location ? environment.history['24h'] : undefined;
  const strip = (history ?? []).slice(-6);

  const airValue = air ? (air.aqi != null ? String(air.aqi) : air.pm25 != null ? String(Math.round(air.pm25)) : '—') : null;
  const airUnit = air && air.aqi == null ? 'µg/m³' : undefined;

  return (
    <section className="relative isolate overflow-hidden rounded-3xl border border-white/10 shadow-2xl shadow-black/50">
      <img src={background} alt="" aria-hidden className="absolute inset-0 -z-20 h-full w-full object-cover" />
      <div className="absolute inset-0 -z-10 bg-gradient-to-t from-black/85 via-black/25 to-black/50" aria-hidden />
      <div className="absolute inset-0 -z-10 hidden bg-gradient-to-r from-black/55 via-transparent to-transparent md:block" aria-hidden />

      <div className="relative grid gap-6 p-5 sm:p-8 xl:grid-cols-[1fr_320px]">
        <div className="flex min-h-[380px] flex-col justify-between gap-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-medium text-white/60">Welcome back</p>
              <p className="text-base font-semibold text-white">{location}</p>
            </div>
            <div className="flex items-center gap-2">
              <IconButton icon={Search} label="Environmental map" onClick={() => navigate('map')} />
              <IconButton icon={Bell} label="Recommendations" onClick={() => navigate('coordinator')} />
              <IconButton icon={RefreshCw} label="Refresh analysis" onClick={() => void runAnalysis({ instant: true })} spinning={running} />
            </div>
          </div>

          <div>
            <span className="inline-flex items-center rounded-full border border-white/20 bg-white/10 px-3 py-1 text-[11px] font-medium text-white/80 backdrop-blur-sm">
              Environmental forecast
            </span>
            <h1 className="mt-4 text-[clamp(1.9rem,4vw,3.1rem)] leading-[1.05] font-bold tracking-tight text-white">
              {HEADLINES[level ?? 'none']}
            </h1>
            <p className="mt-3 max-w-lg text-[13.5px] leading-relaxed text-white/75">
              {coordinator?.reasoning ?? 'Run an analysis to get the coordinator’s cross-signal assessment for this location.'}
            </p>
          </div>

          {strip.length > 0 && (
            <div className="flex items-end gap-5 overflow-x-auto sm:gap-8">
              {strip.map((point, index) => {
                const isNow = index === strip.length - 1;
                return (
                  <div key={point.timestamp} className="flex shrink-0 flex-col items-center gap-1.5">
                    <span className={cn('text-lg tabular', isNow ? 'font-bold text-white' : 'font-medium text-white/70')}>
                      {point.pm25 !== null ? Math.round(point.pm25) : '—'}
                    </span>
                    <span className={cn('text-[11px]', isNow ? 'font-semibold text-white' : 'text-white/55')}>
                      {isNow ? 'Now' : `${point.hoursAgo}h ago`}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-3">
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="rounded-2xl border border-white/15 bg-white/10 p-5 backdrop-blur-md"
          >
            <div className="flex items-center gap-1.5 text-xs font-medium text-white/70">
              <ShieldAlert className="size-3.5" />
              Overall risk
            </div>
            {!coordinator ? (
              pending.coordinator ? (
                <LoadingState variant="skeleton" lines={2} className="mt-3" />
              ) : (
                <p className="mt-3 text-sm text-white/60">Awaiting analysis</p>
              )
            ) : (
              <>
                <p className={cn('mt-2 text-[34px] leading-none font-bold tracking-tight', RISK_STYLES[coordinator.overallRiskLevel].text)}>
                  {coordinator.overallRiskLevel}
                </p>
                <div className="mt-3 flex items-center gap-4 text-xs text-white/70">
                  <span>
                    Score <span className="font-semibold text-white tabular">{pct(coordinator.overallScore)}%</span>
                  </span>
                  <span>
                    Confidence <span className="font-semibold text-white tabular">{pct(coordinator.confidence)}%</span>
                  </span>
                </div>
              </>
            )}
          </motion.div>

          <SecondaryRow
            agentId="air"
            label="Air quality"
            value={airValue}
            unit={airUnit}
            level={air?.riskLevel ?? null}
            pending={pending.air}
            failure={failures.air}
            hasData={!!air}
          />
          <SecondaryRow
            agentId="water"
            label="Water quality"
            value={water?.ph != null ? water.ph.toFixed(1) : null}
            unit="pH"
            level={water?.riskLevel ?? null}
            pending={pending.water}
            failure={failures.water}
            hasData={!!water}
          />
          <SecondaryRow
            agentId="waste"
            label="Waste density"
            value={waste ? String(waste.totalObjects) : null}
            unit="objects"
            level={waste?.riskLevel ?? null}
            pending={pending.waste}
            failure={failures.waste}
            hasData={!!waste}
          />
        </div>
      </div>
    </section>
  );
}
