/**
 * Structured agent contracts. These mirror backend/schemas.py exactly so the UI can
 * consume results from the in-browser demo engine or the FastAPI backend unchanged.
 *
 *   Data -> Specialist Agents (Air | Water | Waste) -> Coordinator -> Decision
 */

import type { GeographicContext } from './environment';

export type RiskLevel = 'LOW' | 'MODERATE' | 'HIGH';
export type SpecialistAgentId = 'air' | 'water' | 'waste';
export type AgentId = SpecialistAgentId | 'coordinator';
export type MeasurementStatus = 'normal' | 'elevated' | 'critical' | 'missing';
export type WasteCategory = 'plastic' | 'paper' | 'other';
/**
 * How current a reading is, as the PROVIDER reports it — never inferred by the UI.
 * Mirrors backend/schemas.py's DataFreshness.
 */
export type DataFreshness = 'live' | 'delayed' | 'demo';

export interface Measurement {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  threshold: number | null;
  thresholdLabel: string | null;
  subScore: number | null;
  status: MeasurementStatus;
}

export interface Finding {
  code: string;
  label: string;
  detail: string;
  impact: number;
}

export interface AgentResultBase {
  location: string;
  riskLevel: RiskLevel;
  riskScore: number;
  confidence: number;
  timestamp: string;
  dataSource: string;
  isMock: boolean;
  measurements: Measurement[];
  findings: Finding[];
  warnings: string[];
}

export interface AirAgentResult extends AgentResultBase {
  agent: 'air';
  stationId: string;
  stationName: string;
  pm25: number | null;
  pm10: number | null;
  no2: number | null;
  o3: number | null;
  aqi: number | null;
  aqiCategory: string | null;
  dominantPollutant: string | null;
  anomalies: string[];
  /** Set when readings come from a live provider such as OpenAQ. */
  stationDistanceKm?: number | null;
  referenceGrade?: boolean | null;
  sourceUrl?: string | null;
  /** pollutant key -> "Station name (distance)" */
  pollutantSources?: Record<string, string>;
  /** Age of the lead reading, as reported by the provider. */
  dataAgeMinutes?: number | null;
  /**
   * The provider's own verdict on the reading, never an assumption by the UI:
   * live = current observation, delayed = latest available but past the freshness window,
   * demo = fixture data. Backend-only (backend/schemas.py); the in-browser demo engine
   * does not set it.
   */
  freshness?: DataFreshness | null;
}

/**
 * live_iot / monitoring_station = a real sensor or station; historical = latest available
 * observation from a water-quality dataset (not a live reading); demo = simulated data.
 * Matches backend/schemas.py's WaterSourceType exactly.
 */
export type WaterSourceType = 'live_iot' | 'monitoring_station' | 'historical' | 'demo';

/**
 * Visual water-pollution detection (YOLO26), produced by the backend's Water Agent when an
 * image is supplied. This is a VISUAL signal only — it counts pollution objects visible in a
 * photograph. It does not measure pH, turbidity, dissolved oxygen or chemistry; those come
 * from the sensor/dataset readings in `measurements`.
 */
/**
 * What the system READS a raw detector class as. Kept beside `className`, never instead of it:
 * the detector says `bottle`, the interpretation says a bottle in water is visible litter.
 * A COCO `person` or `boat` is a real detection but is not pollution and must not be counted
 * as such. `unclassified_object` means no claim either way — which is not "clean".
 */
export type SemanticCategory =
  | 'visible_surface_litter'
  | 'non_pollution_object'
  | 'unclassified_object';

export interface VisionDetection {
  className: string;
  confidence: number;
  /** Pixel-space corners in the uploaded image's own coordinates. */
  bbox: { x1: number; y1: number; x2: number; y2: number };
  semanticCategory?: SemanticCategory;
}

export type WaterVisionStatus = 'ok' | 'not_run' | 'model_not_configured' | 'unavailable';

