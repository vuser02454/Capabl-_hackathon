/**
 * Water data provenance — describes WHERE a WaterAgentResult's readings came from, using only
 * fields the API already returns (WaterAgentResult.sourceType / isMock). Never infers a category
 * that isn't backed by the response itself.
 */
import type { WaterAgentResult, WaterSourceType } from '../types/agents';

export type DataModeTone = 'live' | 'historical' | 'demo';

export interface WaterSourceMeta {
  /** Short label for badges. */
  label: string;
  tone: DataModeTone;
  color: string;
  /** One-sentence explanation shown in provenance panels. */
  description: string;
  /** True only for a currently-reporting live sensor or station. */
  isLive: boolean;
}

export const WATER_SOURCE_META: Record<WaterSourceType, WaterSourceMeta> = {
  live_iot: {
    label: 'Live Sensor',
    tone: 'live',
    color: '#34d399',
    description: 'Reporting live from an EcoSentinel IoT water sensor.',
    isLive: true,
  },
  monitoring_station: {
    label: 'Monitoring Station',
    tone: 'live',
    color: '#34d399',
    description: 'Reporting live from a configured water monitoring station.',
    isLive: true,
  },
  historical: {
    label: 'Historical Dataset',
    tone: 'historical',
    color: '#f5b544',
    description: 'Latest available observation from a water-quality dataset — not a live sensor reading.',
    isLive: false,
  },
  demo: {
    label: 'Demo Data',
    tone: 'demo',
    color: '#60a5fa',
    description: 'Simulated EcoSentinel demo data, not a live measurement.',
    isLive: false,
  },
};

const FALLBACK_LIVE: WaterSourceMeta = {
  label: 'Live Data',
  tone: 'live',
  color: '#34d399',
  description: 'Live reading from the configured water provider.',
  isLive: true,
};

/**
 * Best-effort provenance for a WaterAgentResult. Falls back to isMock when the response doesn't
 * carry sourceType (e.g. the in-browser demo engine), rather than fabricating a specific source.
 */
export function waterProvenance(water: Pick<WaterAgentResult, 'sourceType' | 'isMock'>): WaterSourceMeta {
  if (water.sourceType) return WATER_SOURCE_META[water.sourceType];
  return water.isMock ? WATER_SOURCE_META.demo : FALLBACK_LIVE;
}
