import type { AgentId, SpecialistAgentId } from './agents';

export interface LocationInfo {
  id: string;
  name: string;
  region: string;
  lat: number;
  lon: number;
}

export interface MapStation {
  id: string;
  type: SpecialistAgentId;
  label: string;
  x: number;
  y: number;
  primary?: boolean;
  riskFactor?: number;
}

export interface WaterBody {
  x: number;
  y: number;
  rx: number;
  ry: number;
}

export type TrendRange = '24h' | '7d' | '30d';

export interface TrendPoint {
  hoursAgo: number;
  timestamp: string;
  pm25: number | null;
  turbidity: number | null;
  wasteCount: number;
}

export interface EnvironmentSnapshot {
  location: LocationInfo;
  stations: MapStation[];
  waterBodies: WaterBody[];
  history: Record<TrendRange, TrendPoint[]>;
}

/** Reverse-geocoded place name for a coordinate pair (backend: POST /api/location/reverse). */
export interface GeocodeResult {
  displayName: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  postcode: string | null;
  neighbourhood: string | null;
  waterFeature: string | null;
  cached: boolean;
}

/** One forward-geocoding candidate (backend: POST /api/location/search). */
export interface PlaceMatch {
  displayName: string;
  latitude: number;
  longitude: number;
  category: string | null;
  placeType: string | null;
  importance: number | null;
  /** True when the match is itself a water feature — a lake, river, reservoir and so on. */
  isWater: boolean;
}

export interface PlaceSearchResponse {
  query: string;
  matches: PlaceMatch[];
  cached: boolean;
}

/**
 * One OpenStreetMap water feature near a point (backend: POST /api/water/nearby-bodies).
 * Geography only — Overpass carries no water-quality data.
 */
export interface NearbyWaterBody {
  osmId: string;
  name: string | null;
  /** Raw OSM tag value, e.g. "lake", "drain". */
  kind: string;
  /** Human label for `kind`, e.g. "Lake", "Storm drain". */
  label: string;
  /** True for waterways that flow (river, stream, canal) rather than standing water. */
  flowing: boolean;
  latitude: number;
  longitude: number;
  distanceKm: number;
}

export interface NearbyWaterResponse {
  status: 'ok' | 'disabled' | 'unavailable';
  message: string | null;
  bodies: NearbyWaterBody[];
  /** Closest NAMED body, chosen before the result limit truncates — cite this in a report. */
  nearestNamed: NearbyWaterBody | null;
  radiusM: number | null;
  cached: boolean;
}

/**
 * One mapped OpenStreetMap feature near the analysis point (backend: POST /api/location/context).
 *
 * CONTEXT ONLY. A mapped feature is a polygon a contributor drew — never a measurement, an
 * emission, or evidence that anything is polluting. Describe it as "industrial activity is
 * mapped near this location", never as a cause of an observed reading.
 */
export interface GeographicFeature {
  osmId: string;
  name: string | null;
  category: 'industrial' | 'waste' | 'waterway' | 'road';
  /** Raw OSM tag value, e.g. "landfill". */
  kind: string;
  /** Human label for `kind`, e.g. "Landfill". */
  label: string;
  latitude: number;
  longitude: number;
  distanceKm: number;
}

/**
 * Optional geographic enrichment for one analysis. Never contributes to a risk score and never
 * reaches the Coordinator — `available: false` carries the reason instead of an error.
 */
export interface GeographicContext {
  available: boolean;
  source: string;
  status: 'ok' | 'disabled' | 'unavailable' | 'skipped';
  message: string | null;
  industrialFeatures: GeographicFeature[];
  wasteFacilities: GeographicFeature[];
  waterways: GeographicFeature[];
  roads: GeographicFeature[];
  radiusM: number | null;
  cached: boolean;
}

/**
 * AI role health (backend: GET /api/ai/status). Never carries a key.
 *
 * The two roles are reported separately because they are not interchangeable — see
 * backend/services/ai/functional.py and backend/services/ai/explainability.py.
 */
/** The live camera's entire output: is there visible contamination, yes or no. */
export interface FrameScanVerdict {
  status: 'ok' | 'not_run' | 'model_not_configured' | 'unavailable';
  /** True only for pollution-relevant classes — a person by the water is not a finding. */
  contaminated: boolean;
  objectCount: number;
  otherObjectCount: number;
  classes: string[];
  model: string | null;
  message: string | null;
}

export interface AiRoleStatus {
  provider: string;
  configured: boolean;
  available: boolean;
  model: string | null;
  detail: string | null;
}

export interface AiStatusResponse {
  /** Gemini: performs AI work whose validated output enters as evidence. */
  functionalAi: AiRoleStatus;
  /** OpenRouter or Groq: explains an already-final decision. Cannot change it. */
  explainableAi: AiRoleStatus;
  /** YOLO: locates objects in an image. Neither LLM may substitute for it. */
  vision?: AiRoleStatus;
}

/** A question about one specific analysis (backend: POST /api/chat). */
export interface ChatRequest {
  analysisId: string;
  question: string;
}

/**
 * One tool the chat agent ran, as the UI shows it.
 *
 * Deliberately shallow — tool name, why it ran, whether it worked, one line of result. No prompt
 * and no model reasoning: those are not verifiable by a reader, whereas "this tool ran and
 * returned this" is.
 */
export interface ChatToolExecution {
  tool: string;
  purpose: string;
  status: 'ok' | 'failed';
  durationMs: number;
  summary: string;
  error: string | null;
}

/** A retrieved passage backing an answer. Always a real chunk from the real retriever. */
export interface ChatCitation {
  chunkId: string;
  documentTitle: string;
  section: string;
  sourceFile: string | null;
  score: number;
  content: string;
}

export interface ChatResponse {
  analysisId: string;
  question: string;
  answer: string;
  /** Evidence the answer rests on, so any claim can be checked against the decision. */
  evidenceIds: string[];
  /** "deterministic" when no explainability provider ran, else the provider name. */
  source: string;
  llmEnhanced: boolean;
  /**
   * How the message was routed:
   *   analysis   — answered from the held decision state
   *   functional — a tool ran and its result is authoritative
   *   general    — the secondary LLM answered a non-analysis question
   *   unavailable— no provider could serve it, and the answer says so
   */
  intent: 'analysis' | 'functional' | 'general' | 'unavailable';
  toolExecutions: ChatToolExecution[];
  citations: ChatCitation[];
}

export interface AgentStatusInfo {
  id: AgentId;
  name: string;
  status: 'operational' | 'degraded' | 'offline';
  provider: string;
  lastRunAt: string | null;
  lastDurationMs: number | null;
}

export interface AgentsStatusResponse {
  operational: boolean;
  summary: string;
  agents: AgentStatusInfo[];
}
