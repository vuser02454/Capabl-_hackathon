import type {
  AnalysisResult,
  ContaminationReportReceipt,
  ContaminationReportRequest,
  DatasetIndexStatus,
  SelectedLocation,
  WasteImageAnalysis,
  WasteSegregationResult,
  WasteDebugRun,
  WaterAgentResult,
  WaterDatasetMatch,
} from '../types/agents';
import type {
  AdminActionRow,
  AdminDashboard,
  AdminMapData,
  AdminReportDetail,
  AdminReportRow,
  HotspotDetail,
  AdminNotification,
  AdminRoutesResponse,
  NotificationFeed,
  WorkerNotification,
  MyReportsResponse,
  RouteEvent,
  RouteSummary,
  SafetyChatResponse,
  PublicAlert,
  WorkerProfile,
  RouteResponse,
  SafetyAnalysisResult,
  SafetyHotspot,

  WorkerSubmission,
  SafetyHealth,
  SafetyOverview,
  SafetyPatterns,
  SafetyReportRow,
  WorkflowNode,
} from '../types/safety';
import type {
  AiStatusResponse,
  ChatResponse,
  FrameScanVerdict,
  GeocodeResult,
  GeographicContext,
  NearbyWaterResponse,
  PlaceSearchResponse,
} from '../types/environment';
import type { AgentsStatusResponse, EnvironmentSnapshot } from '../types/environment';
import { AppError, isKnownCode } from './errors';

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  demoMode: boolean;
  providers: Record<string, string>;
  timestamp: string;
}

const abortError = () => new DOMException('Aborted', 'AbortError');

