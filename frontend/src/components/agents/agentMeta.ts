import { Droplets, Network, Recycle, Wind, type LucideIcon } from 'lucide-react';
import type { RouteId } from '../../lib/routes';
import type { AgentId, SpecialistAgentId, WasteCategory } from '../../types/agents';

export interface AgentSpec {
  input: string[];
  tools: string[];
  processing: string[];
  output: string[];
}

export interface AgentMeta {
  id: AgentId;
  name: string;
  short: string;
  icon: LucideIcon;
  color: string;
  route: RouteId;
  role: string;
  spec: AgentSpec;
}

export const SPECIALISTS: SpecialistAgentId[] = ['air', 'water', 'waste'];

export const AGENT_META: Record<AgentId, AgentMeta> = {
  air: {
    id: 'air',
    name: 'Air Quality Agent',
    short: 'Air Agent',
    icon: Wind,
    color: '#0284c7',
    route: 'air',
    role: 'Retrieves the nearest station’s pollutant readings, normalizes them against WHO guidelines, computes an India NAQI and flags spikes against the 24-hour baseline.',
    spec: {
      input: ['Location'],
      tools: ['Air quality data source', 'OpenAQ-compatible'],
      processing: ['Data normalization', 'Risk calculation', 'Anomaly detection'],
      output: ['Air risk report'],
    },
  },
  water: {
    id: 'water',
    // Visual pollution detection is the primary experience; IoT telemetry is no longer the story
    // this agent tells, even where the sensor/dataset provider chain still runs behind it.
    name: 'Water Pollution Agent',
    short: 'Water Agent',
    icon: Droplets,
    color: '#4f46e5',
    route: 'water',
    role: 'Detects visible pollution in water imagery, then explains what was found: where it is in the frame, why it matters, and what to investigate next. An image supports statements about visible pollution only — never about chemical contamination.',
    spec: {
      input: ['Camera frame / photo'],
      tools: ['YOLO26 visual detection', 'Explainable AI layer'],
      processing: ['Object localization', 'Evidence typing', 'Recovery planning'],
      output: ['Frame investigation report'],
    },
  },
  waste: {
    id: 'waste',
    name: 'Waste Detection Agent',
    short: 'Waste Agent',
    icon: Recycle,
    color: '#9333ea',
    route: 'waste',
    role: 'Runs object detection on camera frames or uploaded images, classifies litter into plastic, paper and other, and estimates litter density.',
    spec: {
      input: ['Image / video'],
      tools: ['Object detector', 'YOLO-compatible'],
      processing: ['Object detection', 'Waste classification', 'Density estimation'],
      output: ['Waste risk report'],
    },
  },
  coordinator: {
    id: 'coordinator',
    name: 'Coordinator Agent',
    short: 'Coordinator',
    icon: Network,
    color: '#0d9488',
    route: 'coordinator',
    role: 'Consumes only the three specialist reports — never raw data — then reasons across signals, aggregates risk and prioritizes actions.',
    spec: {
      input: ['All three agent reports'],
      tools: ['Cross-signal rules', 'Weighted aggregation'],
      processing: ['Cross-signal reasoning', 'Risk aggregation', 'Priority identification'],
      output: ['Overall environmental risk', 'Reasons', 'Recommended actions'],
    },
  },
};

export const WASTE_CATEGORY_COLORS: Record<WasteCategory, string> = {
  plastic: '#9333ea',
  paper: '#0284c7',
  other: '#64748b',
};
