/**
 * Landing-page environment model.
 *
 * The cinematic scene is only ever a *view* of real agent output: every readout below is
 * either a value the specialist agents actually produced, or `null` (rendered as "Awaiting
 * analysis"). Nothing here invents a measurement to make the hero look busier.
 */
import type { AnalysisValueSlice } from './types';
import { SIGNAL_COLORS } from './scrollStory';
import type { RiskLevel, SpecialistAgentId } from '../../types/agents';

/** A single line inside a hotspot card: label + value, or `null` when the agent has no reading. */
export interface Readout {
  label: string;
  value: string | null;
  tone?: 'default' | 'risk';
}

export interface HotspotData {
  id: SpecialistAgentId;
  /** Short tag revealed on hover, e.g. "AIR QUALITY". */
  tag: string;
  title: string;
  subtitle: string;
  color: string;
  readouts: Readout[];
  riskLevel: RiskLevel | null;
  /** True when the backing agent report is simulated demo data rather than a live reading. */
  isMock: boolean;
  /** Extra provenance note, e.g. "Image-based detection". */
  note: string | null;
  /** False until the agent has produced a report. */
  hasData: boolean;
}

const fmt = (value: number | null | undefined, decimals: number, unit = ''): string | null =>
  value === null || value === undefined || Number.isNaN(value) ? null : `${value.toFixed(decimals)}${unit}`;

export function buildHotspots(analysis: AnalysisValueSlice): Record<SpecialistAgentId, HotspotData> {
  const { air, water, waste } = analysis.display;

  return {
    air: {
      id: 'air',
      tag: 'Air quality',
      title: 'Air Agent',
      subtitle: 'Air Quality Intelligence',
      color: SIGNAL_COLORS.air,
      riskLevel: air?.riskLevel ?? null,
      isMock: air?.isMock ?? false,
      note: air?.stationName ? `Station · ${air.stationName}` : null,
      hasData: Boolean(air),
      readouts: [
        { label: 'AQI', value: air?.aqi != null ? String(air.aqi) : null },
        { label: 'PM2.5', value: fmt(air?.pm25, 1, ' μg/m³') },
        { label: 'Risk', value: air?.riskLevel ?? null, tone: 'risk' },
      ],
    },
    water: {
      id: 'water',
      tag: 'Water quality',
      title: 'Water Agent',
      subtitle: 'Water Quality Intelligence',
      color: SIGNAL_COLORS.water,
      riskLevel: water?.riskLevel ?? null,
      isMock: water?.isMock ?? false,
      note: water?.sensorName ? `Sensor · ${water.sensorName}` : null,
      hasData: Boolean(water),
      readouts: [
        { label: 'pH', value: fmt(water?.ph, 1) },
        { label: 'Turbidity', value: fmt(water?.turbidity, 1, ' NTU') },
        { label: 'Sensor', value: water?.sensorStatus ? water.sensorStatus.toUpperCase() : null },
        { label: 'Risk', value: water?.riskLevel ?? null, tone: 'risk' },
      ],
    },
    waste: {
      id: 'waste',
      tag: 'Waste detection',
      title: 'Waste Detection',
      subtitle: 'Visual Environmental Intelligence',
      color: SIGNAL_COLORS.waste,
      riskLevel: waste?.riskLevel ?? null,
      isMock: waste?.isMock ?? false,
      note: waste ? `${waste.inputType === 'upload' ? 'Uploaded image' : 'Camera frame'} · ${waste.model}` : null,
      hasData: Boolean(waste),
      readouts: [
        { label: 'Objects', value: waste ? String(waste.totalObjects) : null },
        { label: 'Plastic', value: waste ? String(waste.counts.plastic) : null },
        { label: 'Paper', value: waste ? String(waste.counts.paper) : null },
        { label: 'Risk', value: waste?.riskLevel ?? null, tone: 'risk' },
      ],
    },
  };
}