export interface WaterVisionReport {
  available: boolean;
  status: WaterVisionStatus;
  model: string | null;
  message: string | null;
  detections: VisionDetection[];
  /** Class name -> count, using whatever classes the trained model reports. ALL objects. */
  objectCounts: Record<string, number>;
  /** Every object the detector found, pollution or not. */
  totalObjects: number;
  /**
   * The litter subset — the only count that means "visible pollution", and the only one that
   * moves a risk score. Displaying `totalObjects` under a pollution heading is how two people
   * and four kites in a river photo were once reported as visible water pollution.
   */
  pollutionObjects?: number;
  /** Objects whose own class rules pollution out, so the frame is fully accounted for. */
  nonPollutionObjects?: number;
  /** Counts restricted to the litter subset. */
  pollutionCounts?: Record<string, number>;
  confidenceThreshold: number | null;
  visualScore: number | null;
  visualLevel: RiskLevel | null;
  annotatedImage: string | null;
}

export interface DatasetNeighbour {
  file: string;
  className: string;
  label: string;
  similarity: number;
}

export type DatasetMatchStatus = 'ok' | 'no_match' | 'not_run' | 'indexing' | 'index_missing' | 'unavailable';

/**
 * Appearance match against the labelled reference dataset (backend/services/water_dataset_match_service.py).
 *
 * `contaminated` means "resembles reference frames labelled contaminated" — NOT "this water is
 * contaminated". `caveat` carries the matcher's measured reliability and must be shown wherever
 * the flag is shown.
 */
export interface WaterDatasetMatch {
  status: DatasetMatchStatus;
  message: string | null;
  contaminated: boolean;
  matchedClass: string | null;
  matchedLabel: string | null;
  contaminationLevel: RiskLevel | null;
  similarity: number | null;
  voteShare: number | null;
  nearDuplicate: boolean;
  duplicateOf: string | null;
  neighbours: DatasetNeighbour[];
  datasetSize: number | null;
  matchThreshold: number | null;
  indexedAt: string | null;
  progress: number | null;
  caveat: string | null;
}

export interface DatasetIndexStatus {
  enabled: boolean;
  ready: boolean;
  building: boolean;
  datasetSize: number;
  classes: Record<string, number>;
  builtAt: string | null;
  progress: number | null;
  error: string | null;
  matchThreshold: number;
  flagLevels: string[];
}

/**
 * The location an analysis runs against, and how it was obtained.
 *
 * `source` is what the provenance strip shows the user: a browser fix and a typed search are
 * both legitimate, but they are not the same claim, so the UI never blurs them. Coordinates are
 * kept at full precision here for the analysis; only the display is rounded.
 */
export interface SelectedLocation {
  latitude: number;
  longitude: number;
  accuracy?: number | null;
  displayName: string;
  source: 'browser' | 'manual' | 'preset';
  /** How the display name was obtained, for the provenance strip. */
  geocoding: 'nominatim' | 'cached' | 'unresolved' | 'preset';
  city?: string | null;
  state?: string | null;
  country?: string | null;
}

/** Coordinates the browser resolved, plus whatever the reverse geocoder could name. */
export interface ReportLocation {
  latitude: number;
  longitude: number;
  accuracyM?: number | null;
  displayName?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  postcode?: string | null;
  neighbourhood?: string | null;
  waterFeature?: string | null;
  source: 'browser_geolocation' | 'preset';
  geocoding: 'nominatim' | 'cached' | 'unresolved' | 'preset';
}

export interface ContaminationReportRequest {
  location: ReportLocation;
  match: WaterDatasetMatch;
  observedAt: string;
  source: 'upload' | 'camera';
  note?: string | null;
  contact?: string | null;
  waterRiskLevel?: RiskLevel | null;
  waterRiskScore?: number | null;
  photo?: string | null;
}

export interface ContaminationReportReceipt {
  reference: string;
  /** `forwarded` only when a configured destination accepted it. `recorded` = stored here only. */
  status: 'recorded' | 'forwarded' | 'forward_failed';
  message: string;
  createdAt: string;
  stored: boolean;
  deliveredTo: string | null;
  summary: string;
}

