import metadataJson from '@shared/pollutant_metadata.json';

export interface SourceCategory {
  category: string;
  description: string;
  icon?: string;
  is_contextual?: boolean;
}

export interface GuidelineEntry {
  averaging_period: string;
  value: number;
  unit: string;
  label: string;
}

export interface PollutantDetail {
  key: string;
  code: string;
  name: string;
  unit: string;
  description: string;
  is_secondary_pollutant: boolean;
  source_type: 'direct' | 'secondary' | 'direct_and_secondary';
  secondary_formation: string | null;
  precursor_pollutants: string[];
  health_effects: string[];
  vulnerable_groups: string[];
  primary_sources: SourceCategory[];
  guideline_references: {
    who_2021: GuidelineEntry[];
    cpcb_naaqs: GuidelineEntry[];
  };
}

export interface AuthoritativeSource {
  code: string;
  name: string;
  publisher: string;
  type: string;
  note: string;
}

export interface PollutantRegistry {
  version: string;
  disclaimer: string;
  authoritative_sources: AuthoritativeSource[];
  pollutants: Record<string, PollutantDetail>;
}

export const POLLUTANT_REGISTRY: PollutantRegistry = metadataJson as PollutantRegistry;
export const HEALTH_DISCLAIMER: string = POLLUTANT_REGISTRY.disclaimer;
export const POLLUTANTS: Record<string, PollutantDetail> = POLLUTANT_REGISTRY.pollutants;

export function getPollutantMetadata(key: string): PollutantDetail | undefined {
  return POLLUTANTS[key.toLowerCase()];
}
