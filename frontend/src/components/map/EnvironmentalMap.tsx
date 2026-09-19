import { AnimatePresence, motion } from 'framer-motion';
import { ArrowUpRight, Map as MapIcon, MapPin, Navigation2 } from 'lucide-react';
import { useState } from 'react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useNavigation } from '../../context/NavigationContext';
import { cn } from '../../lib/format';
import { clamp, RISK_STYLES, riskLevelFor } from '../../lib/risk';
import type { AirAgentResult, RiskLevel, SpecialistAgentId, WasteAgentResult, WaterAgentResult } from '../../types/agents';
import type { EnvironmentSnapshot, MapStation } from '../../types/environment';
import { AGENT_META, SPECIALISTS } from '../agents/agentMeta';
import { Button } from '../ui/Button';
import { DashboardCard } from '../ui/DashboardCard';
import { ErrorState } from '../ui/ErrorState';
import { RiskBadge } from '../ui/RiskBadge';

export interface MapResults {
  air: AirAgentResult | null;
  water: WaterAgentResult | null;
  waste: WasteAgentResult | null;
}

export const STATION_LABELS: Record<SpecialistAgentId, string> = {
  air: 'Air Station',
  water: 'Water Sensor',
  waste: 'Waste Observation',
};

const VIEW_HEIGHT = 62.5; // viewBox 100 x 62.5 matches the 16:10 container
const Y_SCALE = VIEW_HEIGHT / 100;

const CITY_OUTLINE =
  'M21 13 C27 9 34 7 41 6.2 C49 5.4 57 5.8 64 7.6 C72 9.6 79 13 84.5 18.5 C89 23.5 91 30 89.5 37 C88 44 83.5 50 76.5 54 C69 57.6 60.5 58.8 52 58.8 C43 58.8 34.5 57.5 27.5 53.6 C20.5 49.7 14.8 43.6 12.4 36 C10.2 28.6 14.6 17.6 21 13 Z';

const ROADS = [
  'M3 31 C22 29 38 33.5 50 31.2 S80 28.6 97 32',
  'M49.5 1 C48.6 14 52 22 50 31.2 S48.4 49 51.2 61.5',
  'M13 6 C27 16 40 24.5 50 31.2 S75 45.5 91 58',
  'M89 5 C74 15 61.5 23.8 50 31.2 S24 47.5 8 57.5',
  'M28 60 C34 48 41 40 50 31.2',
];

export function stationRisk(station: MapStation, results: MapResults): { score: number | null; level: RiskLevel | null } {
  const result = results[station.type];
  if (!result) return { score: null, level: null };
  const score = clamp(result.riskScore * (station.riskFactor ?? 1));
  return { score, level: riskLevelFor(score) };
}

/** The primary air station shows the live station name when readings come from OpenAQ. */
export function stationLabel(station: MapStation, results: MapResults): string {
  const air = results.air;
  return station.type === 'air' && station.primary && air && !air.isMock ? air.stationName : station.label;
}

export function stationReading(station: MapStation, results: MapResults): string {
  const factor = station.riskFactor ?? 1;
  if (station.type === 'air') {
    const pm25 = results.air?.pm25;
    return pm25 === null || pm25 === undefined ? 'No data' : `PM2.5 ${Math.round(pm25 * factor)} µg/m³`;
  }
  if (station.type === 'water') {
    const water = results.water;
    if (!water) return 'No data';
    return water.turbidity === null ? `pH ${water.ph ?? '—'}` : `${(water.turbidity * factor).toFixed(1)} NTU`;
  }
  return results.waste ? `${Math.round(results.waste.totalObjects * factor)} objects` : 'No data';
}

interface EnvironmentalMapProps {
  snapshot: EnvironmentSnapshot;
  results: MapResults;
  layers?: Record<SpecialistAgentId, boolean>;
  selectedId?: string | null;
  onSelect?: (id: string | null) => void;
  compact?: boolean;
  className?: string;
}

