/**
 * Multi-agent execution engine.
 *
 *   Data -> Air Agent -> Water Agent -> Waste Agent -> Coordinator -> Decision
 *
 * Demo mode runs the TypeScript agents in the browser with mock data sources.
 * Live mode asks the FastAPI orchestrator to run the Python agents, then replays
 * each agent's trace so the hand-offs remain visible.
 */
import { nearestLocation, resolveLocation } from '../data/locations';
import type {
  AgentId,
  AgentRun,
  AnalysisResult,
  CoordinatorResult,
  SelectedLocation,
  SpecialistResult,
  WasteAgentResult,
  WaterAgentResult,
  WaterVisionReport,
} from '../types/agents';
import { AgentTrace } from './agents/agent';
import { AirQualityAgent } from './agents/airAgent';
import { CoordinatorAgent } from './agents/coordinatorAgent';
import { WasteDetectionAgent } from './agents/wasteAgent';
import { WaterQualityAgent } from './agents/waterAgent';
import type { ApiClient } from './apiClient';
import { AppError, isAbortError, toAppError } from './errors';
import { MockAirQualitySource } from './providers/airQualitySource';
import { MockWasteDetector, validateImageFile } from './providers/wasteDetectionSource';
import { MockWaterSensorSource } from './providers/waterSensorSource';

export type EngineMode = 'demo' | 'live';
export type FaultInjection = 'none' | 'water-timeout' | 'air-failure';

export type EngineEvent =
  | { type: 'agent:start'; agent: AgentId }
  | { type: 'agent:log'; agent: AgentId; message: string }
  | { type: 'agent:complete'; agent: AgentId; result: SpecialistResult | CoordinatorResult; durationMs: number }
  | { type: 'agent:failed'; agent: AgentId; status: 'failed' | 'timeout'; error: string; durationMs: number };

export interface EngineOptions {
  mode: EngineMode;
  api: ApiClient;
  /** 1 = presentation pacing, 0.5 = fast, 0 = instant */
  speed: number;
  fault: FaultInjection;
  signal: AbortSignal;
  onEvent: (event: EngineEvent) => void;
}

export const AGENT_ORDER: AgentId[] = ['air', 'water', 'waste', 'coordinator'];
export const AGENT_DURATIONS_MS: Record<AgentId, number> = { air: 1000, water: 1000, waste: 1500, coordinator: 1000 };
export const AGENT_NAMES: Record<AgentId, string> = {
  air: 'Air Quality Agent',
  water: 'Water Quality Agent',
  waste: 'Waste Detection Agent',
  coordinator: 'Coordinator Agent',
};
const DEMO_AGENT_TIMEOUT_MS = 3000;

// ------------------------------------------------------------------ helpers

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException('Aborted', 'AbortError'));
    if (ms <= 0) return resolve();
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal.addEventListener('abort', onAbort, { once: true });
  });
}

function withTimeout<T>(promise: Promise<T>, ms: number, agent: AgentId, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(new AppError('AGENT_TIMEOUT', `${AGENT_NAMES[agent]} timed out after ${(ms / 1000).toFixed(0)}s — no response from its data source.`));
    }, ms);
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (error) => {
        cleanup();
        reject(error);
      },
    );
  });
}

async function streamLogs(agent: AgentId, steps: string[], budgetMs: number, opts: EngineOptions) {
  const interval = steps.length ? budgetMs / steps.length : 0;
  for (const message of steps) {
    await sleep(interval, opts.signal);
    opts.onEvent({ type: 'agent:log', agent, message });
  }
}

const newId = () => Math.random().toString(16).slice(2, 14).padEnd(12, '0');

function createDemoAgents(fault: FaultInjection) {
  return {
    air: new AirQualityAgent(new MockAirQualitySource({ simulateFailure: fault === 'air-failure' })),
    water: new WaterQualityAgent(new MockWaterSensorSource({ simulateTimeout: fault === 'water-timeout' })),
    waste: new WasteDetectionAgent(new MockWasteDetector()),
    coordinator: new CoordinatorAgent(),
  };
}

/** Run one in-browser agent under a timeout; specialists fail soft (return null). */
async function runLocalAgent<T extends SpecialistResult | CoordinatorResult>(
  agent: AgentId,
  execute: (trace: AgentTrace) => Promise<T>,
  opts: EngineOptions,
  runs: AgentRun[],
): Promise<T | null> {
  opts.onEvent({ type: 'agent:start', agent });
  const started = performance.now();
  const trace = new AgentTrace();
  const budget = AGENT_DURATIONS_MS[agent] * opts.speed;

  try {
    const timeoutMs = opts.speed === 0 ? 1200 : DEMO_AGENT_TIMEOUT_MS;
    const result = await withTimeout(execute(trace), timeoutMs, agent, opts.signal);
    await streamLogs(agent, trace.steps, budget, opts);
    const durationMs = Math.round(performance.now() - started);
    runs.push({ agent, name: AGENT_NAMES[agent], status: 'complete', durationMs, steps: trace.steps, error: null });
    opts.onEvent({ type: 'agent:complete', agent, result, durationMs });
    return result;
  } catch (error) {
    if (isAbortError(error)) throw error;
    const appError = toAppError(error);
    await streamLogs(agent, trace.steps, budget * 0.3, opts);
    const status = appError.code === 'AGENT_TIMEOUT' ? 'timeout' : 'failed';
    const durationMs = Math.round(performance.now() - started);
    runs.push({ agent, name: AGENT_NAMES[agent], status, durationMs, steps: trace.steps, error: appError.message });
    opts.onEvent({ type: 'agent:failed', agent, status, error: appError.message, durationMs });
    return null;
  }
}

