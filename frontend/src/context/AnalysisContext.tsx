import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from 'react';
import { loadEnvironment } from '../services/environmentService';
import {
  AGENT_ORDER,
  runAnalysis as runEngineAnalysis,
  runWasteImageAnalysis,
  runWaterImageAnalysis,
  type EngineEvent,
  type EngineOptions,
} from '../services/analysisEngine';
import { useBrowserLocation, type BrowserLocationState } from '../hooks/useBrowserLocation';
import { AppError, isAbortError, toAppError } from '../services/errors';
import { validateImageFile } from '../services/providers/wasteDetectionSource';
import type {
  AgentId,
  AirAgentResult,
  AnalysisResult,
  CoordinatorResult,
  RiskLevel,
  SelectedLocation,
  WasteAgentResult,
  WaterAgentResult,
} from '../types/agents';
import type { EnvironmentSnapshot } from '../types/environment';
import { useSettings } from './SettingsContext';
import { useToast } from './ToastContext';

export type StepStatus = 'idle' | 'queued' | 'running' | 'complete' | 'failed' | 'timeout';
export type Phase = 'idle' | 'running' | 'complete' | 'error';

export interface AgentStepState {
  agent: AgentId;
  status: StepStatus;
  logs: string[];
  durationMs: number | null;
  riskLevel: RiskLevel | null;
  error: string | null;
}

interface LiveResults {
  air?: AirAgentResult;
  water?: WaterAgentResult;
  waste?: WasteAgentResult;
  coordinator?: CoordinatorResult;
}

interface State {
  selectedLocation: string;
  /**
   * The point the analysis runs against, when the user picked a real one (a browser fix or a
   * Nominatim search result). Null means "use the preset named by `selectedLocation`", which is
   * the pre-existing behaviour and stays the default.
   */
  selectedPoint: SelectedLocation | null;
  phase: Phase;
  runKind: 'analysis' | 'image' | null;
  steps: Record<AgentId, AgentStepState>;
  result: AnalysisResult | null;
  live: LiveResults;
  error: AppError | null;
  uploadedImage: { url: string; name: string } | null;
  /** Water photo the user captured or picked, kept separate from the waste upload. */
  waterImage: { url: string; name: string } | null;
  lastDurationMs: number | null;
  /**
   * Identifies the target the displayed result was produced for (see `locationKey`). Comparing
   * it to the current target is what makes the "location changed — re-run" hint accurate: the
   * coordinator's location LABEL cannot serve, because it shortens "Bengaluru, Bangalore
   * North, …" to "Bengaluru" and would read as stale forever.
   */
  analyzedKey: string | null;
}

/** Stable identity for an analysis target: the exact point when there is one, else the name. */
export function locationKey(name: string, point: SelectedLocation | null): string {
  return point ? `${point.latitude},${point.longitude}` : name.trim().toLowerCase();
}

type Action =
  | EngineEvent
  | { type: 'select'; location: string }
  | { type: 'select:point'; point: SelectedLocation | null }
  | { type: 'run:start'; kind: 'analysis' | 'image'; agents: AgentId[] }
  | { type: 'run:complete'; result: AnalysisResult; durationMs: number; targetKey?: string }
  | { type: 'run:error'; error: AppError }
  | { type: 'error:clear' }
  | { type: 'image:set'; image: { url: string; name: string } | null }
  | { type: 'water-image:set'; image: { url: string; name: string } | null };

const emptyStep = (agent: AgentId): AgentStepState => ({ agent, status: 'idle', logs: [], durationMs: null, riskLevel: null, error: null });

const initialState: State = {
  selectedLocation: 'Bengaluru',
  selectedPoint: null,
  phase: 'idle',
  runKind: null,
  steps: { air: emptyStep('air'), water: emptyStep('water'), waste: emptyStep('waste'), coordinator: emptyStep('coordinator') },
  result: null,
  live: {},
  error: null,
  uploadedImage: null,
  waterImage: null,
  lastDurationMs: null,
  analyzedKey: null,
};

