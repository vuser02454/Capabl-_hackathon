/**
 * C3 Safety Intelligence contracts.
 *
 * `confidence` here is how well the REPORT supports the classification — driven by how much the
 * text actually states — not how certain a model feels. A two-line report naming nothing specific
 * scores low, and that low number is the useful signal: go read this one yourself.
 *
 * `narrativeSource` is `'llm'` when prose came from the language model and `'rules'` when it was
 * generated deterministically because the LLM was unavailable. The risk level and every count are
 * always deterministic, whichever value this holds.
 */

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';
export type NarrativeSource = 'llm' | 'rules';

/** One scored signal, with the phrase from the report that triggered it. */
export interface RiskContribution {
  factor: string;
  points: number;
  kind: 'hazard' | 'missing_control' | 'outcome' | 'recurrence';
  evidence: string | null;
}

export interface SafetyExtraction {
  summary: string | null;
  hazards: string[];
  riskFactors: string[];
  missingControls: string[];
  rootCause: string | null;
  contributingFactors: string[];
  severityIndicators: string[];
  /** `null` means the report does not say — never guessed. */
  injuryPresent: boolean | null;
  ppeIssue: boolean | null;
  environmentalCondition: string | null;
  confidence: number;
  narrativeSource: NarrativeSource;
}

export interface SafetyRiskAnalysis {
  riskLevel: RiskLevel;
  riskScore: number;
  confidence: number;
  reasoning: string[];
  criticalFactors: string[];
  contributions: RiskContribution[];
  /** Prior reports sharing this hazard AND location. Recurrence raises the score. */
  repeatHits: number;
  narrativeSource: NarrativeSource;
  ruleBasis: {
    highThreshold: number;
    mediumThreshold: number;
    forcedHigh: boolean;
    disclaimer: string;
  };
}

export interface SafetyRecommendations {
  priority: string;
  recommendedActions: string[];
  preventiveActions: string[];
  reasoning: string | null;
  humanReviewRequired: boolean;
  narrativeSource: NarrativeSource;
}

/** One agent hand-off, rendered in the Agent Execution panel. */
export interface AgentTraceStep {
  agent: string;
  status: 'ok' | 'skipped' | 'error';
  detail: string;
  payload: Record<string, unknown>;
}

export interface SafetyAnalysisResult {
  reportId: number | null;
  report: {
    reportText: string | null;
    source: string | null;
    location: string | null;
    department: string | null;
    equipment: string | null;
    incidentType: string | null;
  };
  extraction: SafetyExtraction;
  analysis: SafetyRiskAnalysis;
  recommendations: SafetyRecommendations;
  trace: AgentTraceStep[];
  disclaimer: string;
}

export interface CountedItem {
  name?: string;
  location?: string;
  department?: string;
  type?: string;
  cause?: string;
  count: number;
  percentage?: number;
  highRiskCount?: number;
  averageScore?: number;
}

export interface EmergingPattern {
  pattern: string;
  count: number | null;
  detail: string;
  evidence: string;
}

export interface RiskDistribution {
  LOW: number;
  MEDIUM: number;
  HIGH: number;
}

export interface SafetyOverview {
  totalReports: number;
  syntheticReports: number;
  userReports: number;
  riskDistribution: RiskDistribution;
  topHazards: CountedItem[];
  topRiskFactors: CountedItem[];
  highRiskLocations: CountedItem[];
  topDepartments: CountedItem[];
  recurringCauses: CountedItem[];
  incidentTypes: CountedItem[];
  emergingPatterns: EmergingPattern[];
  trendSummary: string;
  recentReports: SafetyReportRow[];
  llmAvailable: boolean;
  llmModel: string | null;
  syntheticNotice: string;
  disclaimer: string;
}

export interface SafetyPatterns {
  reportCount: number;
  riskDistribution: RiskDistribution;
  topHazards: CountedItem[];
  topRiskFactors: CountedItem[];
  highRiskLocations: CountedItem[];
  topDepartments: CountedItem[];
  recurringCauses: CountedItem[];
  incidentTypes: CountedItem[];
  emergingPatterns: EmergingPattern[];
  trendSummary: string;
  narrativeSource: NarrativeSource;
  syntheticNotice: string;
}