export function EnvironmentalMap({ snapshot, results, layers, selectedId = null, onSelect, compact = false, className }: EnvironmentalMapProps) {
  const [hovered, setHovered] = useState<string | null>(null);
  const active = hovered ?? selectedId;
  const stations = snapshot.stations.filter((station) => layers?.[station.type] ?? true);

  return (
    <div className={cn('relative w-full overflow-hidden rounded-xl border border-black/[0.06] bg-[#070a0d]', className)} style={{ aspectRatio: '16 / 10' }}>
      <svg viewBox={`0 0 100 ${VIEW_HEIGHT}`} className="absolute inset-0 size-full" preserveAspectRatio="xMidYMid meet" aria-hidden>
        <defs>
          <radialGradient id="map-glow" cx="50%" cy="50%" r="60%">
            <stop offset="0" stopColor="#2563eb" stopOpacity="0.08" />
            <stop offset="1" stopColor="#2563eb" stopOpacity="0" />
          </radialGradient>
          <pattern id="map-grid-minor" width="2.5" height="2.5" patternUnits="userSpaceOnUse">
            <path d="M2.5 0H0V2.5" fill="none" stroke="rgb(15 23 42 / 0.03)" strokeWidth="0.1" />
          </pattern>
          <pattern id="map-grid-major" width="12.5" height="12.5" patternUnits="userSpaceOnUse">
            <path d="M12.5 0H0V12.5" fill="none" stroke="rgb(15 23 42 / 0.065)" strokeWidth="0.12" />
          </pattern>
          {(['LOW', 'MODERATE', 'HIGH'] as RiskLevel[]).map((level) => (
            <radialGradient key={level} id={`map-zone-${level}`}>
              <stop offset="0" stopColor={RISK_STYLES[level].color} stopOpacity="0.42" />
              <stop offset="0.55" stopColor={RISK_STYLES[level].color} stopOpacity="0.13" />
              <stop offset="1" stopColor={RISK_STYLES[level].color} stopOpacity="0" />
            </radialGradient>
          ))}
        </defs>

        <rect width="100" height={VIEW_HEIGHT} fill="url(#map-grid-minor)" />
        <rect width="100" height={VIEW_HEIGHT} fill="url(#map-grid-major)" />
        <rect width="100" height={VIEW_HEIGHT} fill="url(#map-glow)" />

        <path d={CITY_OUTLINE} fill="rgb(45 212 191 / 0.03)" stroke="rgb(45 212 191 / 0.3)" strokeWidth="0.22" strokeDasharray="1 0.7" />
        <ellipse cx="50" cy="31.2" rx="23" ry="14.5" fill="none" stroke="rgb(15 23 42 / 0.06)" strokeWidth="0.55" />
        <g fill="none" stroke="rgb(15 23 42 / 0.075)" strokeWidth="0.38" strokeLinecap="round">
          {ROADS.map((d) => (
            <path key={d} d={d} />
          ))}
        </g>

        {snapshot.waterBodies.map((body, index) => (
          <ellipse
            key={index}
            cx={body.x}
            cy={body.y * Y_SCALE}
            rx={body.rx}
            ry={body.ry * Y_SCALE}
            fill="rgb(96 165 250 / 0.14)"
            stroke="rgb(96 165 250 / 0.35)"
            strokeWidth="0.15"
          />
        ))}

        {stations
          .filter((station) => station.primary)
          .map((station) => {
            const { score, level } = stationRisk(station, results);
            if (score === null || !level) return null;
            const radius = 5 + score * 9;
            return (
              <g key={`zone-${station.id}`}>
                <motion.circle
                  cx={station.x}
                  cy={station.y * Y_SCALE}
                  r={radius}
                  fill={`url(#map-zone-${level})`}
                  initial={{ opacity: 0, scale: 0.6 }}
                  animate={{ opacity: 1, scale: [1, 1.08, 1] }}
                  transition={{ opacity: { duration: 0.6 }, scale: { duration: 4, repeat: Infinity, ease: 'easeInOut' } }}
                  style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
                />
                <circle cx={station.x} cy={station.y * Y_SCALE} r={radius} fill="none" stroke={RISK_STYLES[level].color} strokeOpacity="0.28" strokeWidth="0.15" strokeDasharray="0.8 0.8" />
              </g>
            );
          })}
      </svg>

      <div className="pointer-events-none absolute top-1/2 left-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border border-brand/60">
        <span className="absolute inset-[3px] rounded-full bg-brand" />
      </div>

      {stations.map((station) => {
        const { level } = stationRisk(station, results);
        const meta = AGENT_META[station.type];
        const Icon = meta.icon;
        const ringColor = level ? RISK_STYLES[level].color : '#838d97';
        const isActive = active === station.id;
        const below = station.y < 34;
        const label = stationLabel(station, results);
        return (
          <div
            key={station.id}
            className="absolute -translate-x-1/2 -translate-y-1/2"
            style={{ left: `${station.x}%`, top: `${station.y}%`, zIndex: isActive ? 30 : station.primary ? 20 : 10 }}
          >
            <button
              type="button"
              onMouseEnter={() => setHovered(station.id)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(station.id)}
              onBlur={() => setHovered(null)}
              onClick={() => onSelect?.(selectedId === station.id ? null : station.id)}
              aria-label={`${label} ${STATION_LABELS[station.type]}${level ? `, ${level} risk` : ''}`}
              className="group relative grid place-items-center rounded-full focus-visible:ring-2 focus-visible:ring-brand/60 focus-visible:outline-none"
            >
              {station.primary && <span className="absolute size-7 animate-pulse-ring rounded-full" style={{ background: `${ringColor}45` }} />}
              <span
                className={cn(
                  'relative grid place-items-center rounded-full border-2 bg-ink-950 transition-transform duration-200 group-hover:scale-110',
                  station.primary ? 'size-7' : 'size-5',
                  isActive && 'scale-110',
                )}
                style={{ borderColor: ringColor, boxShadow: `0 0 14px ${ringColor}55` }}
              >
                <Icon className={station.primary ? 'size-3.5' : 'size-2.5'} style={{ color: meta.color }} />
              </span>
              {(!compact || station.primary) && (
                <span className="pointer-events-none absolute top-full mt-1 max-w-36 truncate rounded bg-ink-950/75 px-1 text-[9.5px] whitespace-nowrap text-fg-muted">{label}</span>
              )}
            </button>

            <AnimatePresence>
              {isActive && (
                <motion.div
                  initial={{ opacity: 0, y: below ? -4 : 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className={cn(
                    'pointer-events-none absolute left-1/2 w-48 -translate-x-1/2 rounded-lg border border-black/10 bg-ink-850/95 p-2.5 shadow-2xl backdrop-blur',
                    below ? 'top-full mt-6' : 'bottom-full mb-3',
                  )}
                >
                  <p className="text-[10px] font-semibold tracking-wider uppercase" style={{ color: meta.color }}>
                    {STATION_LABELS[station.type]}
                  </p>
                  <p className="text-xs font-medium text-fg">{label}</p>
                  <p className="font-mono text-[10px] text-fg-subtle">{station.id}</p>
                  <div className="mt-1.5 flex items-center justify-between gap-2">
                    <RiskBadge level={level} />
                    <span className="text-[10.5px] text-fg-muted">{stationReading(station, results)}</span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}

      <div className="absolute top-3 left-3 flex items-center gap-1.5 rounded-md border border-black/10 bg-ink-950/75 px-2 py-1 text-[11px] backdrop-blur">
        <MapPin className="size-3.5 text-brand" />
        <span className="font-medium text-fg">{snapshot.location.name}</span>
        {!compact && (
          <span className="hidden text-fg-subtle sm:inline">
            {snapshot.location.lat.toFixed(2)}°N {snapshot.location.lon.toFixed(2)}°E
          </span>
        )}
      </div>

      {!compact && (
        <div className="absolute top-3 right-3 flex flex-col items-center rounded-full border border-black/10 bg-ink-950/75 p-1.5 backdrop-blur" aria-hidden>
          <span className="text-[8px] leading-none font-semibold text-fg-subtle">N</span>
          <Navigation2 className="size-3.5 text-fg-muted" />
        </div>
      )}

      <div className="absolute bottom-3 left-3 flex flex-col gap-1 text-[9.5px] text-fg-subtle" aria-hidden>
        <div className="flex h-1.5 w-20 overflow-hidden rounded-sm border border-black/20">
          <span className="flex-1 bg-black/30" />
          <span className="flex-1" />
          <span className="flex-1 bg-black/30" />
          <span className="flex-1" />
        </div>
        <span>0 — 5 km</span>
      </div>
    </div>
  );
}

export function MapLegend({ className }: { className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-center gap-x-6 gap-y-2 text-[11px] text-fg-muted', className)}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="eyebrow">Risk</span>
        {(['LOW', 'MODERATE', 'HIGH'] as RiskLevel[]).map((level) => (
          <span key={level} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: RISK_STYLES[level].color, boxShadow: `0 0 8px ${RISK_STYLES[level].color}88` }} />
            {level}
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <span className="eyebrow">Stations</span>
        {SPECIALISTS.map((type) => {
          const Icon = AGENT_META[type].icon;
          return (
            <span key={type} className="inline-flex items-center gap-1.5">
              <Icon className="size-3.5" style={{ color: AGENT_META[type].color }} />
              {STATION_LABELS[type]}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export function MapCard({ className }: { className?: string }) {
  const { environment, environmentError, display, runAnalysis } = useAnalysis();
  const { navigate } = useNavigation();

  return (
    <DashboardCard
      title="Environmental Map"
      subtitle={environment ? `${environment.location.name} · ${environment.stations.length} monitoring stations` : 'Loading monitoring network…'}
      icon={MapIcon}
      iconColor="#2563eb"
      className={className}
      actions={
        <Button size="sm" variant="ghost" iconRight={ArrowUpRight} onClick={() => navigate('map')}>
          Expand
        </Button>
      }
    >
      {environmentError ? (
        <ErrorState compact error={environmentError} onRetry={() => void runAnalysis({ instant: true })} />
      ) : environment ? (
        <>
          <EnvironmentalMap snapshot={environment} results={display} compact />
          <MapLegend className="mt-4" />
          <ul className="mt-4 space-y-2 border-t border-black/[0.05] pt-4">
            {environment.stations
              .filter((station) => station.primary)
              .map((station) => {
                const { level } = stationRisk(station, display);
                const meta = AGENT_META[station.type];
                return (
                  <li key={station.id} className="flex items-center gap-3 text-xs">
                    <meta.icon className="size-3.5 shrink-0" style={{ color: meta.color }} />
                    <span className="min-w-0 flex-1 truncate text-fg-muted">
                      {stationLabel(station, display)} <span className="text-fg-subtle">· {STATION_LABELS[station.type]}</span>
                    </span>
                    <span className="hidden text-fg-subtle tabular sm:inline">{stationReading(station, display)}</span>
                    <RiskBadge level={level} />
                  </li>
                );
              })}
          </ul>
        </>
      ) : (
        <div className="skeleton aspect-[16/10] w-full rounded-xl" />
      )}
    </DashboardCard>
  );
}
