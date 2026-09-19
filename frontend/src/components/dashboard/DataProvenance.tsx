/**
 * Where this analysis's numbers actually came from.
 *
 * The rule this panel exists to enforce: a source is listed only when it genuinely supplied data
 * for the run on screen, and every row states what KIND of data it is. "OpenAQ" and "a historical
 * dataset" and "demo fixtures" are three very different claims, and a dashboard that renders them
 * identically is lying by omission.
 *
 *   Current observation  — a live provider reading, recent enough for the provider to call current
 *   Delayed observation  — a real reading, but older than the freshness window
 *   Historical / ML      — a dataset-derived assessment, not a reading from this place right now
 *   Demo data            — fixtures, labelled as such
 *   Context only         — geography (Nominatim, Overpass); never a measurement
 *
 * The water dataset in particular is never presented as a live sensor: it has no coordinates for
 * this location and is not a measurement of this water.
 */
import { motion } from 'framer-motion';
import { Check, Info, MapPin } from 'lucide-react';
import type { AnalysisResult, SelectedLocation } from '../../types/agents';
import { DashboardCard } from '../ui/DashboardCard';

type SourceKind = 'live' | 'delayed' | 'historical' | 'demo' | 'context';

interface SourceRow {
  channel: string;
  provider: string;
  status: string;
  kind: SourceKind;
}

const KIND_STYLES: Record<SourceKind, string> = {
  live: 'text-risk-low',
  delayed: 'text-risk-moderate',
  historical: 'text-fg-muted',
  demo: 'text-fg-subtle',
  context: 'text-fg-muted',
};

/** How the user obtained the location — never blurred, because they are different claims. */
const SOURCE_LABEL: Record<SelectedLocation['source'], string> = {
  browser: 'Browser location',
  manual: 'Manual search',
  preset: 'Preset monitoring area',
};

const GEOCODER_LABEL: Record<SelectedLocation['geocoding'], string> = {
  nominatim: 'OpenStreetMap / Nominatim',
  cached: 'OpenStreetMap / Nominatim (cached)',
  unresolved: 'Name unresolved — coordinates only',
  preset: 'Bundled monitoring area',
};

function airRow(result: AnalysisResult): SourceRow | null {
  const air = result.air;
  if (!air) return null;
  if (air.isMock) {
    return { channel: 'Air', provider: air.dataSource, status: 'Demo data', kind: 'demo' };
  }
  // `freshness` is the provider's own verdict on the reading's age — not an assumption.
  const status =
    air.freshness === 'live'
      ? 'Current observation'
      : air.freshness === 'delayed'
        ? `Latest available observation${air.dataAgeMinutes ? ` (${Math.round(air.dataAgeMinutes / 60)} h old)` : ''}`
        : 'Observation';
  return { channel: 'Air', provider: air.dataSource, status, kind: air.freshness === 'live' ? 'live' : 'delayed' };
}

function waterRow(result: AnalysisResult): SourceRow | null {
  const water = result.water;
  if (!water) return null;
  if (water.isMock) {
    return { channel: 'Water', provider: water.dataSource, status: 'Demo data', kind: 'demo' };
  }
  switch (water.sourceType) {
    case 'live_iot':
      return { channel: 'Water', provider: water.dataSource, status: 'Live sensor reading', kind: 'live' };
    case 'monitoring_station':
      return { channel: 'Water', provider: water.dataSource, status: 'Monitoring station reading', kind: 'live' };
    case 'historical':
      // Explicitly NOT a sensor reading for this location.
      return {
        channel: 'Water',
        provider: water.dataSource,
        status: 'Historical / ML assessment',
        kind: 'historical',
      };
    default:
      return { channel: 'Water', provider: water.dataSource, status: 'Demo data', kind: 'demo' };
  }
}

function wasteRow(result: AnalysisResult): SourceRow | null {
  const waste = result.waste;
  if (!waste) return null;
  return {
    channel: 'Waste',
    provider: waste.dataSource,
    status: waste.isMock ? 'Demo data' : `${waste.model} detection`,
    kind: waste.isMock ? 'demo' : 'live',
  };
}