export interface WaterAgentResult extends AgentResultBase {
  agent: 'water';
  sensorId: string;
  sensorName: string;
  sensorStatus: 'online' | 'degraded' | 'offline';
  ph: number | null;
  turbidity: number | null;
  temperature: number | null;
  /**
   * Fields below are only populated by the FastAPI backend (backend/schemas.py); the in-browser
   * demo engine (services/agents/waterAgent.ts) does not set them, so they must stay optional.
   */
  tds?: number | null;
  sourceType?: WaterSourceType;
  sourceName?: string | null;
  sensorDistanceKm?: number | null;
  dataAgeMinutes?: number | null;
  /** Only present on backend runs; the in-browser demo engine does not produce it. */
  visualPollution?: WaterVisionReport | null;
  /** Water-quality-only score, set when the visual signal escalated the combined risk. */
  waterQualityScore?: number | null;
  /**
   * Appearance match against the labelled reference dataset. Reporting-only: it deliberately does
   * NOT contribute to riskScore, because the matcher misreads clean water often enough that
   * letting it move a sensor-backed number would corrupt it.
   */
  datasetMatch?: WaterDatasetMatch | null;
  /** Clicked-frame explainable-AI report. Present only when a frame was investigated. */
  investigation?: FrameInvestigation | null;
}

export interface Detection {
  id: string;
  label: string;
  category: WasteCategory;
  confidence: number;
  /** x, y, width, height normalised to 0..1 */
  bbox: [number, number, number, number];
}

export interface WasteCounts {
  plastic: number;
  paper: number;
  other: number;
}

export interface WasteAgentResult extends AgentResultBase {
  agent: 'waste';
  sourceId: string;
  sourceName: string;
  inputType: 'camera' | 'upload';
  model: string;
  totalObjects: number;
  counts: WasteCounts;
  densityIndex: number;
  detections: Detection[];
}

export type SpecialistResult = AirAgentResult | WaterAgentResult | WasteAgentResult;

export interface SignalContribution {
  agent: SpecialistAgentId;
  riskLevel: RiskLevel;
  riskScore: number;
  weight: number;
  contribution: number;
}

export interface ContributingFactor {
  agent: SpecialistAgentId;
  label: string;
  detail: string;
}

export type RecommendationUrgency = 'Immediate' | 'Within 24h' | 'Routine';

export interface Recommendation {
  id: string;
  priority: number;
  title: string;
  explanation: string;
  agent: SpecialistAgentId | 'all';
  urgency: RecommendationUrgency;
  actionLabel: string;
}

export interface CoordinatorResult {
  agent: 'coordinator';
  location: string;
  overallRiskLevel: RiskLevel;
  overallScore: number;
  confidence: number;
  reasoning: string;
  crossSignalInsights: string[];
  contributingFactors: ContributingFactor[];
  contributions: SignalContribution[];
  crossSignalAdjustment: number;
  dominantAgents: SpecialistAgentId[];
  inputsReceived: SpecialistAgentId[];
  missingInputs: SpecialistAgentId[];
  recommendations: Recommendation[];
  timestamp: string;
  /**
   * Fields below are only produced by the FastAPI backend's Coordinator (backend/schemas.py);
   * they are optional here so the in-browser demo engine (services/agents/coordinatorAgent.ts)
   * doesn't need to populate them.
   */
  /** Freshness/mock/missing-agent caveats, derived deterministically from the specialist reports. */
  dataLimitations?: string[];
  /** True when every specialist agent failed/timed out — overallScore/confidence are 0, not a real LOW risk. */
  insufficientData?: boolean;
  /** Present only when LLM_PROVIDER is configured on the backend and the call succeeded. */
  llmNarrative?: string | null;
  llmEnhanced?: boolean;
}

export interface CoordinatorInput {
  location: string;
  air: AirAgentResult | null;
  water: WaterAgentResult | null;
  waste: WasteAgentResult | null;
}

export type AgentRunStatus = 'complete' | 'failed' | 'timeout';

export interface AgentRun {
  agent: AgentId;
  name: string;
  status: AgentRunStatus;
  durationMs: number;
  steps: string[];
  error: string | null;
}

/**
 * Decision-engine contracts — mirrors backend/schemas.py.
 *
 * Every field below is computed deterministically by the LangGraph decision engine
 * (backend/core/evidence.py, backend/core/decision.py). The optional LLM writes
 * `llmExplanation` and nothing else.
 */
