import { useState } from 'react';
import {
  Car,
  Factory,
  Flame,
  HardHat,
  HeartPulse,
  Home,
  Info,
  Layers,
  Navigation,
  Pickaxe,
  Sparkles,
  Trees,
  Truck,
  Wheat,
  Wind,
  Zap,
} from 'lucide-react';
import { getPollutantMetadata, HEALTH_DISCLAIMER, POLLUTANTS } from '../../data/pollutantMetadata';
import { evaluateComparison } from '../../lib/pollutantInterpretation';
import { cn } from '../../lib/format';
import type { AirAgentResult, Measurement } from '../../types/agents';
import type { GeographicContext } from '../../types/environment';
import { DashboardCard } from '../ui/DashboardCard';
import { Chip } from '../ui/primitives';

interface PollutantDetailCardProps {
  airResult?: AirAgentResult | null;
  geographicContext?: GeographicContext | null;
  className?: string;
}

const SOURCE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  Car,
  Factory,
  Zap,
  Home,
  Wheat,
  HardHat,
  Pickaxe,
  Wind,
  Flame,
  Truck,
  Trees,
  Layers,
  Navigation,
};

export function PollutantDetailCard({ airResult, geographicContext, className }: PollutantDetailCardProps) {
  const [selectedKey, setSelectedKey] = useState<string>('pm25');
  const metadata = getPollutantMetadata(selectedKey) ?? POLLUTANTS.pm25;

  const measurement: Measurement | undefined = airResult?.measurements.find(
    (m) => m.key.toLowerCase() === selectedKey.toLowerCase(),
  );

  const measuredValue = measurement?.value ?? null;
  const measuredUnit = measurement?.unit ?? metadata.unit;
  const measuredPeriod = measurement?.averagingPeriod ?? '24-hour';

  // Guidelines
  const who24h = metadata.guideline_references.who_2021.find(
    (g) => g.averaging_period === measuredPeriod,
  ) ?? metadata.guideline_references.who_2021[0];

  const cpcbStd = metadata.guideline_references.cpcb_naaqs.find(
    (g) => g.averaging_period === measuredPeriod,
  ) ?? metadata.guideline_references.cpcb_naaqs[0];

  const comparison = evaluateComparison(
    measuredValue,
    measuredUnit,
    measuredPeriod,
    who24h?.value,
    who24h?.unit ?? metadata.unit,
    who24h?.averaging_period ?? '24-hour',
    measurement?.subScore,
  );

  // Contextual Overpass features
  const nearbyRoads = geographicContext?.roads ?? [];
  const nearbyIndustrial = geographicContext?.industrialFeatures ?? [];

  return (
    <DashboardCard
      title="Pollutant Health & Emission Source Profile"
      subtitle="Authoritative health thresholds (WHO 2021 AQG vs CPCB NAAQS), physiological effects, and source mechanics"
      icon={HeartPulse}
      iconColor="#ef4444"
      className={cn('relative', className)}
    >
      {/* Pollutant Tabs */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-black/[0.06] pb-3">
        {Object.values(POLLUTANTS).map((p) => {
          const isSelected = p.key === selectedKey;
          const liveMeasurement = airResult?.measurements.find((m) => m.key.toLowerCase() === p.key);
          const hasReading = liveMeasurement?.value != null;

          return (
            <button
              key={p.key}
              type="button"
              onClick={() => setSelectedKey(p.key)}
              className={cn(
                'relative flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all',
                isSelected
                  ? 'bg-brand text-white shadow-sm'
                  : 'bg-black/[0.03] text-fg-muted hover:bg-black/[0.06] hover:text-fg',
              )}
            >
              <span>{p.code}</span>
              {hasReading && (
                <span
                  className={cn(
                    'size-1.5 rounded-full',
                    isSelected ? 'bg-white' : 'bg-risk-high',
                  )}
                  title="Measured at active station"
                />
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-4 grid gap-6 lg:grid-cols-12">
        {/* Left Column: Measurements & Dual Thresholds */}
        <div className="space-y-4 lg:col-span-5">
          {/* Header & Classification */}
          <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <span className="text-[11px] font-semibold tracking-wider text-fg-subtle uppercase">
                  {metadata.code}
                </span>
                <h4 className="text-base font-semibold text-fg">{metadata.name}</h4>
              </div>
              <Chip
                color={
                  metadata.is_secondary_pollutant
                    ? '#9333ea'
                    : metadata.source_type === 'direct_and_secondary'
                    ? '#0284c7'
                    : '#d97706'
                }
              >
                {metadata.is_secondary_pollutant
                  ? 'Secondary Pollutant'
                  : metadata.source_type === 'direct_and_secondary'
                  ? 'Direct & Secondary'
                  : 'Direct Emitter'}
              </Chip>
            </div>

            <p className="mt-2 text-xs leading-relaxed text-fg-subtle">
              {metadata.description}
            </p>

            {/* Current Reading */}
            <div className="mt-4 rounded-lg border border-black/[0.06] bg-white/70 p-3 shadow-xs">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-fg-subtle">Measured Concentration</span>
                <span className="rounded bg-black/[0.04] px-1.5 py-0.5 text-[10px] font-mono text-fg-muted">
                  {measuredPeriod} avg
                </span>
              </div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-bold tracking-tight text-fg tabular">
                  {measuredValue !== null ? measuredValue : '—'}
                </span>
                <span className="text-xs font-semibold text-fg-subtle">
                  {measuredValue !== null ? measuredUnit : 'No station measurement'}
                </span>
              </div>

              {/* Dynamic Comparison Banner */}
              {comparison.isCompatible && comparison.ratio !== null && (
                <div
                  className={cn(
                    'mt-2.5 flex items-center justify-between gap-2 rounded-md p-2 text-xs',
                    comparison.interpretationLabel === 'CRITICAL'
                      ? 'bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300'
                      : comparison.interpretationLabel === 'SIGNIFICANTLY ABOVE REFERENCE'
                      ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
                      : comparison.interpretationLabel === 'ABOVE GUIDELINE REFERENCE'
                      ? 'bg-yellow-50 text-yellow-800 dark:bg-yellow-950/40 dark:text-yellow-300'
                      : 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300',
                  )}
                >
                  <span className="font-semibold">
                    {comparison.ratio >= 1.0
                      ? `${comparison.ratio}× WHO Guideline`
                      : 'Below WHO Guideline'}
                  </span>
                  <span className="text-[11px] font-medium opacity-90">
                    {comparison.interpretationDescription}
                  </span>
                </div>
              )}

              {!comparison.isCompatible && (
                <div className="mt-2.5 rounded-md bg-black/[0.03] p-2 text-[11px] text-fg-subtle">
                  <Info className="mr-1 inline-block size-3 text-fg-subtle" />
                  {comparison.note}
                </div>
              )}
            </div>

            {/* Authoritative Dual Standards Comparison (Strictly Separated) */}
            <div className="mt-4 space-y-2">
              <p className="text-[10.5px] font-semibold tracking-wider text-fg-subtle uppercase">
                Authoritative Reference Comparison
              </p>

              {/* WHO Health Guideline */}
              <div className="flex items-center justify-between rounded-lg border border-blue-500/20 bg-blue-50/40 p-2.5 dark:bg-blue-950/20">
                <div>
                  <span className="text-[10px] font-bold tracking-wider text-blue-600 uppercase dark:text-blue-400">
                    WHO 2021 Health Guideline
                  </span>
                  <p className="text-xs font-semibold text-fg">
                    {who24h ? `${who24h.value} ${who24h.unit}` : '—'}
                    <span className="ml-1 text-[10px] font-normal text-fg-subtle">
                      ({who24h?.averaging_period ?? '24-hour'} AQG)
                    </span>
                  </p>
                </div>
                {measuredValue !== null && who24h && (
                  <span
                    className={cn(
                      'text-xs font-bold tabular',
                      measuredValue <= who24h.value ? 'text-emerald-600' : 'text-risk-high',
                    )}
                  >
                    {measuredValue <= who24h.value
                      ? 'Within Reference'
                      : `+${(measuredValue - who24h.value).toFixed(1)} ${who24h.unit}`}
                  </span>
                )}
              </div>

              {/* India CPCB Regulatory Standard */}
              <div className="flex items-center justify-between rounded-lg border border-purple-500/20 bg-purple-50/40 p-2.5 dark:bg-purple-950/20">
                <div>
                  <span className="text-[10px] font-bold tracking-wider text-purple-600 uppercase dark:text-purple-400">
                    India CPCB / NAAQS (2009)
                  </span>
                  <p className="text-xs font-semibold text-fg">
                    {cpcbStd ? `${cpcbStd.value} ${cpcbStd.unit}` : '—'}
                    <span className="ml-1 text-[10px] font-normal text-fg-subtle">
                      ({cpcbStd?.averaging_period ?? '24-hour'} standard)
                    </span>
                  </p>
                </div>
                {measuredValue !== null && cpcbStd && (
                  <span
                    className={cn(
                      'text-xs font-bold tabular',
                      measuredValue <= cpcbStd.value ? 'text-emerald-600' : 'text-amber-600',
                    )}
                  >
                    {measuredValue <= cpcbStd.value
                      ? 'Within Standard'
                      : `+${(measuredValue - cpcbStd.value).toFixed(1)} ${cpcbStd.unit}`}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Health Effects & Major Sources */}
        <div className="space-y-4 lg:col-span-7">
          {/* Health Effects Section */}
          <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-fg">
              <HeartPulse className="size-4 text-red-500" />
              <span>What can exposure affect? (Health Guidance)</span>
            </div>

            <ul className="mt-3 space-y-2 text-xs text-fg-subtle">
              {metadata.health_effects.map((effect, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="mt-1 size-1.5 shrink-0 rounded-full bg-red-400" />
                  <span className="leading-relaxed">{effect}</span>
                </li>
              ))}
            </ul>

            {metadata.vulnerable_groups.length > 0 && (
              <div className="mt-3 border-t border-black/[0.05] pt-2.5">
                <span className="text-[10.5px] font-medium tracking-wide text-fg-subtle uppercase">
                  Vulnerable populations:
                </span>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {metadata.vulnerable_groups.map((grp, idx) => (
                    <span
                      key={idx}
                      className="rounded-md border border-black/[0.06] bg-white px-2 py-0.5 text-[11px] text-fg-muted"
                    >
                      {grp}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Emission Sources Section */}
          <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-semibold text-fg">
                <Factory className="size-4 text-blue-600" />
                <span>Where does this pollutant commonly come from?</span>
              </div>
              <span className="text-[10px] text-fg-subtle">Major source categories</span>
            </div>

            {/* Special Ozone Precursor Banner */}
            {metadata.is_secondary_pollutant && (
              <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-50/60 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                <div className="flex items-center gap-1.5 font-semibold">
                  <Sparkles className="size-3.5 text-amber-600" />
                  <span>Important: Ozone is formed secondarily in the atmosphere</span>
                </div>
                <p className="mt-1 text-[11px] leading-relaxed opacity-95">
                  {metadata.secondary_formation}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5 text-[10.5px]">
                  <span className="font-medium text-amber-800 dark:text-amber-300">Precursors:</span>
                  {metadata.precursor_pollutants.map((prec, idx) => (
                    <span
                      key={idx}
                      className="rounded bg-amber-200/60 px-1.5 py-0.2 font-mono text-amber-950 dark:bg-amber-800/60 dark:text-amber-100"
                    >
                      {prec}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Source Categories Grid */}
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {metadata.primary_sources.map((src, idx) => {
                const IconComponent = (src.icon && SOURCE_ICONS[src.icon]) || Factory;

                return (
                  <div
                    key={idx}
                    className="flex items-start gap-2.5 rounded-lg border border-black/[0.05] bg-white/70 p-2.5 shadow-2xs"
                  >
                    <span className="grid size-7 shrink-0 place-items-center rounded-md bg-black/[0.04] text-fg-muted">
                      <IconComponent className="size-3.5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-fg">{src.category}</p>
                      <p className="mt-0.5 text-[11px] leading-snug text-fg-subtle">
                        {src.description}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Location-Aware Contextual Evidence (Guarded) */}
            {(nearbyRoads.length > 0 || nearbyIndustrial.length > 0) && (
              <div className="mt-3 rounded-lg border border-black/[0.06] bg-black/[0.015] p-2.5 text-xs">
                <div className="flex items-center gap-1.5 font-medium text-fg">
                  <Navigation className="size-3.5 text-brand" />
                  <span>Mapped Environmental Context near this location</span>
                </div>
                <ul className="mt-1.5 space-y-1 text-[11px] text-fg-subtle">
                  {nearbyRoads.length > 0 && ['pm25', 'pm10', 'no2', 'co'].includes(metadata.key) && (
                    <li>
                      • Nearby road traffic ({nearbyRoads.length} mapped segment(s)) is a potential source category for NO₂ and particulate matter.
                    </li>
                  )}
                  {nearbyIndustrial.length > 0 && ['pm25', 'pm10', 'so2', 'no2'].includes(metadata.key) && (
                    <li>
                      • Nearby industrial zoning ({nearbyIndustrial.length} mapped feature(s)) represents a potential category for combustion and process emissions.
                    </li>
                  )}
                </ul>
                <p className="mt-2 text-[10px] text-fg-muted italic">
                  Note: Contextual inference only based on OpenStreetMap features — not measured facility attribution. Does not claim a specific nearby facility caused this reading.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Footer: Compact Health Disclaimer & Citations */}
      <div className="mt-4 flex flex-col justify-between gap-2 border-t border-black/[0.06] pt-3 text-[11px] text-fg-subtle sm:flex-row sm:items-center">
        <p className="max-w-2xl leading-snug">
          <span className="font-semibold text-fg-muted">Health Disclaimer: </span>
          {HEALTH_DISCLAIMER}
        </p>
        <div className="shrink-0 text-right font-mono text-[10px] text-fg-muted">
          <span>Sources: WHO AQG (2021) · CPCB NAAQS (2009)</span>
        </div>
      </div>
    </DashboardCard>
  );
}