export function DataProvenance({ result, point }: { result: AnalysisResult | null; point: SelectedLocation | null }) {
  if (!result) return null;

  const rows: SourceRow[] = [airRow(result), waterRow(result), wasteRow(result)].filter(
    (row): row is SourceRow => row !== null,
  );

  // Geography is listed separately: it describes the place, it never measures it.
  if (point && point.geocoding !== 'unresolved') {
    rows.push({
      channel: 'Location',
      provider: GEOCODER_LABEL[point.geocoding],
      status: 'Context only',
      kind: 'context',
    });
  }
  const geo = result.geographicContext;
  if (geo?.available) {
    rows.push({
      channel: 'Geographic context',
      provider: geo.source,
      status: 'Mapped features — context only',
      kind: 'context',
    });
  }

  return (
    <DashboardCard bodyClassName="p-4 sm:p-5">
      <div className="space-y-4">
        <div className="flex items-start gap-2.5">
          <MapPin className="mt-0.5 size-4 shrink-0 text-brand" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-fg">{point?.displayName ?? result.location}</p>
            <p className="text-[11px] text-fg-subtle">
              {point ? SOURCE_LABEL[point.source] : 'Preset monitoring area'}
              {point && (
                <>
                  {' · '}
                  {/* Four decimals ≈ 11 m: enough to show which point ran, without implying the
                      UI knows the user's doorstep. The backend keeps full precision. */}
                  <span className="tabular">
                    {point.latitude.toFixed(4)}, {point.longitude.toFixed(4)}
                  </span>
                  {point.accuracy != null && ` · ±${Math.round(point.accuracy)} m`}
                </>
              )}
            </p>
          </div>
        </div>

        <div>
          <p className="eyebrow mb-2">Environmental data sources</p>
          <ul className="space-y-1.5">
            {rows.map((row, index) => (
              <motion.li
                key={`${row.channel}-${row.provider}`}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className="flex items-baseline gap-2 text-xs"
              >
                <Check className={`size-3 shrink-0 translate-y-0.5 ${KIND_STYLES[row.kind]}`} />
                <span className="w-32 shrink-0 text-fg-muted">{row.channel}</span>
                <span className="min-w-0 flex-1 truncate text-fg">{row.provider}</span>
                <span className={`shrink-0 text-[10.5px] ${KIND_STYLES[row.kind]}`}>{row.status}</span>
              </motion.li>
            ))}
          </ul>
        </div>

        {geo && !geo.available && geo.message && (
          <p className="flex items-start gap-1.5 text-[11px] text-fg-subtle">
            <Info className="mt-px size-3 shrink-0" />
            <span>{geo.message}</span>
          </p>
        )}

        {geo?.available && (
          <p className="flex items-start gap-1.5 text-[11px] text-fg-subtle">
            <Info className="mt-px size-3 shrink-0" />
            {/* Wording matters: mapped features are context, never an attributed cause. */}
            <span>
              {describeContext(geo)} Mapped features describe what is around this location; they are not
              measurements and did not affect the risk score.
            </span>
          </p>
        )}
      </div>
    </DashboardCard>
  );
}

/** One neutral sentence about what OSM has mapped nearby. Never asserts a cause. */
function describeContext(geo: NonNullable<AnalysisResult['geographicContext']>): string {
  const parts: string[] = [];
  if (geo.industrialFeatures.length) parts.push(`${geo.industrialFeatures.length} industrial`);
  if (geo.wasteFacilities.length) parts.push(`${geo.wasteFacilities.length} waste`);
  if (geo.waterways.length) parts.push(`${geo.waterways.length} waterway`);
  if (geo.roads.length) parts.push(`${geo.roads.length} major-road`);
  if (!parts.length) return '';
  const radius = geo.radiusM ? ` within ${geo.radiusM} m` : '';
  return `${parts.join(', ')} features are mapped near the analysis location${radius}.`;
}