export type EvidenceDomain = 'air' | 'water' | 'waste' | 'geographic';
export type EvidenceKind = 'measurement' | 'detection' | 'context' | 'derived';
/** Only ever set from a real baseline comparison; `unknown` where no history exists. */
export type EvidenceDirection = 'improving' | 'deteriorating' | 'stable' | 'unknown';
export type ProblemCategory = 'air' | 'water' | 'waste' | 'cross_signal' | 'unknown';
export type CausalStatus = 'observed' | 'supported_hypothesis' | 'unconfirmed';
export type OverallDirection = 'improving' | 'deteriorating' | 'mixed' | 'stable' | 'insufficient_history';

export interface EnvironmentalEvidence {
  evidenceId: string;
  domain: EvidenceDomain;
  kind: EvidenceKind;
  label: string;
  detail: string;
  value: number | null;
  unit: string | null;
  threshold: number | null;
  status: MeasurementStatus;
  severity: number;
  confidence: number;
  direction: EvidenceDirection;
  source: string;
  observedAt: string | null;
  isMock: boolean;
}

export interface EnvironmentalProblem {
  problemId: string;
  category: ProblemCategory;
  title: string;
  description: string;
  severity: RiskLevel;
  severityScore: number;
  confidence: number;
  /** severity x confidence x evidence strength x persistence — see core/decision.py. */
  priority: number;
  evidenceIds: string[];
  causalStatus: CausalStatus;
  affectedArea: string | null;
}

export interface CrossSignalFinding {
  findingId: string;
  title: string;
  detail: string;
  domains: EvidenceDomain[];
  evidenceIds: string[];
  /** Fixed. Co-occurrence is never presented as causation. */
  causality: 'not_established';
}

export interface EvidenceConflict {
  conflictId: string;
  detail: string;
  evidenceIds: string[];
}

export interface InvestigationAction {
  actionId: string;
  title: string;
  missingData: string;
  rationale: string;
  provider: string;
  priority: number;
}

export interface DecisionTraceStep {
  step: number;
  stage: string;
  detail: string;
  evidenceIds: string[];
}

export interface TriageDecision {
  domains: EvidenceDomain[];
  skipped: EvidenceDomain[];
  rationale: string[];
}

/**
 * One passage retrieved from the knowledge corpus.
 *
 * CONTEXT, NOT EVIDENCE. Retrieved knowledge explains what a measurement means; it is not a
 * measurement. It carries no severity and cannot move a risk score.
 *
 * `chunkId` is `<documentId>#<section-slug>` and resolves to an exact section of an exact file,
 * and `sourceFile` names the repository file the knowledge came from — so every citation shown
 * in the UI can be opened and checked.
 */
export interface RetrievedKnowledge {
  chunkId: string;
  documentId: string;
  documentTitle: string;
  section: string;
  domain: string;
  sourceFile: string | null;
  content: string;
  /** Cosine similarity, shown rather than hidden so a weak match reads as weak. */
  score: number;
  domainMatched: boolean;
  usedBy: string | null;
}

export interface KnowledgeRetrieval {
  status: 'ok' | 'not_run' | 'unavailable';
  /** Built deterministically from the evidence, never written by a language model. */
  query: string;
  results: RetrievedKnowledge[];
  embedding: string;
  documentsIndexed: number;
  chunksIndexed: number;
  minScore: number | null;
  message: string | null;
}

export interface EnvironmentalDecision {
  primaryProblem: EnvironmentalProblem | null;
  secondaryProblems: EnvironmentalProblem[];
  overallDirection: OverallDirection;
  /** Mirrors the deterministic Coordinator — the decision never recomputes risk. */
  riskLevel: RiskLevel;
  riskScore: number;
  confidence: number;
  sufficientEvidence: boolean;
  evidence: EnvironmentalEvidence[];
  crossSignalFindings: CrossSignalFinding[];
  conflicts: EvidenceConflict[];
  supportingEvidence: string[];
  contradictoryEvidence: string[];
  dataGaps: string[];
  investigationPlan: InvestigationAction[];
  decisionTrace: DecisionTraceStep[];
  triage: TriageDecision;
  /** Always present and always deterministic. */
  explanation: string;
  llmExplanation: string | null;
  llmEnhanced: boolean;
  explanationProvider?: string | null;
  dataStatus: 'live' | 'demo' | 'mixed' | 'none';
  /** Knowledge retrieved to ground the explanation. Context only. */
  knowledge?: KnowledgeRetrieval | null;
}