function patchStep(state: State, agent: AgentId, patch: Partial<AgentStepState>): State {
  return { ...state, steps: { ...state.steps, [agent]: { ...state.steps[agent], ...patch } } };
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'select':
      // Choosing a preset discards any browser/searched point: they are alternative answers to
      // the same question, and keeping both would make "which coordinates ran?" ambiguous.
      return { ...state, selectedLocation: action.location, selectedPoint: null };
    case 'select:point':
      return {
        ...state,
        selectedPoint: action.point,
        selectedLocation: action.point ? action.point.displayName : state.selectedLocation,
      };
    case 'run:start': {
      const steps = { ...state.steps };
      action.agents.forEach((agent) => {
        steps[agent] = { ...emptyStep(agent), status: 'queued' };
      });
      return { ...state, phase: 'running', runKind: action.kind, steps, live: {}, error: null };
    }
    case 'agent:start':
      return patchStep(state, action.agent, { status: 'running' });
    case 'agent:log':
      return patchStep(state, action.agent, { logs: [...state.steps[action.agent].logs, action.message] });
    case 'agent:complete': {
      const riskLevel = action.result.agent === 'coordinator' ? action.result.overallRiskLevel : action.result.riskLevel;
      const next = patchStep(state, action.agent, { status: 'complete', durationMs: action.durationMs, riskLevel });
      return { ...next, live: { ...state.live, [action.agent]: action.result } };
    }
    case 'agent:failed':
      return patchStep(state, action.agent, { status: action.status, durationMs: action.durationMs, error: action.error });
    case 'run:complete':
      return {
        ...state,
        phase: 'complete',
        result: action.result,
        live: {},
        lastDurationMs: action.durationMs,
        // An image re-analysis carries no target of its own; it refines the existing result.
        analyzedKey: action.targetKey ?? state.analyzedKey,
      };
    case 'run:error': {
      const steps = { ...state.steps };
      AGENT_ORDER.forEach((agent) => {
        if (steps[agent].status === 'queued' || steps[agent].status === 'running') steps[agent] = emptyStep(agent);
      });
      return { ...state, phase: 'error', steps, live: {}, error: action.error };
    }
    case 'error:clear':
      return { ...state, error: null, phase: state.result ? 'complete' : 'idle' };
    case 'image:set':
      return { ...state, uploadedImage: action.image };
    case 'water-image:set':
      return { ...state, waterImage: action.image };
    default:
      return state;
  }
}

export interface SystemStatus {
  tone: 'operational' | 'degraded' | 'offline' | 'running';
  label: string;
}

interface AnalysisValue {
  state: State;
  selectLocation: (location: string) => void;
  /** Set (or clear) the exact point to analyse — a browser fix or a Nominatim search result. */
  selectPoint: (point: SelectedLocation | null) => void;
  /**
   * The one browser-geolocation instance for the app. Shared rather than created per component,
   * so however many controls offer "Use My Location", the permission dialog opens at most once.
   */
  browserLocation: BrowserLocationState;
  runAnalysis: (options?: { instant?: boolean }) => Promise<AnalysisResult | null>;
  analyzeImage: (file: File) => Promise<boolean>;
  analyzeWaterImage: (file: File) => Promise<boolean>;
  clearError: () => void;
  display: { air: AirAgentResult | null; water: WaterAgentResult | null; waste: WasteAgentResult | null; coordinator: CoordinatorResult | null };
  pending: Record<AgentId, boolean>;
  failures: Record<AgentId, string | null>;
  progress: number;
  environment: EnvironmentSnapshot | null;
  environmentError: AppError | null;
  environmentLoading: boolean;
  systemStatus: SystemStatus;
}

