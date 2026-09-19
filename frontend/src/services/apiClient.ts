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
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, limit }) },
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