/** Thin FastAPI client. Every failure is converted into a user-friendly AppError. */
export class ApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.trim().replace(/\/+$/, '');
  }

  health(signal?: AbortSignal) {
    return this.request<HealthResponse>('/api/health', {}, 5000, signal);
  }

  environment(location: string, signal?: AbortSignal) {
    return this.request<EnvironmentSnapshot>(`/api/environment/${encodeURIComponent(location)}`, {}, 10000, signal);
  }

  /**
   * Run the full agent pipeline.
   *
   * When the user has picked a real point — a browser fix or a Nominatim search result — the
   * coordinates are what the analysis must run against, so they are sent as `locationContext`
   * and the backend's own LocationContext contract is preserved unchanged. `location` alone
   * still works for the preset monitoring areas, which is the pre-existing contract.
   */
  analyze(location: string, selected?: SelectedLocation | null, signal?: AbortSignal) {
    const body = selected
      ? { locationContext: toLocationContext(selected), demoMode: false }
      : { location, demoMode: false };
    return this.request<AnalysisResult>(
      '/api/analyze',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      30000, // live providers (OpenAQ) add network round-trips
      signal,
    );
  }

  analyzeWaste(file: File, location: string, signal?: AbortSignal) {
    const form = new FormData();
    form.append('file', file);
    form.append('location', location);
    form.append('demo_mode', 'false');
    form.append('reassess', 'true');
    return this.request<WasteImageAnalysis>('/api/waste/analyze', { method: 'POST', body: form }, 35000, signal);
  }

  /**
   * Water Agent run with a water photo attached. The sensor half of the report is produced by the
   * usual provider chain; the image only adds the `visualPollution` block, so this never fails
   * just because the vision model is unconfigured.
   */
  analyzeWaterImage(file: File, location: string, signal?: AbortSignal) {
    const form = new FormData();
    form.append('file', file);
    form.append('location', location);
    form.append('demo_mode', 'false');
    return this.request<WaterAgentResult>('/api/water/analyze-image', { method: 'POST', body: form }, 45000, signal);
  }

  /**
   * Investigate one captured frame: WHERE the visible pollution is, WHY it matters, WHAT next.
   *
   * Uses the existing water image endpoint with `investigate=true` rather than a second one, so
   * there is a single image-analysis path. The geotag is optional provenance — omit it (denied
   * permission, no GPS) and the visual investigation still runs in full.
   */
  investigateFrame(
    file: File | Blob,
    location: string,
    geotag?: { latitude: number; longitude: number; accuracy?: number | null; source?: string },
    signal?: AbortSignal,
    selected?: SelectedLocation | null,
    demoMode = false,
  ) {
    const form = new FormData();
    form.append('file', file, file instanceof File ? file.name : 'frame.jpg');
    // A picked point is sent as coordinates, never as its display name. Nominatim names like
    // "Bellandur Lake Road, Yemaluru, …" are not preset ids, so sending one as `location` made the
    // backend reject the whole investigation with 404 INVALID_LOCATION before any analysis ran.
    if (selected) form.append('location_context', JSON.stringify(toLocationContext(selected)));
    else form.append('location', location);
    form.append('demo_mode', String(demoMode));
    form.append('investigate', 'true');
    if (geotag) {
      form.append('latitude', String(geotag.latitude));
      form.append('longitude', String(geotag.longitude));
      if (geotag.accuracy != null) form.append('accuracy_meters', String(geotag.accuracy));
      if (geotag.source) form.append('location_source', geotag.source);
    }
    return this.request<WaterAgentResult>('/api/water/analyze-image', { method: 'POST', body: form }, 60000, signal);
  }

  /**
   * Real two-stage waste analysis: YOLO detection, then the trained classifier on each crop.
   *
   * This is the honest path for the Waste page. The demo waste provider generates random boxes
   * from a seeded RNG and never looks at the image, so anything it produces is a placeholder —
   * this endpoint reports what a model actually found, including nothing.
   */
  /**
   * DIAGNOSTIC ONLY. Every intermediate stage of one waste analysis.
   *
   * Returns raw model internals — full probability vectors and the de-normalised tensor the
   * network actually consumed — so a wrong label can be traced to the stage that produced it.
   * Deliberately loosely typed: this is not an API contract and should not become one.
   */
  debugWaste(file: File | Blob, signal?: AbortSignal) {
    const form = new FormData();
    form.append('file', file, file instanceof File ? file.name : 'waste.jpg');
    return this.request<WasteDebugRun>('/api/waste/debug', { method: 'POST', body: form }, 90000, signal);
  }

  /**
   * `explain` adds a Grad-CAM attribution per classified crop. It costs a backward pass per
   * object, so it is opt-in rather than on by default.
   */
  // --- Worker ----------------------------------------------------------------------------------

  /** Submit a worker report. Location is optional at every level — GPS denial must not block it. */
  submitWorkerReport(
    body: {
      reportText: string; latitude?: number | null; longitude?: number | null;
      gpsAccuracy?: number | null; locationSource?: string; locationText?: string | null;
      locationCapturedAt?: string | null; employeeId?: string | null;
    },
    signal?: AbortSignal,
  ) {
    const payload: Record<string, unknown> = {
      report_text: body.reportText,
      latitude: body.latitude ?? null,
      longitude: body.longitude ?? null,
      gps_accuracy: body.gpsAccuracy ?? null,
      location_source: body.locationSource ?? 'unknown',
      location_text: body.locationText ?? null,
      location_captured_at: body.locationCapturedAt ?? null,
    };
    if (body.employeeId) {
      payload.employee_id = body.employeeId;
    }
    return this.request<WorkerSubmission>('/api/worker/reports', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }, 90000, signal);
  }

  /** Attach a photo to a report that is already filed.
   *
   * A second request on purpose: the report text is the thing that matters, and a camera or
   * upload failure must not take the report down with it. */
  attachReportPhoto(reportId: number, file: File, capturedAt?: string, signal?: AbortSignal) {
    const form = new FormData();
    form.append('file', file);
    form.append('photo_source', 'live_camera');
    if (capturedAt) form.append('captured_at', capturedAt);
    return this.request<{ reportId: number; photoSource: string; photoUrl: string }>(
      `/api/worker/reports/${reportId}/photo`, { method: 'POST', body: form }, 60000, signal);
  }

  /** Ask the backend for a walking route. Dijkstra runs server-side over an OSM road graph.
   *
   * There is no mode to choose: the backend returns the shortest route unless it enters a
   * published alert's safety radius, and only then looks for an alternative. */
  workerRoute(body: {
    start: { latitude: number; longitude: number };
    destination: { latitude: number; longitude: number };
    safetyRadiusMeters?: number;
  }, signal?: AbortSignal) {
    return this.request<RouteResponse>('/api/worker/route', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start: body.start, destination: body.destination,
        ...(body.safetyRadiusMeters != null
          ? { safety_radius_meters: body.safetyRadiusMeters } : {}),
      }),
    }, 90000, signal);
  }

  /** The worker's own profile. `employeeId` identifies whose records to return; it is not a
   *  credential, and the backend says so in the response. */
  workerMe(employeeId: string, signal?: AbortSignal) {
    return this.request<{ worker: WorkerProfile; reportCount: number;
                          locationEventCount: number; note: string }>(
      `/api/worker/me?employee_id=${encodeURIComponent(employeeId)}`, {}, 20000, signal);
  }

  /** The worker's own report history. The backend filters to their rows in SQL. */
  myReports(employeeId: string, signal?: AbortSignal) {
    return this.request<MyReportsResponse>(
      `/api/worker/reports?employee_id=${encodeURIComponent(employeeId)}`, {}, 30000, signal);
  }

  /** Is this coordinate in India? Used for a GPS fix and for a tapped map point — the two
   *  sources that Nominatim's search filter has not already checked. */
  verifyLocationInIndia(latitude: number, longitude: number, signal?: AbortSignal) {
    return this.request<{
      accepted: boolean; verified: boolean; countryCode: string | null;
      reason: string | null; place: string | null; method: string;
    }>('/api/worker/verify-location', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latitude, longitude }),
    }, 20000, signal);
  }

  /** Cautions and published alerts near a point. Cautions never affect routing. */
  workerCautions(latitude: number, longitude: number, signal?: AbortSignal) {
    return this.request<{
      alerts: PublicAlert[];
      cautions: Array<{ area: string; hazard: string; message: string; severity: string }>;
      radiusMeters: number; priority: string; note: string;
    }>(`/api/worker/cautions?latitude=${latitude}&longitude=${longitude}`, {}, 20000, signal);
  }

  /** This worker's own recorded routes. Filtered by employee_id in SQL on the server. */
  workerRoutes(employeeId: string, signal?: AbortSignal) {
    return this.request<{ routes: RouteEvent[]; count: number; note: string }>(
      `/api/worker/routes?employee_id=${encodeURIComponent(employeeId)}`, {}, 30000, signal);
  }

  adminRoutes(filters: {
    employeeId?: string; classification?: string; alertId?: number;
    department?: string; since?: string; until?: string;
  } = {}, signal?: AbortSignal) {
    const query = new URLSearchParams();
    if (filters.employeeId) query.set('employee_id', filters.employeeId);
    if (filters.classification) query.set('classification', filters.classification);
    if (filters.alertId != null) query.set('alert_id', String(filters.alertId));
    if (filters.department) query.set('department', filters.department);
    if (filters.since) query.set('since', filters.since);
    if (filters.until) query.set('until', filters.until);
    const suffix = query.toString() ? `?${query}` : '';
    return this.request<AdminRoutesResponse>(`/api/admin/routes${suffix}`, {}, 30000, signal);
  }

  adminWorkerRoutes(employeeId: string, signal?: AbortSignal) {
    return this.request<{ worker: WorkerProfile; routes: RouteEvent[]; count: number;
                          summary: RouteSummary }>(
      `/api/admin/workers/${encodeURIComponent(employeeId)}/routes`, {}, 30000, signal);
  }

  adminAlertAffectedWorkers(alertId: number, signal?: AbortSignal) {
    return this.request<{ alertId: number; count: number; evidence: string; coverageNote: string;
                          workers: Array<Record<string, unknown>> }>(
      `/api/admin/alerts/${alertId}/affected-workers`, {}, 30000, signal);
  }

  adminAlertReroutedWorkers(alertId: number, signal?: AbortSignal) {
    return this.request<{ alertId: number; count: number; coverageNote: string;
                          workers: Array<Record<string, unknown>> }>(
      `/api/admin/alerts/${alertId}/rerouted-workers`, {}, 30000, signal);
  }

  /** Ask the grounded safety assistant. It reads the database through fixed read-only tools. */
  safetyChat(body: {
    question: string; role: 'admin' | 'worker'; employeeId?: string;
    context?: Record<string, unknown>;
  }, signal?: AbortSignal) {
    return this.request<SafetyChatResponse>('/api/safety/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: body.question, role: body.role,
        employee_id: body.employeeId ?? null, context: body.context ?? null,
      }),
    }, 60000, signal);
  }

  // --- Notifications ---------------------------------------------------------------------

  adminNotifications(unreadOnly = false, signal?: AbortSignal) {
    return this.request<NotificationFeed<AdminNotification>>(
      `/api/admin/notifications?unread_only=${unreadOnly}`, {}, 20000, signal);
  }

  adminMarkNotificationRead(id: number, signal?: AbortSignal) {
    return this.request<{ unreadCount: number }>(
      `/api/admin/notifications/${id}/read`, { method: 'POST' }, 20000, signal);
  }

  adminMarkAllNotificationsRead(signal?: AbortSignal) {
    return this.request<{ marked: number; unreadCount: number }>(
      '/api/admin/notifications/read-all', { method: 'POST' }, 20000, signal);
  }

  /** Broadcast to every worker, or target named workers. Not a published alert — no routing effect. */
  adminSendNotification(body: {
    title: string; message: string; severity?: string; employeeIds?: string[];
    latitude?: number | null; longitude?: number | null; radiusMeters?: number | null;
  }, signal?: AbortSignal) {
    return this.request<{ ids: number[]; count: number; delivery: string; note: string }>(
      '/api/admin/notifications/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: body.title, message: body.message, severity: body.severity ?? 'MEDIUM',
          employee_ids: body.employeeIds ?? null,
          latitude: body.latitude ?? null, longitude: body.longitude ?? null,
          radius_meters: body.radiusMeters ?? null,
        }),
      }, 20000, signal);
  }

  workerNotifications(employeeId: string, unreadOnly = false, signal?: AbortSignal) {
    return this.request<NotificationFeed<WorkerNotification>>(
      `/api/worker/notifications?employee_id=${encodeURIComponent(employeeId)}&unread_only=${unreadOnly}`,
      {}, 20000, signal);
  }

  workerMarkNotificationRead(employeeId: string, id: number, signal?: AbortSignal) {
    return this.request<{ unreadCount: number }>(
      `/api/worker/notifications/${id}/read?employee_id=${encodeURIComponent(employeeId)}`,
      { method: 'POST' }, 20000, signal);
  }

  workerAlerts(signal?: AbortSignal) {
    return this.request<{ alerts: PublicAlert[]; count: number }>('/api/worker/alerts', {}, 20000, signal);
  }

  workerMap(signal?: AbortSignal) {
    return this.request<{ alerts: PublicAlert[]; note: string }>('/api/worker/map', {}, 20000, signal);
  }

  // --- Admin -----------------------------------------------------------------------------------

  adminMap(signal?: AbortSignal) {
    return this.request<AdminMapData>('/api/admin/map', {}, 30000, signal);
  }

  adminHotspots(signal?: AbortSignal) {
    return this.request<{ hotspots: SafetyHotspot[]; count: number }>('/api/admin/hotspots', {}, 20000, signal);
  }

  adminHotspotDetail(id: number, signal?: AbortSignal) {
    return this.request<HotspotDetail>(`/api/admin/hotspots/${id}`, {}, 30000, signal);
  }

  adminHotspotAction(id: number, action: string, notes?: string, signal?: AbortSignal) {
    return this.request<{ hotspot: SafetyHotspot; status: string }>(
      `/api/admin/hotspots/${id}/${action}`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: notes ?? null }) },
      20000, signal);
  }

  adminFlagHotspot(body: {
    latitude: number;
    longitude: number;
    reason: string;
    severity?: string;
    radius_meters?: number;
    location_text?: string | null;
  }, signal?: AbortSignal) {
    return this.request<{ hotspot: SafetyHotspot; flagSource: string }>(
      '/api/admin/hotspots/flag',
      { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body) },
      20000, signal);
  }

  /** Absolute URL for a backend-served asset, for use in an <img src>.
   *
   * Photos are fetched by the browser directly rather than through `request`, so they need the
   * same base URL that `request` prepends. Returned as a plain string so an <img> can use it. */
  absoluteUrl(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  adminAnnouncements(signal?: AbortSignal) {
    return this.request<{ announcements: Array<Record<string, unknown>>; count: number }>(
      '/api/admin/announcements', {}, 20000, signal);
  }

  adminDashboard(signal?: AbortSignal) {
    return this.request<AdminDashboard>('/api/admin/dashboard', {}, 30000, signal);
  }

  adminReports(limit = 200, signal?: AbortSignal) {
    return this.request<{ reports: AdminReportRow[]; count: number }>(
      `/api/admin/reports?limit=${limit}`, {}, 30000, signal);
  }

  adminReportDetail(id: number, signal?: AbortSignal) {
    return this.request<AdminReportDetail>(`/api/admin/reports/${id}`, {}, 30000, signal);
  }

  adminRecordAction(body: {
    actionTaken: string; hotspotId?: number | null; reportId?: number | null;
    authorityContacted?: string | null; adminNotes?: string | null;
    outcome?: string | null; followUpRequired?: boolean;
  }, signal?: AbortSignal) {
    return this.request<{ id: number; label: string; note: string }>('/api/admin/actions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action_taken: body.actionTaken, hotspot_id: body.hotspotId ?? null,
        report_id: body.reportId ?? null, authority_contacted: body.authorityContacted ?? null,
        admin_notes: body.adminNotes ?? null, outcome: body.outcome ?? null,
        follow_up_required: body.followUpRequired ?? false,
      }),
    }, 20000, signal);
  }

  adminActions(hotspotId?: number, signal?: AbortSignal) {
    const query = hotspotId != null ? `?hotspot_id=${hotspotId}` : '';
    return this.request<{ actions: AdminActionRow[]; count: number;
                          available: Array<{ id: string; label: string }> }>(
      `/api/admin/actions${query}`, {}, 20000, signal);
  }

  adminRecordFeedback(body: {
    useful: boolean; hotspotId?: number | null; reportId?: number | null;
    reason?: string | null; comment?: string | null;
  }, signal?: AbortSignal) {
    return this.request<{ id: number; note: string }>('/api/admin/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        useful: body.useful, hotspot_id: body.hotspotId ?? null,
        report_id: body.reportId ?? null, reason: body.reason ?? null,
        comment: body.comment ?? null,
      }),
    }, 20000, signal);
  }

  adminFlagLocation(
    body: { latitude: number; longitude: number; reason: string; severity?: string; locationText?: string },
    signal?: AbortSignal,
  ) {
    return this.request<{ hotspot: SafetyHotspot }>('/api/admin/hotspots/flag', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, location_text: body.locationText ?? null }),
    }, 20000, signal);
  }

  adminPublishAnnouncement(
    body: { title: string; message: string; severity?: string; hotspotId?: number;
            latitude?: number | null; longitude?: number | null; locationText?: string | null },
    signal?: AbortSignal,
  ) {
    return this.request<{ id: number }>('/api/admin/announcements', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: body.title, message: body.message, severity: body.severity ?? 'HIGH',
        hotspot_id: body.hotspotId ?? null, latitude: body.latitude ?? null,
        longitude: body.longitude ?? null, location_text: body.locationText ?? null,
      }),
    }, 20000, signal);
  }

  // --- C3 Safety Intelligence ----------------------------------------------------------------

  /** Run one report through the four-agent workflow. `persist: false` previews without storing. */
  analyzeSafetyReport(reportText: string, persist = true, signal?: AbortSignal) {
    return this.request<SafetyAnalysisResult>(
      '/api/reports/analyze',
      { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_text: reportText, source: 'user', persist }) },
      // The graph makes up to three Groq calls; generous but bounded.
      90000,
      signal,
    );
  }

  /** Seed or re-seed the synthetic demo corpus. Deterministic and offline. */
  seedSafetyCorpus(force = false, signal?: AbortSignal) {
    return this.request<{ processed: number; failed: number; totalInStore: number; seeded: boolean }>(
      '/api/reports/batch-analyze',
      { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ use_synthetic: true, force }) },
      120000,
      signal,
    );
  }

  safetyOverview(signal?: AbortSignal) {
    return this.request<SafetyOverview>('/api/analytics/overview', {}, 30000, signal);
  }

  safetyPatterns(interpret = true, signal?: AbortSignal) {
    return this.request<SafetyPatterns>(
      `/api/analytics/patterns?interpret=${interpret}`, {}, 60000, signal);
  }

  safetyReports(limit = 100, signal?: AbortSignal) {
    return this.request<{ count: number; reports: SafetyReportRow[] }>(
      `/api/reports?limit=${limit}`, {}, 20000, signal);
  }

  safetyHealth(signal?: AbortSignal) {
    return this.request<SafetyHealth>('/api/health', {}, 10000, signal);
  }

  safetyWorkflow(signal?: AbortSignal) {
    return this.request<{ nodes: WorkflowNode[]; llmAvailable: boolean; llmModel: string | null }>(
      '/api/agents/workflow', {}, 10000, signal);
  }

  segregateWaste(file: File | Blob, signal?: AbortSignal, explain = false) {
    const form = new FormData();
    form.append('file', file, file instanceof File ? file.name : 'waste.jpg');
    return this.request<WasteSegregationResult>(
      `/api/waste/segregate${explain ? '?explain=true' : ''}`,
      { method: 'POST', body: form },
      60000,
      signal,
    );
  }

  /**
   * The live camera's only question: is there visible contamination in this frame?
   * Runs YOLO and returns a verdict, not an explanation — the detailed work happens once, on a
   * frame the user deliberately picks.
   */
  scanFrame(frame: File | Blob, signal?: AbortSignal) {
    const form = new FormData();
    form.append('file', frame, frame instanceof File ? frame.name : 'frame.jpg');
    return this.request<FrameScanVerdict>('/api/water/scan-frame', { method: 'POST', body: form }, 25000, signal);
  }

  /**
   * Appearance-match one frame against the labelled reference dataset. Fast path for the live
   * camera: no sensor lookup, no scoring, nothing stored.
   */
  matchWaterFrame(file: File | Blob, signal?: AbortSignal) {
    const form = new FormData();
    form.append('file', file, file instanceof File ? file.name : 'frame.jpg');
    return this.request<WaterDatasetMatch>('/api/water/match-frame', { method: 'POST', body: form }, 20000, signal);
  }

  waterDatasetStatus(signal?: AbortSignal) {
    return this.request<DatasetIndexStatus>('/api/water/dataset-status', {}, 8000, signal);
  }

  /** Coordinates -> place name. Sent as a POST body so coordinates never reach an access log. */
  reverseGeocode(latitude: number, longitude: number, signal?: AbortSignal) {
    return this.request<GeocodeResult>(
      '/api/location/reverse',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ latitude, longitude }) },
      10000,
      signal,
    );
  }

  /** Free-text place name -> coordinates (Nominatim forward geocoding). */
  searchPlaces(query: string, limit = 5, signal?: AbortSignal) {
    return this.request<PlaceSearchResponse>(
      '/api/location/search',
      {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        // India-only application. The backend applies this as Nominatim's own `countrycodes`
        // filter AND re-checks each result's structured country_code, so "Whitefield" resolves
        // to Bengaluru rather than New Hampshire.
        body: JSON.stringify({ query, limit, country_codes: 'in' }),
      },
      12000,
      signal,
    );
  }

  /**
   * Named water bodies near a point, from OpenStreetMap via Overpass. Geography only — it answers
   * "which lake is this?", never anything about water quality.
   */
  nearbyWaterBodies(latitude: number, longitude: number, radiusM?: number, signal?: AbortSignal) {
    return this.request<NearbyWaterResponse>(
      '/api/water/nearby-bodies',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latitude, longitude, radiusM }),
      },
      30000, // Overpass is a shared free service and can be slow under load
      signal,
    );
  }

  /**
   * Contextual OSM features near a point (industrial land, waste facilities, waterways, major
   * roads), from Overpass. CONTEXT ONLY — it reports what is MAPPED, never what is measured,
   * and nothing it returns may be described as a cause of a reading.
   */
  geographicContext(latitude: number, longitude: number, radiusM?: number, signal?: AbortSignal) {
    return this.request<GeographicContext>(
      '/api/location/context',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latitude, longitude, radiusM }),
      },
      30000, // Overpass is a shared free service and can be slow under load
      signal,
    );
  }

  /**
   * Submit a citizen contamination report. This is the one call that persists precise
   * coordinates, so it is only ever made after an explicit confirmation in the UI.
   */
  submitContaminationReport(report: ContaminationReportRequest, signal?: AbortSignal) {
    return this.request<ContaminationReportReceipt>(
      '/api/reports/contamination',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(report) },
      20000,
      signal,
    );
  }

  /** Which AI roles are configured and whether they can answer. Never returns a key. */
  aiStatus(signal?: AbortSignal) {
    return this.request<AiStatusResponse>('/api/ai/status', {}, 8000, signal);
  }

  /**
   * Ask a question about one specific analysis. `analysisId` is required — an answer must be
   * grounded in the decision on screen, never in whichever analysis ran most recently.
   */
  chat(analysisId: string, question: string, signal?: AbortSignal) {
    return this.request<ChatResponse>(
      '/api/chat',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysisId, question }),
      },
      45000, // an explainability provider adds a model round-trip
      signal,
    );
  }

  agentsStatus(signal?: AbortSignal) {
    return this.request<AgentsStatusResponse>('/api/agents/status', {}, 5000, signal);
  }

  private async request<T>(path: string, init: RequestInit, timeoutMs: number, signal?: AbortSignal): Promise<T> {
    if (signal?.aborted) throw abortError();
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const forwardAbort = () => controller.abort();
    signal?.addEventListener('abort', forwardAbort, { once: true });

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, { ...init, signal: controller.signal });
    } catch {
      if (signal?.aborted) throw abortError();
      if (timedOut) {
        throw new AppError('API_TIMEOUT', `The EcoSentinel API did not respond within ${Math.round(timeoutMs / 1000)} seconds.`);
      }
      throw new AppError(
        'API_UNAVAILABLE',
        `Could not reach the EcoSentinel API${this.baseUrl ? ` at ${this.baseUrl}` : ''}. Start the backend or switch to Demo Mode.`,
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', forwardAbort);
    }

    let body: unknown = null;
    try {
      const text = await response.text();
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }

    if (!response.ok) {
      const error = (body as { error?: { code?: string; message?: string } } | null)?.error;
      if (error?.message) {
        throw new AppError(error.code && isKnownCode(error.code) ? error.code : 'UNKNOWN', error.message);
      }
      throw new AppError(
        'API_UNAVAILABLE',
        `The EcoSentinel API returned HTTP ${response.status}. Check that the backend is running, or switch to Demo Mode.`,
      );
    }
    if (body === null) throw new AppError('API_UNAVAILABLE', 'The EcoSentinel API returned an empty response.');
    return body as T;
  }
}


/**
 * SelectedLocation (UI shape) -> LocationContext (backend contract, backend/schemas.py).
 *
 * Full coordinate precision is preserved: the UI rounds only for display, because the analysis
 * genuinely needs the precision to pick the right monitoring station.
 */
function toLocationContext(selected: SelectedLocation) {
  return {
    latitude: selected.latitude,
    longitude: selected.longitude,
    accuracyM: selected.accuracy ?? null,
    displayName: selected.displayName,
    city: selected.city ?? null,
    state: selected.state ?? null,
    country: selected.country ?? null,
    // The backend distinguishes only "a real fix" from "a preset area". A place the user searched
    // for is a real coordinate, so it is not a preset.
    source: selected.source === 'preset' ? 'preset' : 'browser_geolocation',
    geocoding: selected.geocoding,
  };
}