/**
 * Clicked-frame investigation — mirrors backend/schemas.py.
 *
 * Everything here comes from what the detector actually returned. Nothing in this contract can
 * carry a fabricated detection, reason, coordinate or date.
 */

/** How strongly the evidence backs a reason. The distinction is the whole point. */
export type ReasonType = 'OBSERVED' | 'INFERRED' | 'HYPOTHESIS' | 'UNKNOWN';

export interface FrameDetection {
  detectionId: string;
  /** Exactly what the trained model reported — never remapped. */
  className: string;
  confidence: number;
  /** Pixel-space corners as the detector returned them. */
  bbox: number[];
  /** Same box normalised to 0..1 of the frame, for overlaying at any display size. */
  bboxRelative: number[];
  /** Position WITHIN THE FRAME ("lower-left foreground") — never a real-world location. */
  imageRegion: string | null;
}

export interface InvestigationReason {
  reasonId: string;
  text: string;
  type: ReasonType;
  evidenceIds: string[];
  source: string | null;
  confidence: number | null;
  observedAt: string | null;
}

export interface FrameAction {
  actionId: string;
  action: string;
  rationale: string;
  priority: 'high' | 'medium' | 'low';
  expectedEffect: string;
  timeframe: string;
  timelineCategory: 'immediate' | 'short_term' | 'medium_term' | 'long_term';
  evidenceIds: string[];
}

/**
 * How the observed situation could get worse if nothing is done.
 * PROJECTIONS, not predictions — `basis` is fixed so none can be presented as an observation.
 */
export interface EscalationRisk {
  riskId: string;
  text: string;
  evidenceIds: string[];
  horizon: 'immediate' | 'short_term' | 'medium_term' | 'long_term';
  basis: 'projection';
}

export interface RecoveryTimeline {
  immediate: string;
  shortTerm: string;
  mediumTerm: string;
  longTerm: string;
  isEstimate: boolean;
  caveat: string;
  /** Set when no historical evidence supports any trend statement. */
  trendNote: string | null;
}

export interface InvestigationGeotag {
  available: boolean;
  latitude: number | null;
  longitude: number | null;
  accuracyMeters: number | null;
  capturedAt: string | null;
  source: 'browser' | 'manual' | 'preset' | null;
  resolvedName: string | null;
  message: string | null;
}

/** Which kinds of evidence an investigation actually has. */
export interface DataAvailability {
  visual: boolean;
  waterMeasurements: boolean;
  detail: string | null;
}

export interface FrameInvestigation {
  investigationId: string;
  dataAvailability: DataAvailability;
  summary: string;
  /** True only when the detector actually ran and returned boxes. */
  detectionsAvailable: boolean;
  detectionStatus: string;
  detectionMessage: string | null;
  model: string | null;
  imageWidth: number | null;
  imageHeight: number | null;
  detections: FrameDetection[];
  reasons: InvestigationReason[];
  actions: FrameAction[];
  /** How this could deteriorate if nothing is done. Projections, never predictions. */
  escalationRisks: EscalationRisk[];
  timeline: RecoveryTimeline;
  geotag: InvestigationGeotag;
  capturedAt: string | null;
  /** Plain-language reasoning about this frame, from the explainability provider. Additive only. */
  llmReasoning?: string | null;
  explanationProvider?: string | null;
}

/**
 * Real two-stage waste analysis (backend: POST /api/waste/segregate).
 *
 * `detectedObject` is the DETECTOR's class, exactly as reported. `classification` is the waste
 * class used for segregation: the detector's own class when that class is in the waste taxonomy,
 * otherwise the classifier's verdict on the crop.
 */
