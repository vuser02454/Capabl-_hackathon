import { CircleCheck, FlaskConical, Gauge, PlugZap, Server, ShieldCheck, Zap } from 'lucide-react';
import { AiConfiguration } from '../components/settings/AiConfiguration';
import { useEffect, useState } from 'react';
import { AGENT_META } from '../components/agents/agentMeta';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { ErrorState } from '../components/ui/ErrorState';
import { Chip, SegmentedControl, Switch } from '../components/ui/primitives';
import { useSettings } from '../context/SettingsContext';
import { useToast } from '../context/ToastContext';
import { cn } from '../lib/format';
import { HIGH_THRESHOLD, MODERATE_THRESHOLD, RISK_STYLES } from '../lib/risk';
import type { FaultInjection } from '../services/analysisEngine';
import { ApiClient, type HealthResponse } from '../services/apiClient';
import { COORDINATOR_WEIGHTS } from '../services/agents/coordinatorAgent';
import { toAppError, type AppError } from '../services/errors';

const FAULTS: Array<{ value: FaultInjection; title: string; description: string }> = [
  { value: 'none', title: 'No fault', description: 'All data sources respond normally.' },
  { value: 'water-timeout', title: 'Water sensor timeout', description: 'The ESP32 sensor stops responding. The Water agent times out and the Coordinator re-weights Air and Waste.' },
  { value: 'air-failure', title: 'Air data source failure', description: 'The air-quality API returns HTTP 503. The analysis continues with reduced confidence.' },
];

const INTEGRATIONS = [
  { agent: 'air' as const, name: 'OpenAQ v3', file: 'backend/services/openaq_service.py', env: 'OPENAQ_API_KEY', status: 'Live when OPENAQ_API_KEY is set on the backend' },
  { agent: 'water' as const, name: 'ESP32 → Firebase / MQTT', file: 'backend/services/water_sensor_service.py', env: 'FIREBASE_DB_URL · MQTT_BROKER_URL', status: 'Demo IoT sensor · interface ready' },
  { agent: 'waste' as const, name: 'YOLO waste detector', file: 'backend/services/waste_detection_service.py', env: 'YOLO_WEIGHTS_PATH', status: 'Simulated detections · interface ready' },
];