export interface SafetyReportRow {
  id: number;
  reportText: string;
  source: string;
  createdAt: string;
  location: string | null;
  department: string | null;
  incidentType: string | null;
  riskLevel: RiskLevel | null;
  riskScore: number | null;
  summary: string | null;
  hazards: string[];
  confidence: number | null;
}

export interface SafetyHealth {
  status: string;
  service: string;
  reportsStored: number;
  llmAvailable: boolean;
  llmModel: string | null;
  syntheticAvailable: number;
  disclaimer: string;
}

export interface WorkflowNode {
  id: string;
  agent: string;
  role: string;
}

/**
 * The C3 spec mandates LOW / MEDIUM / HIGH; the shared UI components predate it and use
 * LOW / MODERATE / HIGH. Adapt at the boundary rather than renaming the shared type, which would
 * ripple through the retained environmental pages and their tests for no benefit here.
 */
export function toDisplayRisk(level: RiskLevel): 'LOW' | 'MODERATE' | 'HIGH' {
  return level === 'MEDIUM' ? 'MODERATE' : level;
}


// --- Worker / Admin / geographic hotspots -----------------------------------------------------

export type LocationSource = 'browser_gps' | 'manual_map' | 'text_location' | 'unknown';
export type HotspotStatus =
  | 'PENDING_REVIEW' | 'ACKNOWLEDGED' | 'INVESTIGATING' | 'PUBLISHED' | 'RESOLVED' | 'DISMISSED';

export interface HotspotRule {
  minReports: number;
  radiusMeters: number;
  summary: string;
  disclaimer: string;
}

/** Everything a worker is permitted to see. Deliberately has no report ids or reviewer fields. */
export interface PublicAlert {
  id: number;
  title: string;
  message: string;
  severity: string;
  latitude: number | null;
  longitude: number | null;
  radiusMeters: number;
  locationText: string | null;
  publishedAt: string;
  issuedBy: string;
}

export interface SafetyHotspot {
  id: number;
  latitude: number;
  longitude: number;
  radiusMeters: number;
  reportCount: number;
  primaryHazard: string | null;
  relatedHazards: string[];
  riskLevel: RiskLevel;
  firstReportAt: string | null;
  latestReportAt: string | null;
  reportIds: number[];
  locations: string[];
  explanation: string | null;
  /** 'ai_detected' or 'admin_flagged' — the UI must never present these as the same thing. */
  flagSource: string;
  isAiDetected: boolean;
  status: HotspotStatus;
  reviewNotes: string | null;
  severity: string | null;
  reason: string | null;
}

export interface SupportingReport {
  id: number;
  reportText: string;
  location: string | null;
  createdAt: string;
  riskLevel: RiskLevel | null;
  hazards: string[];
  reasoning: string[];
}

export interface AdminMapData {
  reports: Array<{
    id: number; latitude: number; longitude: number; riskLevel: RiskLevel | null;
    hazards: string[]; location: string | null; createdAt: string; locationSource: string;
  }>;
  hotspots: SafetyHotspot[];
  alerts: PublicAlert[];
  rule: HotspotRule;
  syntheticNotice: string;
}

export interface WorkerSubmission extends SafetyAnalysisResult {
  location: {
    latitude: number | null; longitude: number | null; gpsAccuracy: number | null;
    locationSource: LocationSource; locationText: string | null;
  };
  hotspotRule: HotspotRule;
  candidateHotspotCount: number;
}

// --- Incident intelligence -----------------------------------------------------------------
//
// These mirror the backend's evidence blocks. Every field here is either counted from stored
// reports or read from OpenStreetMap; none of it is generated prose, which is why the UI is safe
// to render it verbatim.

export type IncidentDomain =
  | 'MEDICAL' | 'FIRE' | 'VIOLENCE_SECURITY' | 'ELECTRICAL' | 'CHEMICAL'
  | 'WILDLIFE' | 'EQUIPMENT' | 'GENERAL_SAFETY' | 'ENVIRONMENTAL' | 'OTHER';

export interface DomainTag {
  domain: IncidentDomain;
  label: string;
}