export interface WasteSegregationDetection {
  id: string;
  bbox: number[];
  detectedObject: string;
  detectionConfidence: number;
  classification: string | null;
  classificationConfidence: number | null;
  segregation: 'biodegradable' | 'non_biodegradable' | 'uncertain';
  status: 'confirmed' | 'needs_review' | 'unavailable';
  candidate?: string | null;
  handling?: string | null;
  display?: string | null;
  environmentalNote?: string | null;
  /** Other class names the detector gave the same region, absorbed as duplicates. */
  alsoDetectedAs?: string[] | null;
  /** Which stage produced `classification`: detector (TACO taxonomy class) or classifier. */
  labelSource?: 'detector' | 'classifier' | null;
  /**
   * Set when the localisation gate refused this box BEFORE any crop was classified. Such a box is
   * evidence about the detector, not a waste object, and must never be presented as one.
   */
  localisationRejected?: 'degenerate_box' | 'non_waste_object' | null;
  message?: string | null;
  /** Grad-CAM attribution, present only when requested with `explain`. */
  xai?: WasteXaiAttribution | null;
}

/**
 * Gradient attribution over the classifier's own prediction.
 *
 * `available: false` carries a reason and NO image. There is deliberately no fallback picture:
 * a heatmap that is not the model's gradients explains nothing, however convincing it looks.
 */
export interface WasteXaiAttribution {
  method: string;
  available: boolean;
  message?: string | null;
  targetClass?: string | null;
  targetConfidence?: number | null;
  layer?: string | null;
  /** Grid the attribution was computed on, e.g. "7x7" — not the display resolution. */
  attributionGrid?: string | null;
  overlayImage?: string | null;
}

export interface WasteSegregationResult {
  status: string;
  model: string | null;
  classifierAvailable: boolean;
  imageWidth: number | null;
  imageHeight: number | null;
  detections: WasteSegregationDetection[];
  summary: {
    totalObjects: number;
    biodegradable: number;
    nonBiodegradable: number;
    uncertain: number;
    /** Overlapping boxes folded into another object; `totalObjects` is the count after merging. */
    duplicateBoxesMerged: number;
    /** Detected objects whose class rules out waste entirely — a person, a car. */
    nonWasteObjects: number;
    /** Boxes the localisation gate refused before classification, for any reason. */
    localisationsRejected: number;
  };
  message: string | null;
}

/**
 * DIAGNOSTIC ONLY — one run of the waste pipeline with every intermediate stage exposed.
 *
 * Temporary, and intentionally shaped like the debug payload rather than like an API contract.
 * A wrong final label can originate in detection, cropping, preprocessing, classification or the
 * taxonomy lookup, and those are indistinguishable from the outside, so each is carried separately.
 */
export interface WasteDebugDetection {
  id: string;
  detector: { class: string; confidence: number; bbox: number[] };
  /** The raw argmax, BEFORE the confidence threshold and the non-waste gate. */
  classifier: {
    class: string | null;
    confidence: number | null;
    top5?: { class: string; confidence: number }[];
  };
  /** What the API actually returned, so a withheld answer is visible as a gate, not an error. */
  reported: {
    classification: string | null;
    classificationConfidence?: number | null;
    candidate?: string | null;
    segregation: string;
    status: string;
    message?: string | null;
  };
  taxonomy?: { lookedUp: string; category: string | null; handling: string | null; display: string | null };
  finalLabel: string | null;
  cropPath: string | null;
  /** The region cut from the image, before preprocessing. */
  cropImage?: string;
  /** The exact tensor the network consumed, with normalisation inverted. */
  modelInputImage?: string;
  modelInputPath?: string;
}

export interface WasteDebugRun {
  stem: string;
  sourceFile: string;
  generatedAt: string;
  rawDetections: number;
  originalImage?: string;
  detectorAnnotatedImage?: string;
  detections: WasteDebugDetection[];
  pipelineResult: WasteSegregationResult;
}

export interface AnalysisResult {
  analysisId: string;
  location: string;
  mode: 'demo' | 'live';
  startedAt: string;
  completedAt: string;
  air: AirAgentResult | null;
  water: WaterAgentResult | null;
  waste: WasteAgentResult | null;
  coordinator: CoordinatorResult;
  runs: AgentRun[];
  locationContext?: ReportLocation | null;
  /** Descriptive OSM enrichment. It never influenced `coordinator`. */
  geographicContext?: GeographicContext | null;
  /** The decision engine's output: what the evidence points to and what to investigate next. */
  decision?: EnvironmentalDecision | null;
}

export interface WasteImageAnalysis {
  waste: WasteAgentResult;
  coordinator: CoordinatorResult | null;
  runs: AgentRun[];
}
