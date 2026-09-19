import { Layers, Map as MapIcon, RadioTower } from 'lucide-react';
import { useState } from 'react';
import { AGENT_META, SPECIALISTS } from '../components/agents/agentMeta';
import { EnvironmentalMap, MapLegend, STATION_LABELS, stationLabel, stationReading, stationRisk } from '../components/map/EnvironmentalMap';
import { DashboardCard } from '../components/ui/DashboardCard';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { ProgressBar } from '../components/ui/primitives';
import { RiskBadge } from '../components/ui/RiskBadge';
import { useAnalysis } from '../context/AnalysisContext';
import { cn, pct } from '../lib/format';
import { RISK_STYLES } from '../lib/risk';
import type { SpecialistAgentId } from '../types/agents';

export function MapPage() {
  const { environment, environmentError, display, runAnalysis } = useAnalysis();
  const [layers, setLayers] = useState<Record<SpecialistAgentId, boolean>>({ air: true, water: true, waste: true });
  const [selected, setSelected] = useState<string | null>(null);

  if (environmentError) return <ErrorState error={environmentError} onRetry={() => void runAnalysis({ instant: true })} />;
  if (!environment) return <LoadingState variant="block" label="Loading monitoring network…" />;

  const stations = environment.stations.filter((station) => layers[station.type]);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <DashboardCard
        title={`${environment.location.name} monitoring network`}
        subtitle={`${environment.location.region} · ${environment.location.lat.toFixed(4)}°N, ${environment.location.lon.toFixed(4)}°E`}
        icon={MapIcon}
        iconColor="#60a5fa"
        className="self-start"
        actions={
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Map layers">
            <Layers className="mr-1 hidden size-3.5 text-fg-subtle sm:block" />
            {SPECIALISTS.map((type) => {
              const Icon = AGENT_META[type].icon;
              return (
                <button
                  key={type}
                  type="button"
                  aria-pressed={layers[type]}
                  onClick={() => setLayers((current) => ({ ...current, [type]: !current[type] }))}
                  className={cn(
                    'inline-flex h-7 items-center gap-1.5 rounded-lg border px-2 text-[11px] font-medium transition',
                    layers[type] ? 'border-white/15 bg-white/[0.07] text-fg' : 'border-white/[0.06] text-fg-subtle hover:text-fg-muted',
                  )}
                >
                  <Icon className="size-3.5" style={{ color: layers[type] ? AGENT_META[type].color : undefined }} />
                  <span className="hidden sm:inline">{AGENT_META[type].short.replace(' Agent', '')}</span>
                </button>
              );
            })}
          </div>
        }
      >
        <EnvironmentalMap snapshot={environment} results={display} layers={layers} selectedId={selected} onSelect={setSelected} />
        <MapLegend className="mt-4" />
      </DashboardCard>

      <div className="space-y-4">
        <DashboardCard title="Monitoring stations" subtitle={`${stations.length} of ${environment.stations.length} visible`} icon={RadioTower} iconColor="#2dd4bf">
          <ul className="-mx-2 space-y-0.5">
            {stations.map((station) => {
              const { level } = stationRisk(station, display);
              const meta = AGENT_META[station.type];
              const Icon = meta.icon;
              return (
                <li key={station.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(selected === station.id ? null : station.id)}
                    className={cn('flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition hover:bg-white/[0.04]', selected === station.id && 'bg-white/[0.06]')}
                  >
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ background: `${meta.color}14`, color: meta.color }}>
                      <Icon className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 text-[13px] font-medium text-fg">
                        <span className="truncate">{stationLabel(station, display)}</span>
                        {station.primary && <span className="rounded bg-brand/15 px-1 text-[9px] font-semibold tracking-wider text-brand uppercase">Primary</span>}
                      </span>
                      <span className="block truncate text-[11px] text-fg-subtle">
                        {STATION_LABELS[station.type]} · {stationReading(station, display)}
                      </span>
                    </span>
                    <RiskBadge level={level} />
                  </button>
                </li>
              );
            })}
            {stations.length === 0 && <li className="px-2 py-4 text-center text-xs text-fg-subtle">All layers hidden</li>}
          </ul>
        </DashboardCard>

        <DashboardCard title="Zone risk summary" subtitle="Derived from each agent’s latest report">
          <div className="space-y-3">
            {SPECIALISTS.map((type) => {
              const result = display[type];
              return (
                <div key={type}>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-fg-muted">{AGENT_META[type].name}</span>
                    {result ? <span className="font-semibold text-fg tabular">{pct(result.riskScore)}%</span> : <span className="text-fg-subtle">No report</span>}
                  </div>
                  <ProgressBar value={result?.riskScore ?? 0} color={result ? RISK_STYLES[result.riskLevel].color : undefined} height={4} className="mt-1.5" markers={[0.4, 0.7]} />
                </div>
              );
            })}
          </div>
        </DashboardCard>
      </div>
    </div>
  );
}
