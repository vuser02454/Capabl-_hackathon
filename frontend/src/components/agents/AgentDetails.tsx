import { motion } from 'framer-motion';
import { TriangleAlert, Braces, Check, ChevronRight, Copy, Cpu, FileOutput, LogIn, Play, Search, Workflow, Wrench } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useSettings } from '../../context/SettingsContext';
import { cn, formatDateTime, formatValue, pct } from '../../lib/format';
import { MEASUREMENT_STATUS_STYLES } from '../../lib/risk';
import type { AgentId, Measurement, SpecialistAgentId, SpecialistResult } from '../../types/agents';
import { Button } from '../ui/Button';
import { DashboardCard } from '../ui/DashboardCard';
import { ErrorState } from '../ui/ErrorState';
import { LoadingState } from '../ui/LoadingState';
import { Chip, ProgressBar } from '../ui/primitives';
import { RiskBadge } from '../ui/RiskBadge';
import { RiskGauge } from '../ui/RiskGauge';
import { AGENT_META } from './agentMeta';
import { AgentTimeline } from './AgentTimeline';

export const RESULT_TYPE_NAMES: Record<AgentId, string> = {
  air: 'AirAgentResult',
  water: 'WaterAgentResult',
  waste: 'WasteAgentResult',
  coordinator: 'CoordinatorResult',
};

export function AgentPipelineSpec({ agent, stacked = false }: { agent: AgentId; stacked?: boolean }) {
  const meta = AGENT_META[agent];
  const columns = [
    { label: 'Input', icon: LogIn, items: meta.spec.input },
    { label: 'Tools', icon: Wrench, items: meta.spec.tools },
    { label: 'Processing', icon: Cpu, items: meta.spec.processing },
    { label: 'Output', icon: FileOutput, items: meta.spec.output },
  ];
  return (
    <div className={cn('grid gap-2.5', stacked ? 'grid-cols-1' : 'sm:grid-cols-2 lg:grid-cols-4')}>
      {columns.map((column, index) => (
        <motion.div
          key={column.label}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.06 }}
          className="relative rounded-xl border border-white/[0.06] bg-white/[0.02] p-3"
        >
          <div className="flex items-center gap-2 text-[10.5px] font-semibold tracking-[0.12em] uppercase" style={{ color: meta.color }}>
            <column.icon className="size-3.5" />
            {column.label}
          </div>
          <ul className="mt-2 space-y-1">
            {column.items.map((item) => (
              <li key={item} className="flex items-start gap-2 text-xs text-fg-muted">
                <span className="mt-[7px] size-1 shrink-0 rounded-full bg-fg-subtle" />
                {item}
              </li>
            ))}
          </ul>
          {!stacked && index < columns.length - 1 && (
            <span className="absolute top-1/2 -right-[13px] z-10 hidden -translate-y-1/2 rounded-full border border-white/10 bg-ink-900 p-0.5 lg:block">
              <ChevronRight className="size-3 text-fg-subtle" />
            </span>
          )}
        </motion.div>
      ))}
    </div>
  );
}