export interface AuthorityResult {
  name: string;
  address: string | null;
  /** Null when OpenStreetMap carries no number. Never a plausible substitute. */
  phone: string | null;
  /** True only when a contact number came from OSM data. */
  verified: boolean;
  distanceMeters: number;
  latitude: number;
  longitude: number;
  osmId: string;
  source: string;
}

export interface AuthorityLookup {
  available: boolean;
  authorityType: string | null;
  label?: string;
  results: AuthorityResult[];
  /** Why the lookup produced nothing. Shown verbatim rather than hidden. */
  reason?: string | null;
  source: string | null;
  radiusMeters?: number;
  cached?: boolean;
}

export interface SpecializedResponse {
  domain: IncidentDomain;
  label: string;
  authority: AuthorityLookup;
  nearest: AuthorityResult | null;
  evidenceReportIds?: number[];
  recommendation: string;
  disclaimer: string;
}

export interface SeriousIncident {
  reportId: number;
  markers: string[];
  evidence: string;
  riskLevel: RiskLevel | null;
  reportedAt: string | null;
  location: string | null;
  distanceMeters: number | null;
}

export interface IncidentHistory {
  radiusMeters: number;
  reportCount: number;
  riskBreakdown: { HIGH: number; MEDIUM: number; LOW: number };
  recurringHazards: Array<{ hazard: string; count: number }>;
  allHazards: Array<{ hazard: string; count: number }>;
  incidentTypes: Array<{ type: string; count: number }>;
  seriousIncidents: SeriousIncident[];
  seriousIncidentCount: number;
  firstReportAt: string | null;
  latestReportAt: string | null;
  reportIds: number[];
  previousRecommendations: Array<{ reportId: number; actions: string[]; reportedAt: string | null }>;
  unavailableReason?: string;
}

export interface ExplainableAssessment {
  statement: string;
  findings: string[];
  seriousHistory: SeriousIncident[];
  evidenceReportIds: number[];
  /** Always "stored reports" — the assessment cites the database, nothing else. */
  basis: string;
}

export interface AdminActionRow {
  id: number;
  hotspotId: number | null;
  reportId: number | null;
  actionTaken: string;
  label: string;
  authorityContacted: string | null;
  adminNotes: string | null;
  outcome: string | null;
  followUpRequired: number;
  recordedBy: string;
  actionTimestamp: string;
}

export interface FeedbackRow {
  id: number;
  hotspotId: number | null;
  useful: boolean;
  reason: string | null;
  comment: string | null;
  createdAt: string;
}

export interface HotspotDetail {
  hotspot: SafetyHotspot;
  supportingReports: SupportingReport[];
  rule: HotspotRule;
  incidentHistory: IncidentHistory;
  explanation: ExplainableAssessment;
  domain: DomainTag;
  authority: AuthorityLookup;
  specializedResponse: SpecializedResponse | null;
  adminActions: AdminActionRow[];
  feedback: FeedbackRow[];
}

export interface PhotoEvidence {
  hasPhoto: boolean;
  photoUrl: string | null;
  photoSource: string | null;
  photoCapturedAt: string | null;
  latitude: number | null;
  longitude: number | null;
  gpsAccuracy: number | null;
  locationSource: string | null;
  locationText: string | null;
  locationCapturedAt: string | null;
  geotagNote: string;
}

export interface AdminReportRow {
  id: number;
  reportText: string;
  location: string | null;
  locationText?: string | null;
  workerName?: string | null;
  employeeId?: string | null;
  createdAt: string;
  riskLevel: RiskLevel | null;
  hazards: string[];
  latitude: number | null;
  longitude: number | null;
  locationSource: string | null;
  photoPath: string | null;
}

export interface AdminReportDetail {
  pattern?: {
    level: number;
    status: string;
    summary: string;
    relatedReportIds?: number[];
    isPrecursor?: boolean;
    precursorNote?: string | null;
  } | null;
  report: AdminReportRow & Record<string, unknown>;
  analysis: Record<string, unknown>;
  evidence: PhotoEvidence;
  domain: DomainTag & { evidence: string | null; matchedText: string | null };
  incidentHistory: IncidentHistory | null;
  explanation: ExplainableAssessment | null;
  adminActions: AdminActionRow[];
  geographicRelationship?: Array<{
    reportId: number;
    location: string | null;
    distanceMeters: number | null;
    hazards: string[];
    createdAt?: string;
  }>;
  recommendations?: Record<string, unknown> | Array<string> | null;
}