/** Replay backend agent runs with presentation pacing. */
async function replayRuns(
  runs: AgentRun[],
  results: Partial<Record<AgentId, SpecialistResult | CoordinatorResult | null>>,
  opts: EngineOptions,
  alreadyStarted: AgentId[],
) {
  for (const run of runs) {
    if (!alreadyStarted.includes(run.agent)) opts.onEvent({ type: 'agent:start', agent: run.agent });
    const steps = run.steps.filter((step) => step !== run.error);
    await streamLogs(run.agent, steps, AGENT_DURATIONS_MS[run.agent] * opts.speed, opts);
    const result = results[run.agent];
    if (run.status === 'complete' && result) {
      opts.onEvent({ type: 'agent:complete', agent: run.agent, result, durationMs: run.durationMs });
    } else {
      opts.onEvent({
        type: 'agent:failed',
        agent: run.agent,
        status: run.status === 'timeout' ? 'timeout' : 'failed',
        error: run.error ?? `${run.name} did not return a report.`,
        durationMs: run.durationMs,
      });
    }
  }
}

async function callApi<T>(agent: AgentId, message: string, call: () => Promise<T>, opts: EngineOptions): Promise<T> {
  const started = performance.now();
  opts.onEvent({ type: 'agent:start', agent });
  opts.onEvent({ type: 'agent:log', agent, message });
  try {
    const [response] = await Promise.all([call(), sleep(250 * opts.speed, opts.signal)]);
    return response;
  } catch (error) {
    if (isAbortError(error)) throw error;
    const appError = toAppError(error);
    opts.onEvent({
      type: 'agent:failed',
      agent,
      status: appError.code === 'API_TIMEOUT' ? 'timeout' : 'failed',
      error: appError.message,
      durationMs: Math.round(performance.now() - started),
    });
    throw appError;
  }
}

// ------------------------------------------------------------------ public API

/**
 * Run one analysis.
 *
 * `selected` is the exact point the user picked — a browser geolocation fix or a Nominatim
 * search result. When present, live mode sends those coordinates to the backend, which is what
 * lets any place be analysed rather than only the preset monitoring areas. The in-browser demo
 * engine has only the preset dataset, so it always falls back to the named preset.
 */
export async function runAnalysis(
  locationName: string,
  selected: SelectedLocation | null,
  opts: EngineOptions,
): Promise<AnalysisResult> {
  if (opts.mode === 'live') {
    const response = await callApi(
      'air',
      selected
        ? `Dispatching analysis request for ${selected.displayName}`
        : 'Dispatching analysis request to EcoSentinel API',
      () => opts.api.analyze(locationName, selected, opts.signal),
      opts,
    );
    await replayRuns(
      response.runs,
      { air: response.air, water: response.water, waste: response.waste, coordinator: response.coordinator },
      opts,
      ['air'],
    );
    return response;
  }

  // Demo Mode has fixtures only for the preset areas. A real point the user picked (a browser
  // fix or a search result) has no fixtures, so the nearest preset stands in — every card still
  // labels the result as demo data, so this never reads as a measurement of their location.
  const location = selected ? nearestLocation(selected.latitude, selected.longitude) : resolveLocation(locationName);
  const agents = createDemoAgents(opts.fault);
  const startedAt = new Date().toISOString();
  const runs: AgentRun[] = [];

  // Specialists run independently; each produces a structured report.
  const air = await runLocalAgent('air', (trace) => agents.air.run(location, trace), opts, runs);
  const water = await runLocalAgent('water', (trace) => agents.water.run(location, trace), opts, runs);
  const waste = await runLocalAgent('waste', (trace) => agents.waste.run({ location }, trace), opts, runs);

  // The coordinator consumes only those reports.
  const coordinator = await runLocalAgent(
    'coordinator',
    (trace) => agents.coordinator.run({ location: location.name, air, water, waste }, trace),
    opts,
    runs,
  );
  if (!coordinator) {
    throw new AppError('ANALYSIS_FAILED', runs[runs.length - 1]?.error ?? 'Coordinator could not complete the assessment.');
  }

  return {
    analysisId: newId(),
    location: location.name,
    mode: 'demo',
    startedAt,
    completedAt: new Date().toISOString(),
    air,
    water,
    waste,
    coordinator,
    runs,
  };
}