export function SettingsPage() {
  const { settings, updateSettings, api } = useSettings();
  const [liveProviders, setLiveProviders] = useState<Record<string, string> | null>(null);

  // Ask the backend which providers it uses for live (non-demo) analyses.
  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((response) => !cancelled && setLiveProviders(response.providers))
      .catch(() => !cancelled && setLiveProviders(null));
    return () => {
      cancelled = true;
    };
  }, [api]);
  const { notify } = useToast();
  const [apiUrl, setApiUrl] = useState(settings.apiBaseUrl);
  const [testing, setTesting] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<AppError | null>(null);

  const testConnection = async () => {
    setTesting(true);
    setHealth(null);
    setHealthError(null);
    try {
      setHealth(await new ApiClient(apiUrl).health());
    } catch (error) {
      setHealthError(toAppError(error));
    } finally {
      setTesting(false);
    }
  };

  const saveUrl = () => {
    if (apiUrl.trim() !== settings.apiBaseUrl) {
      updateSettings({ apiBaseUrl: apiUrl.trim() });
      notify({ tone: 'info', title: 'API endpoint updated', description: apiUrl.trim() || 'Using the Vite proxy (/api → localhost:8000)' });
    }
  };

  return (
    <div className="mx-auto grid max-w-6xl gap-4 lg:grid-cols-2">
      <DashboardCard title="Data mode" subtitle="Where agents get their data" icon={settings.demoMode ? FlaskConical : Server} iconColor={settings.demoMode ? '#2563eb' : '#2563eb'} className="lg:col-span-2">
        <div className="flex flex-col gap-4 md:flex-row md:items-start">
          <div className="flex flex-1 items-start justify-between gap-4 rounded-xl border border-black/[0.06] bg-black/[0.02] p-4">
            <div>
              <p className="flex items-center gap-2 text-sm font-medium text-fg">
                Demo Mode
                {settings.demoMode && (
                  <span className="rounded border border-info/30 bg-info/10 px-1.5 text-[10px] font-semibold tracking-wider text-info">DEMO MODE</span>
                )}
              </p>
              <p className="mt-1 max-w-md text-xs leading-relaxed text-fg-muted">
                Agents run in the browser against realistic mock data. No backend or API keys required — reliable for live presentations. Turn off to call the FastAPI backend.
              </p>
            </div>
            <Switch
              checked={settings.demoMode}
              label="Demo Mode"
              onChange={(value) => {
                updateSettings({ demoMode: value });
                notify({ tone: 'info', title: value ? 'Demo Mode enabled' : 'Live API mode enabled', description: value ? 'Using in-browser agents with mock data.' : 'Agents now run on the FastAPI backend.' });
              }}
            />
          </div>

          <div className={cn('flex-1 rounded-xl border border-black/[0.06] bg-black/[0.02] p-4 transition-opacity', settings.demoMode && 'opacity-60')}>
            <label htmlFor="api-url" className="text-sm font-medium text-fg">
              API base URL
            </label>
            <p className="mt-1 text-xs text-fg-muted">Leave empty to use the dev proxy (/api → http://127.0.0.1:8000).</p>
            <div className="mt-3 flex gap-2">
              <input
                id="api-url"
                value={apiUrl}
                onChange={(event) => setApiUrl(event.target.value)}
                onBlur={saveUrl}
                onKeyDown={(event) => event.key === 'Enter' && saveUrl()}
                placeholder="http://127.0.0.1:8000"
                className="h-9 min-w-0 flex-1 rounded-lg border border-black/10 bg-ink-950/60 px-3 font-mono text-xs text-fg outline-none placeholder:text-fg-subtle focus:border-brand/50"
              />
              <Button size="md" icon={PlugZap} loading={testing} onClick={() => void testConnection()}>
                Test
              </Button>
            </div>
            {health && (
              <div className="mt-3 rounded-lg border border-risk-low/20 bg-risk-low/[0.06] p-3 text-xs">
                <p className="flex items-center gap-1.5 font-medium text-risk-low">
                  <CircleCheck className="size-3.5" /> Connected · {health.service} v{health.version}
                </p>
                <ul className="mt-1.5 space-y-0.5 text-fg-muted">
                  {Object.entries(health.providers).map(([agent, provider]) => (
                    <li key={agent}>
                      <span className="text-fg-subtle capitalize">{agent}:</span> {provider}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {healthError && <ErrorState compact error={healthError} className="mt-3" />}
          </div>
        </div>
      </DashboardCard>

      <AiConfiguration />

      <DashboardCard title="Presentation" subtitle="Agent execution pacing" icon={Gauge} iconColor="#2563eb">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-fg">Simulation speed</p>
            <p className="mt-1 text-xs text-fg-muted">Normal: Air 1s · Water 1s · Waste 1.5s · Coordinator 1s.</p>
          </div>
          <SegmentedControl
            ariaLabel="Simulation speed"
            layoutId="speed"
            options={[
              { value: 'normal', label: 'Normal' },
              { value: 'fast', label: 'Fast' },
            ]}
            value={settings.speed}
            onChange={(speed) => updateSettings({ speed })}
          />
        </div>
      </DashboardCard>

      <DashboardCard title="Resilience testing" subtitle="Inject a fault to show graceful degradation (demo mode)" icon={Zap} iconColor="#d97706">
        <div className="space-y-2" role="radiogroup" aria-label="Fault injection">
          {FAULTS.map((fault) => {
            const active = settings.fault === fault.value;
            return (
              <button
                key={fault.value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => updateSettings({ fault: fault.value })}
                className={cn('flex w-full items-start gap-3 rounded-xl border p-3 text-left transition', active ? 'border-brand/40 bg-brand/[0.06]' : 'border-black/[0.06] hover:border-black/[0.12]')}
              >
                <span className={cn('mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border', active ? 'border-brand' : 'border-black/20')}>
                  {active && <span className="size-2 rounded-full bg-brand" />}
                </span>
                <span>
                  <span className="block text-[13px] font-medium text-fg">{fault.title}</span>
                  <span className="block text-xs text-fg-muted">{fault.description}</span>
                </span>
              </button>
            );
          })}
        </div>
      </DashboardCard>

      <DashboardCard title="Data integrations" subtitle="Mock services behind production-ready interfaces" icon={PlugZap} iconColor="#2563eb">
        <ul className="space-y-2">
          {INTEGRATIONS.map((integration) => {
            const meta = AGENT_META[integration.agent];
            const provider = liveProviders?.[integration.agent];
            const live = provider !== undefined && !/demo|simulated|mock/i.test(provider);
            return (
              <li key={integration.name} className="rounded-xl border border-black/[0.06] bg-black/[0.02] p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-[13px] font-medium text-fg">
                    <meta.icon className="size-4" style={{ color: meta.color }} />
                    {integration.name}
                  </span>
                  <Chip color={live ? '#059669' : '#d97706'}>{live ? 'Live' : 'Mock'}</Chip>
                </div>
                <p className="mt-1 text-xs text-fg-muted">{provider ? `Backend provider: ${provider}` : integration.status}</p>
                <p className="mt-1.5 font-mono text-[10.5px] text-fg-subtle">
                  {integration.file} · {integration.env}
                </p>
              </li>
            );
          })}
        </ul>
      </DashboardCard>

      <DashboardCard title="Risk model" subtitle="Thresholds and coordinator weights" icon={ShieldCheck} iconColor="#059669">
        <div className="grid grid-cols-3 gap-2">
          {[
            { level: 'LOW' as const, range: `< ${MODERATE_THRESHOLD * 100}%` },
            { level: 'MODERATE' as const, range: `${MODERATE_THRESHOLD * 100}–${HIGH_THRESHOLD * 100 - 1}%` },
            { level: 'HIGH' as const, range: `≥ ${HIGH_THRESHOLD * 100}%` },
          ].map((band) => (
            <div key={band.level} className={cn('rounded-xl border border-black/[0.06] p-3', RISK_STYLES[band.level].soft)}>
              <p className={cn('text-xs font-semibold', RISK_STYLES[band.level].text)}>{band.level}</p>
              <p className="mt-1 text-sm text-fg tabular">{band.range}</p>
            </div>
          ))}
        </div>
        <p className="eyebrow mt-4 mb-2">Coordinator weights</p>
        <div className="space-y-1.5">
          {(Object.keys(COORDINATOR_WEIGHTS) as Array<keyof typeof COORDINATOR_WEIGHTS>).map((agent) => (
            <div key={agent} className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-2 text-fg-muted">
                <span className="size-2 rounded-sm" style={{ background: AGENT_META[agent].color }} />
                {AGENT_META[agent].name}
              </span>
              <span className="text-fg tabular">{Math.round(COORDINATOR_WEIGHTS[agent] * 100)}%</span>
            </div>
          ))}
          <p className="pt-1 text-[11px] text-fg-subtle">+3 points per additional correlated HIGH signal.</p>
        </div>
      </DashboardCard>
    </div>
  );
}