export function MeasurementTable({ measurements }: { measurements: Measurement[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[540px] text-left text-xs">
        <thead>
          <tr className="border-b border-white/[0.06] text-[10.5px] tracking-wider text-fg-subtle uppercase">
            <th className="py-2 pr-3 font-medium">Parameter</th>
            <th className="py-2 pr-3 font-medium">Value</th>
            <th className="py-2 pr-3 font-medium">Guideline</th>
            <th className="w-44 py-2 pr-3 font-medium">Sub-score</th>
            <th className="py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {measurements.map((m) => {
            const status = MEASUREMENT_STATUS_STYLES[m.status];
            return (
              <tr key={m.key} className="border-b border-white/[0.04] last:border-0">
                <td className="py-2.5 pr-3 font-medium text-fg">{m.label}</td>
                <td className="py-2.5 pr-3 text-fg tabular">
                  {formatValue(m.value)} <span className="text-fg-subtle">{m.value !== null && m.unit}</span>
                </td>
                <td className="py-2.5 pr-3 text-fg-muted tabular">
                  {m.threshold === null ? '—' : `${m.threshold} ${m.unit}`}
                  {m.thresholdLabel && <span className="block text-[10px] text-fg-subtle">{m.thresholdLabel}</span>}
                </td>
                <td className="py-2.5 pr-3">
                  {m.subScore === null ? (
                    <span className="text-fg-subtle">—</span>
                  ) : (
                    <div className="flex items-center gap-2">
                      <ProgressBar value={m.subScore} color={status.color} height={4} />
                      <span className="w-8 text-fg-muted tabular">{pct(m.subScore)}</span>
                    </div>
                  )}
                </td>
                <td className="py-2.5">
                  <span className={cn('inline-flex items-center gap-1.5', status.text)}>
                    <span className="size-1.5 rounded-full" style={{ background: status.color }} />
                    {status.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function highlightJson(json: string) {
  const escaped = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return escaped.replace(/("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g, (match) => {
    let cls = 'text-[#f5b544]';
    if (match.startsWith('"')) cls = match.endsWith(':') ? 'text-[#7dd3fc]' : 'text-[#a7f3d0]';
    else if (match === 'true' || match === 'false') cls = 'text-[#c79bff]';
    else if (match === 'null') cls = 'text-fg-subtle';
    return `<span class="${cls}">${match}</span>`;
  });
}

export function StructuredOutput({ data, typeName, title = 'Structured output' }: { data: unknown; typeName: string; title?: string }) {
  const [copied, setCopied] = useState(false);
  const json = useMemo(
    () =>
      JSON.stringify(
        data,
        (key, value) => (key === 'detections' && Array.isArray(value) && value.length > 3 ? [...value.slice(0, 3), `… ${value.length - 3} more detections`] : value),
        2,
      ),
    [data],
  );
  const html = useMemo(() => highlightJson(json), [json]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <DashboardCard
      title={title}
      subtitle={<span className="font-mono">{typeName}</span>}
      icon={Braces}
      actions={
        <Button size="sm" variant="ghost" icon={copied ? Check : Copy} onClick={() => void copy()}>
          {copied ? 'Copied' : 'Copy JSON'}
        </Button>
      }
    >
      <pre
        className="max-h-96 overflow-auto rounded-xl border border-white/[0.05] bg-ink-950/70 p-4 font-mono text-[11.5px] leading-relaxed text-fg-muted"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </DashboardCard>
  );
}

export function FindingsCard({ result, className }: { result: SpecialistResult; className?: string }) {
  const meta = AGENT_META[result.agent];
  const maxImpact = Math.max(...result.findings.map((finding) => finding.impact), 0.01);
  const anomalies = result.agent === 'air' ? result.anomalies : [];

  return (
    <DashboardCard title="Findings" subtitle="Evidence handed to the Coordinator" icon={Search} iconColor={meta.color} className={className}>
      {result.findings.length ? (
        <ul className="space-y-2">
          {result.findings.map((finding) => (
            <li key={finding.code} className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-fg">{finding.label}</p>
                <span className="font-mono text-[10.5px] text-fg-subtle">{finding.code}</span>
              </div>
              <p className="mt-0.5 text-xs text-fg-muted">{finding.detail}</p>
              <ProgressBar value={finding.impact / maxImpact} color={meta.color} height={3} className="mt-2" />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-fg-subtle">No indicators above guideline thresholds.</p>
      )}
      {[...anomalies, ...result.warnings].map((note) => (
        <p key={note} className="mt-3 flex items-start gap-1.5 text-xs text-risk-moderate">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          {note}
        </p>
      ))}
    </DashboardCard>
  );
}

export function AgentDetailLayout({ agent, children }: { agent: SpecialistAgentId; children?: ReactNode }) {
  const { display, pending, failures, runAnalysis, state } = useAnalysis();
  const { settings, updateSettings } = useSettings();
  const result = display[agent];
  const meta = AGENT_META[agent];
  const Icon = meta.icon;
  const failure = failures[agent];

  return (
    <div className="space-y-6">
      <DashboardCard accent={meta.color} bodyClassName="p-5 sm:p-6">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-1 items-start gap-4">
            <span className="grid size-14 shrink-0 place-items-center rounded-2xl" style={{ background: `${meta.color}14`, color: meta.color, border: `1px solid ${meta.color}30` }}>
              <Icon className="size-7" />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold tracking-tight text-fg">{meta.name}</h2>
                {result && !pending[agent] && <RiskBadge level={result.riskLevel} suffix="RISK" size="md" />}
                {result?.isMock && <Chip>Mock data source</Chip>}
                {result && !result.isMock && <Chip color="#34d399">Live data</Chip>}
              </div>
              <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-fg-muted">{meta.role}</p>
              {result && (
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-fg-subtle">
                  <span>
                    Source <span className="text-fg-muted">{result.dataSource}</span>
                  </span>
                  <span>
                    Location <span className="text-fg-muted">{result.location}</span>
                  </span>
                  <span>
                    Updated <span className="text-fg-muted">{formatDateTime(result.timestamp)}</span>
                  </span>
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-5 lg:border-l lg:border-white/[0.06] lg:pl-6">
            {result ? <RiskGauge score={result.riskScore} level={result.riskLevel} size={104} stroke={8} /> : <div className="skeleton size-[104px] !rounded-full" />}
            <div className="space-y-2.5">
              <div>
                <p className="eyebrow">Confidence</p>
                <p className="text-xl font-semibold text-fg tabular">{result ? `${pct(result.confidence)}%` : '—'}</p>
              </div>
              <Button size="sm" icon={Play} loading={state.phase === 'running'} onClick={() => void runAnalysis()}>
                Re-run agents
              </Button>
            </div>
          </div>
        </div>
      </DashboardCard>

      {failure && (
        <ErrorState
          compact
          title={`${meta.name} did not report`}
          message={failure}
          onRetry={() => void runAnalysis()}
          onSwitchToDemo={settings.demoMode ? undefined : () => updateSettings({ demoMode: true })}
        />
      )}

      <DashboardCard title="Agent interface" subtitle="Structured input → tools → processing → output" icon={Workflow} iconColor={meta.color}>
        <AgentPipelineSpec agent={agent} />
      </DashboardCard>

      {!result && !failure && <LoadingState variant="block" label={pending[agent] ? `${meta.name} running…` : 'Waiting for analysis…'} />}

      {children}

      {result && (
        <div className="grid gap-4 xl:grid-cols-2">
          <AgentTimeline agents={[agent]} />
          <FindingsCard result={result} />
        </div>
      )}

      {result && <StructuredOutput data={result} typeName={RESULT_TYPE_NAMES[agent]} />}
    </div>
  );
}
