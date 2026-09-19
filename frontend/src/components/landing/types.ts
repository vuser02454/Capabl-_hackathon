/** Narrow structural slice of the analysis context that the landing scene consumes. */
import type { AirAgentResult, CoordinatorResult, WasteAgentResult, WaterAgentResult } from '../../types/agents';

export interface AnalysisValueSlice {
  display: {
    air: AirAgentResult | null;
    water: WaterAgentResult | null;
    waste: WasteAgentResult | null;
    coordinator: CoordinatorResult | null;
  };
}

/** Zones the visitor can enter from the scene. */
export type Zone = 'air' | 'water' | 'waste';
export type EnterTarget = Zone | 'dashboard';