const AnalysisContext = createContext<AnalysisValue | null>(null);

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const { settings, api } = useSettings();
  const { notify } = useToast();
  const [state, dispatch] = useReducer(reducer, initialState);
  const runIdRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const [environment, setEnvironment] = useState<EnvironmentSnapshot | null>(null);
  const [environmentError, setEnvironmentError] = useState<AppError | null>(null);
  const [environmentLoading, setEnvironmentLoading] = useState(false);
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);
  /**
   * Whether the question "where are we analysing?" has been answered yet. The first analysis
   * waits for this. Without it the dashboard auto-ran against the default preset and only then
   * received the browser fix, so the very first result described the wrong place while the
   * location bar already showed the right one.
   */
  const [locationSettled, setLocationSettled] = useState(false);

  const reverseGeocode = useCallback(
    (latitude: number, longitude: number) => api.reverseGeocode(latitude, longitude),
    [api],
  );
  const browserLocation = useBrowserLocation({ reverseGeocode });
  // The hook returns a fresh object each render, so the effect below must not depend on it:
  // re-running would cancel the in-flight attempt and discard the fix it was about to deliver.
  const requestLocationOnce = useRef(browserLocation.requestOnce);
  requestLocationOnce.current = browserLocation.requestOnce;

  const beginRun = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const runId = ++runIdRef.current;
    const guard = (action: Action) => {
      if (runIdRef.current === runId) dispatch(action);
    };
    return { controller, guard };
  }, []);

  const engineOptions = useCallback(
    (controller: AbortController, guard: (action: Action) => void, instant: boolean): EngineOptions => ({
      mode: settings.demoMode ? 'demo' : 'live',
      api,
      speed: instant ? 0 : settings.speed === 'fast' ? 0.5 : 1,
      fault: settings.fault,
      signal: controller.signal,
      onEvent: guard,
    }),
    [api, settings.demoMode, settings.fault, settings.speed],
  );

  const runAnalysis = useCallback(
    async ({ instant = false }: { instant?: boolean } = {}) => {
      const { controller, guard } = beginRun();
      const started = performance.now();
      const location = stateRef.current.selectedLocation;
      const point = stateRef.current.selectedPoint;
      dispatch({ type: 'run:start', kind: 'analysis', agents: AGENT_ORDER });
      if (stateRef.current.uploadedImage) {
        URL.revokeObjectURL(stateRef.current.uploadedImage.url);
        dispatch({ type: 'image:set', image: null });
      }
      if (stateRef.current.waterImage) {
        URL.revokeObjectURL(stateRef.current.waterImage.url);
        dispatch({ type: 'water-image:set', image: null });
      }
      try {
        const result = await runEngineAnalysis(location, point, engineOptions(controller, guard, instant));
        guard({
          type: 'run:complete',
          result,
          durationMs: Math.round(performance.now() - started),
          targetKey: locationKey(location, point),
        });
        return result;
      } catch (error) {
        if (isAbortError(error)) return null;
        guard({ type: 'run:error', error: toAppError(error) });
        return null;
      }
    },
    [beginRun, engineOptions],
  );

  const analyzeImage = useCallback(
    async (file: File) => {
      const current = stateRef.current;
      try {
        validateImageFile(file);
        if (!current.result) throw new AppError('ANALYSIS_FAILED', 'Run an area analysis before uploading an image.');
        if (current.phase === 'running') throw new AppError('ANALYSIS_FAILED', 'Please wait for the current analysis to finish.');
      } catch (error) {
        const appError = toAppError(error);
        notify({ tone: 'error', title: appError.title, description: appError.message });
        return false;
      }

      const base = current.result;
      const { controller, guard } = beginRun();
      const started = performance.now();
      if (current.uploadedImage) URL.revokeObjectURL(current.uploadedImage.url);
      dispatch({ type: 'image:set', image: { url: URL.createObjectURL(file), name: file.name } });
      dispatch({ type: 'run:start', kind: 'image', agents: ['waste', 'coordinator'] });

      try {
        const output = await runWasteImageAnalysis(file, base, engineOptions(controller, guard, false));
        const result: AnalysisResult = {
          ...base,
          waste: output.waste,
          coordinator: output.coordinator,
          completedAt: new Date().toISOString(),
          runs: [...base.runs.filter((run) => run.agent === 'air' || run.agent === 'water'), ...output.runs],
        };
        guard({ type: 'run:complete', result, durationMs: Math.round(performance.now() - started) });
        notify({
          tone: 'success',
          title: `${output.waste.totalObjects} objects detected`,
          description: `Coordinator re-assessed ${base.location}: ${output.coordinator.overallRiskLevel} (${Math.round(output.coordinator.overallScore * 100)}%).`,
        });
        return true;
      } catch (error) {
        if (isAbortError(error)) return false;
        const appError = toAppError(error);
        guard({ type: 'run:error', error: appError });
        notify({ tone: 'error', title: appError.title, description: appError.message });
        return false;
      }
    },
    [beginRun, engineOptions, notify],
  );

  /** Attach a captured or picked water photo to the Water Agent and re-run just that agent. */
  const analyzeWaterImage = useCallback(
    async (file: File) => {
      const current = stateRef.current;
      try {
        validateImageFile(file);
        if (!current.result?.water) throw new AppError('ANALYSIS_FAILED', 'Run an area analysis before adding a water photo.');
        if (current.phase === 'running') throw new AppError('ANALYSIS_FAILED', 'Please wait for the current analysis to finish.');
      } catch (error) {
        const appError = toAppError(error);
        notify({ tone: 'error', title: appError.title, description: appError.message });
        return false;
      }

      const base = current.result;
      const { controller, guard } = beginRun();
      const started = performance.now();
      if (current.waterImage) URL.revokeObjectURL(current.waterImage.url);
      dispatch({ type: 'water-image:set', image: { url: URL.createObjectURL(file), name: file.name } });
      dispatch({ type: 'run:start', kind: 'image', agents: ['water'] });

      try {
        const output = await runWaterImageAnalysis(file, base, engineOptions(controller, guard, false));
        const result: AnalysisResult = {
          ...base,
          water: output.water,
          completedAt: new Date().toISOString(),
          runs: [...base.runs.filter((run) => run.agent !== 'water'), ...output.runs],
        };
        guard({ type: 'run:complete', result, durationMs: Math.round(performance.now() - started) });
        const vision = output.water.visualPollution;
        if (vision?.status === 'ok') {
          // The LITTER count, not the raw object count. A COCO detector in a river scene reports
          // people and boats too, and calling those "pollution objects" invents pollution.
          const litter = vision.pollutionObjects ??
            vision.detections.filter((d) => d.semanticCategory === 'visible_surface_litter').length;
          notify({
            tone: litter > 0 ? 'success' : 'info',
            title: litter > 0
              ? `${litter} litter object${litter === 1 ? '' : 's'} visible`
              : 'No visible litter detected',
            description: litter > 0
              ? `Visual signal ${vision.visualLevel ?? '—'} — water risk is now ${Math.round(output.water.riskScore * 100)}%.`
              : `${vision.totalObjects} object${vision.totalObjects === 1 ? '' : 's'} detected, none indicating litter. This is not evidence the water is clean.`,
          });
        } else {
          notify({
            tone: 'info',
            title: 'Photo added — no visual detection',
            description: vision?.message ?? 'Visual detection did not run for this image.',
          });
        }
        return true;
      } catch (error) {
        if (isAbortError(error)) return false;
        const appError = toAppError(error);
        guard({ type: 'run:error', error: appError });
        notify({ tone: 'error', title: appError.title, description: appError.message });
        return false;
      }
    },
    [beginRun, engineOptions, notify],
  );

  /**
   * Ask the browser where we are, once, before the first analysis.
   *
   * This lives here rather than in a dashboard component so the sequencing holds on every route,
   * and so a single hook instance owns the permission prompt. Demo Mode settles immediately: it
   * renders fixtures, so a real location would buy nothing and the prompt would be pure noise.
   */
  const modeKey = `${settings.demoMode}|${settings.apiBaseUrl}`;
  useEffect(() => {
    let cancelled = false;
    if (settings.demoMode) {
      setLocationSettled(true);
      return;
    }
    void requestLocationOnce.current().then((found) => {
      if (cancelled) return;
      if (found) dispatch({ type: 'select:point', point: found });
      // Settled either way: a denial or a timeout is an answer, and the preset stands in.
      setLocationSettled(true);
    });
    return () => {
      cancelled = true;
    };
  }, [settings.demoMode]);

  // Populate the dashboard on load — once the location is known — and re-run when the mode flips.
  useEffect(() => {
    if (!locationSettled) return;
    void runAnalysis({ instant: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modeKey, locationSettled]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  // Environment snapshot (map layout + history) follows the analyzed location.
  const analyzedLocation = state.result?.location;
  useEffect(() => {
    if (!analyzedLocation) return;
    const controller = new AbortController();
    setEnvironmentLoading(true);
    loadEnvironment(analyzedLocation, settings.demoMode ? 'demo' : 'live', api, controller.signal)
      .then((snapshot) => {
        setEnvironment(snapshot);
        setEnvironmentError(null);
      })
      .catch((error) => {
        if (!isAbortError(error)) setEnvironmentError(toAppError(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setEnvironmentLoading(false);
      });
    return () => controller.abort();
  }, [analyzedLocation, settings.demoMode, api]);

  // Poll backend agent health in live mode.
  useEffect(() => {
    if (settings.demoMode) {
      setApiReachable(null);
      return;
    }
    let cancelled = false;
    const check = () =>
      api
        .agentsStatus()
        .then(() => !cancelled && setApiReachable(true))
        .catch(() => !cancelled && setApiReachable(false));
    void check();
    const interval = window.setInterval(check, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [api, settings.demoMode]);

  const selectLocation = useCallback((location: string) => dispatch({ type: 'select', location }), []);
  const selectPoint = useCallback((point: SelectedLocation | null) => dispatch({ type: 'select:point', point }), []);
  const clearError = useCallback(() => dispatch({ type: 'error:clear' }), []);

  const value = useMemo<AnalysisValue>(() => {
    const { steps, live, result, phase } = state;
    const running = phase === 'running';
    const pending = Object.fromEntries(
      AGENT_ORDER.map((agent) => [agent, running && (steps[agent].status === 'queued' || steps[agent].status === 'running')]),
    ) as Record<AgentId, boolean>;
    const failures = Object.fromEntries(
      AGENT_ORDER.map((agent) => [agent, steps[agent].status === 'failed' || steps[agent].status === 'timeout' ? steps[agent].error : null]),
    ) as Record<AgentId, string | null>;

    const display = {
      air: failures.air ? null : live.air ?? result?.air ?? null,
      water: failures.water ? null : live.water ?? result?.water ?? null,
      waste: failures.waste ? null : live.waste ?? result?.waste ?? null,
      coordinator: live.coordinator ?? result?.coordinator ?? null,
    };

    const tracked = AGENT_ORDER.filter((agent) => steps[agent].status !== 'idle');
    const weights: Record<StepStatus, number> = { idle: 0, queued: 0, running: 0.5, complete: 1, failed: 1, timeout: 1 };
    const progress = tracked.length ? tracked.reduce((sum, agent) => sum + weights[steps[agent].status], 0) / tracked.length : 0;

    const degraded = AGENT_ORDER.filter((agent) => failures[agent]).length;
    const systemStatus: SystemStatus =
      !settings.demoMode && apiReachable === false
        ? { tone: 'offline', label: 'API unreachable' }
        : running
          ? { tone: 'running', label: 'Agents running' }
          : degraded
            ? { tone: 'degraded', label: `${degraded} agent${degraded > 1 ? 's' : ''} degraded` }
            : { tone: 'operational', label: 'All agents operational' };

    return {
      state,
      selectLocation,
      selectPoint,
      browserLocation,
      runAnalysis,
      analyzeImage,
      analyzeWaterImage,
      clearError,
      display,
      pending,
      failures,
      progress,
      environment,
      environmentError,
      environmentLoading,
      systemStatus,
    };
  }, [state, selectLocation, selectPoint, browserLocation, runAnalysis, analyzeImage, analyzeWaterImage, clearError, environment, environmentError, environmentLoading, settings.demoMode, apiReachable]);

  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>;
}

export function useAnalysis() {
  const context = useContext(AnalysisContext);
  if (!context) throw new Error('useAnalysis must be used inside AnalysisProvider');
  return context;
}