export interface ImageAnalysisOutput {
  waste: WasteAgentResult;
  coordinator: CoordinatorResult;
  runs: AgentRun[];
}

/** Re-run the Waste agent on an uploaded image, then let the Coordinator re-assess. */
export async function runWasteImageAnalysis(file: File, base: AnalysisResult, opts: EngineOptions): Promise<ImageAnalysisOutput> {
  validateImageFile(file);

  if (opts.mode === 'live') {
    const response = await callApi('waste', `Uploading ${file.name} to EcoSentinel API`, () => opts.api.analyzeWaste(file, base.location, opts.signal), opts);
    const visible = response.runs.filter((run) => run.agent === 'waste' || run.agent === 'coordinator');
    await replayRuns(visible, { waste: response.waste, coordinator: response.coordinator }, opts, ['waste']);
    if (!response.coordinator) throw new AppError('ANALYSIS_FAILED', 'Coordinator could not re-assess the area.');
    return { waste: response.waste, coordinator: response.coordinator, runs: visible };
  }

  const location = resolveLocation(base.location);
  const agents = createDemoAgents(opts.fault);
  const runs: AgentRun[] = [];
  const waste = await runLocalAgent('waste', (trace) => agents.waste.run({ location, image: { name: file.name, size: file.size } }, trace), opts, runs);
  if (!waste) throw new AppError('INVALID_IMAGE', runs[runs.length - 1]?.error ?? 'Waste detection failed for this image.');

  const coordinator = await runLocalAgent(
    'coordinator',
    (trace) => agents.coordinator.run({ location: location.name, air: base.air, water: base.water, waste }, trace),
    opts,
    runs,
  );
  if (!coordinator) throw new AppError('ANALYSIS_FAILED', 'Coordinator could not re-assess the area.');
  return { waste, coordinator, runs };
}

export interface WaterImageAnalysisOutput {
  water: WaterAgentResult;
  runs: AgentRun[];
}

/**
 * Demo Mode has no detector: the vision model lives server-side. Rather than invent detections,
 * the Water Agent report carries an explicit "unavailable" vision block explaining why.
 */
const DEMO_VISION_REPORT: WaterVisionReport = {
  available: false,
  status: 'unavailable',
  model: null,
  message:
    'Demo Mode is on, so no detector ran on this photo. Visual pollution detection is a server-side model — turn Demo Mode off in Settings with the backend running to analyse it.',
  detections: [],
  objectCounts: {},
  totalObjects: 0,
  confidenceThreshold: null,
  visualScore: null,
  visualLevel: null,
  annotatedImage: null,
};

/** Re-run the Water agent with a water photo attached, adding the visual-pollution half of its report. */
export async function runWaterImageAnalysis(file: File, base: AnalysisResult, opts: EngineOptions): Promise<WaterImageAnalysisOutput> {
  validateImageFile(file);
  if (!base.water) throw new AppError('ANALYSIS_FAILED', 'The Water Agent has no report to attach this image to.');

  if (opts.mode === 'live') {
    const started = performance.now();
    const water = await callApi(
      'water',
      `Uploading ${file.name} for visual pollution detection`,
      () => opts.api.analyzeWaterImage(file, base.location, opts.signal),
      opts,
    );
    const durationMs = Math.round(performance.now() - started);
    const vision = water.visualPollution;
    const steps = [
      `Processed sensor readings · ${water.sensorName} (${water.sensorId})`,
      // Both numbers: what the detector saw, and how much of it is litter. The two differ
      // whenever a COCO model meets a river scene containing people or boats.
      vision?.status === 'ok'
        ? `${vision.model ?? 'Vision model'} detected ${vision.totalObjects} object${vision.totalObjects === 1 ? '' : 's'} · ${
            vision.pollutionObjects ??
            vision.detections.filter((d) => d.semanticCategory === 'visible_surface_litter').length
          } classified as visible litter`
        : (vision?.message ?? 'Visual detection did not run.'),
    ];
    await streamLogs('water', steps, AGENT_DURATIONS_MS.water * opts.speed, opts);
    opts.onEvent({ type: 'agent:complete', agent: 'water', result: water, durationMs });
    return { water, runs: [{ agent: 'water', name: AGENT_NAMES.water, status: 'complete', durationMs, steps, error: null }] };
  }

  const started = performance.now();
  opts.onEvent({ type: 'agent:start', agent: 'water' });
  const steps = [`Received ${file.name}`, DEMO_VISION_REPORT.message as string];
  await streamLogs('water', steps, AGENT_DURATIONS_MS.water * opts.speed, opts);
  const water: WaterAgentResult = { ...base.water, visualPollution: DEMO_VISION_REPORT };
  const durationMs = Math.round(performance.now() - started);
  opts.onEvent({ type: 'agent:complete', agent: 'water', result: water, durationMs });
  return { water, runs: [{ agent: 'water', name: AGENT_NAMES.water, status: 'complete', durationMs, steps, error: null }] };
}