export interface AdminDashboard {
  /** Worker safety activity, counted from stored route events. */
  workerCount?: number;
  workersReportingIncidents?: number;
  routeEventCount?: number;
  workersPassingModerateHazards?: number;
  workersReroutedFromHighHazards?: number;
  noSafeAlternativeEvents?: number;
  reportCount: number;
  geolocatedCount: number;
  photoCount: number;
  riskBreakdown: { HIGH: number; MEDIUM: number; LOW: number };
  hotspotCount: number;
  hotspotsByStatus: Record<string, number>;
  pendingReview: number;
  publishedAlertCount: number;
  recordedActionCount: number;
  domainBreakdown: Array<{ domain: IncidentDomain; label: string; count: number }>;
  rule: HotspotRule;
  domains: Array<{ domain: IncidentDomain; label: string; authority_type: string | null; specialised: boolean }>;
  syntheticNotice: string;
  disclaimer: string;
}

// --- Worker routing -------------------------------------------------------------------------
//
// Routing is computed by the backend: Dijkstra runs there, over a road graph built from
// OpenStreetMap way geometry. The frontend draws the result and never computes a path itself.
//
// The safety rule is CONDITIONAL. The shortest route is returned unchanged unless it actually
// enters the safety radius of a published alert; only then are alternatives generated. So there
// is one route in the response, plus a record of what the check found — not a menu of options.

export type RouteSelection = 'shortest' | 'alternative' | 'none_clear';

export type StartSource = 'browser_gps' | 'manual_map';
export type DestinationSource = 'text_search' | 'manual_map';

export interface RoutePoint {
  latitude: number;
  longitude: number;
}

/** A published alert whose safety radius the route enters. Only published alerts appear here. */
export interface RouteAlert {
  id: number;
  title: string;
  severity: string | null;
  latitude: number;
  longitude: number;
  radiusMeters: number;
  locationText: string | null;
  closestApproachMeters: number;
  /** The threshold actually applied — the route safety radius, or the alert's own if restricted. */
  safetyRadiusMeters: number;
  restricted: boolean;
}

/** A route that was computed, checked, and rejected because it was not clear. */
export interface RejectedRoute {
  distanceMeters: number;
  blockedBy: string[];
}

export interface RouteResponse {
  found: boolean;
  /** 'shortest' — nothing was in range. 'alternative' — a clear alternative replaced it.
   *  'none_clear' — every route evaluated was affected, and none may be called safe. */
  selected: RouteSelection | null;
  adjustedForSafety: boolean;
  route: RoutePoint[];
  nodePath?: number[];
  /** Real ground distance along the path — never a penalised cost. */
  distanceMeters: number | null;
  walkingSeconds?: number;
  /** Present only when an alternative replaced the shortest route. */
  shortestDistanceMeters?: number;
  alertsNearRoute: RouteAlert[];
  blockingAlerts: RouteAlert[];
  rejectedRoutes?: RejectedRoute[];
  alternativesEvaluated: number;
  /** Closest published alert to this route, or null when there are none to measure against. */
  nearestAlertMeters?: number | null;
  safetyRadiusMeters?: number;
  explanation: string;
  reason?: string;
  graph: {
    nodes: number;
    edges: number;
    startSnapMeters: number;
    destinationSnapMeters: number;
  };
  algorithm?: string;
  note: string;
}

// --- Worker identity and history ---------------------------------------------------------------
//
// `employeeId` is a handle, not a credential: this project has no login. The boundary that is
// real is server-side — a worker's queries are filtered to their own rows in SQL — so these
// types describe what a worker may see, not what protects it.

export interface WorkerProfile {
  id: number;
  employeeId: string;
  name: string;
  email: string | null;
  role: 'WORKER' | 'SAFETY_ADMIN';
  department: string | null;
  status: string;
  createdAt: string;
}

/** One of the worker's OWN reports. Carries no review state, reviewer or internal reasoning. */
export interface MyReport {
  id: number;
  reportText: string;
  createdAt: string;
  location: string | null;
  latitude: number | null;
  longitude: number | null;
  gpsAccuracy: number | null;
  locationSource: string | null;
  locationCapturedAt: string | null;
  riskLevel: RiskLevel | null;
  riskScore: number | null;
  summary: string | null;
  hazards: string[];
  status: string | null;
  hasPhoto: boolean;
  photoSource: string | null;
  photoCapturedAt: string | null;
  source: string | null;
}

export interface MyReportsResponse {
  worker: WorkerProfile;
  reports: MyReport[];
  count: number;
}

// --- Route history --------------------------------------------------------------------------
//
// A route event is created by an explicit route request and never by anything else. The stored
// geometry is historical evidence: it is what was served at the time, not a route recomputed
// later over today's map.

export type RouteClassification =
  | 'NORMAL_ROUTE' | 'MODERATE_HAZARD_PASSED' | 'HIGH_HAZARD_DETOUR' | 'NO_SAFE_ALTERNATIVE';

export interface RouteEventAlert {
  id: number | null;
  title: string | null;
  severity: string | null;
  latitude: number | null;
  longitude: number | null;
  radiusMeters: number | null;
  minimumDistanceMeters: number | null;
}

export interface RouteEvent {
  id: number;
  createdAt: string;
  start: RoutePoint;
  destination: RoutePoint;
  originalDistanceMeters: number | null;
  selectedDistanceMeters: number | null;
  detourDistanceMeters: number;
  detourRatio: number;
  routeAdjustedForSafety: boolean;
  safeAlternativeFound: boolean | null;
  selectedReason: string | null;
  classification: RouteClassification;
  classificationLabel: string;
  safetyRadiusMeters: number | null;
  originalRouteGeometry: RoutePoint[];
  selectedRouteGeometry: RoutePoint[];
  alert: RouteEventAlert | null;
  /** Admin-only. Absent from a worker's own route payload. */
  employeeId?: string;
  workerName?: string | null;
  department?: string | null;
  alertsNearRoute?: RouteAlert[];
}

export interface RouteSummary {
  total: number;
  byClassification: Array<{ classification: RouteClassification; label: string; count: number }>;
  normal: number;
  moderateHazard: number;
  highHazardDetour: number;
  noSafeAlternative: number;
  workersAffected: number;
  alertsInvolved: number;
  /** Route history begins when recording was introduced; this says so. */
  coverageNote: string;
}

export interface AdminRoutesResponse {
  routes: RouteEvent[];
  count: number;
  summary: RouteSummary;
  classifications: Array<{ id: RouteClassification; label: string }>;
  departments: string[];
}

// --- Safety chatbot -------------------------------------------------------------------------

export interface ChatEvidence {
  tool: string;
  result: Record<string, unknown>;
}

export interface SafetyChatResponse {
  answer: string;
  /** The answer composed with no model involved. Always present, so the phrasing can be checked. */
  deterministicAnswer?: string;
  answerSource?: 'deterministic' | 'llm_phrased';
  evidence: ChatEvidence[];
  tools: string[];
  grounded: boolean;
  refused: boolean;
  hint?: string;
  role: string;
  note: string;
}

// --- Notifications --------------------------------------------------------------------------
//
// One model, two directions. A worker's payload is a strict subset: sender, report id, GPS
// accuracy and the extracted risk factors are admin-side evidence about somebody's report, so
// the worker shape simply does not carry those fields.

export type NotificationType =
  | 'REPORT_SUBMITTED' | 'ANNOUNCEMENT' | 'DIRECT_MESSAGE' | 'SAFETY_ALERT';

export interface WorkerNotification {
  id: number;
  type: NotificationType;
  title: string;
  message: string;
  severity: string | null;
  createdAt: string;
  read: boolean;
  readAt: string | null;
  latitude: number | null;
  longitude: number | null;
  radiusMeters: number | null;
  expiresAt: string | null;
}

export interface AdminNotification extends WorkerNotification {
  senderEmployeeId: string | null;
  recipientEmployeeId: string | null;
  reportId: number | null;
  gpsAccuracy: number | null;
  locationSource: string | null;
  metadata: Record<string, unknown>;
}

export interface NotificationFeed<T> {
  notifications: T[];
  count: number;
  unreadCount: number;
  note?: string;
}
