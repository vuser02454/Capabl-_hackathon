import { Download, FileBraces, FileText, Printer, Sparkles } from 'lucide-react';
import type { ReactNode } from 'react';
import { MeasurementTable } from '../components/agents/AgentDetails';
import { AGENT_META } from '../components/agents/agentMeta';
import { CategoryBreakdown } from '../components/agents/DetectionViewer';
import { ContributionBar } from '../components/coordinator/CoordinatorPanel';
import { Logo } from '../components/layout/Logo';
import { RecommendationCard } from '../components/recommendations/RecommendationCard';
import { Button } from '../components/ui/Button';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { RiskBadge } from '../components/ui/RiskBadge';
import { useAnalysis } from '../context/AnalysisContext';
import { useToast } from '../context/ToastContext';
import { formatDateTime, pct } from '../lib/format';
import { buildReportJson, buildReportText, downloadFile, reportFilename } from '../services/reportExport';
import type { Finding, SpecialistAgentId, SpecialistResult } from '../types/agents';

function Section({ index, title, agent, children }: { index: string; title: string; agent?: SpecialistAgentId; children: ReactNode }) {
  const meta = agent ? AGENT_META[agent] : null;
  return (
    <section className="p-6 sm:p-8">
      <div className="mb-4 flex items-center gap-3">
        <span className="font-mono text-xs text-fg-subtle">{index}</span>
        {meta && <meta.icon className="size-4" style={{ color: meta.color }} />}
        <h3 className="text-base font-semibold tracking-tight text-fg">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function Summary({ result, label }: { result: SpecialistResult | null; label: string }) {
  if (!result) return <p className="text-sm text-risk-high">{label} report unavailable for this analysis.</p>;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 text-sm text-fg-muted">
      <RiskBadge level={result.riskLevel} size="md" suffix="RISK" />
      <span>
        Risk score <span className="font-semibold text-fg tabular">{pct(result.riskScore)}%</span>
      </span>
      <span>
        Confidence <span className="font-semibold text-fg tabular">{pct(result.confidence)}%</span>
      </span>
      <span className="text-fg-subtle">Source: {result.dataSource}</span>
    </div>
  );
}

function Findings({ findings, warnings }: { findings: Finding[]; warnings: string[] }) {
  if (!findings.length && !warnings.length) return null;
  return (
    <ul className="mt-4 space-y-1.5">
      {findings.map((finding) => (
        <li key={finding.code} className="text-xs text-fg-muted">
          <span className="font-medium text-fg">{finding.label}</span> — {finding.detail}
        </li>
      ))}
      {warnings.map((warning) => (
        <li key={warning} className="text-xs text-risk-moderate">
          ⚠ {warning}
        </li>
      ))}
    </ul>
  );
}

export function ReportsPage() {
  const { state, runAnalysis } = useAnalysis();
  const { notify } = useToast();
  const result = state.result;

  if (!result) {
    return state.error ? <ErrorState error={state.error} onRetry={() => void runAnalysis()} /> : <LoadingState variant="block" label="Preparing report…" />;
  }

  const { air, water, waste, coordinator } = result;

  const exportReport = (format: 'json' | 'txt') => {
    try {
      if (format === 'json') downloadFile(reportFilename(result, 'json'), buildReportJson(result), 'application/json');
      else downloadFile(reportFilename(result, 'txt'), buildReportText(result), 'text/plain;charset=utf-8');
      notify({ tone: 'success', title: 'Report exported', description: reportFilename(result, format) });
    } catch {
      notify({ tone: 'error', title: 'Export failed', description: 'The browser blocked the download. Please try again.' });
    }
  };

  return (
    // Tall element: skip backdrop blur, which can exceed GPU layer limits and render blank.
    <article className="glass mx-auto max-w-5xl overflow-hidden !bg-ink-900/85" style={{ backdropFilter: 'none', WebkitBackdropFilter: 'none' }}>
      <header className="border-b border-black/[0.06] bg-linear-to-br from-brand/[0.07] via-transparent to-transparent p-6 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5">
              <Logo size={28} />
              <span className="eyebrow">EcoSentinel AI · Multi-agent assessment</span>
            </div>
            <h2 className="mt-4 text-2xl font-semibold tracking-tight text-fg">Environmental Risk Report</h2>
            <p className="mt-1 font-mono text-[11px] text-fg-subtle">
              Report {result.analysisId} · {result.mode === 'demo' ? 'Demo mode (mock data)' : 'Live API'}
            </p>
          </div>
          <div className="no-print flex flex-wrap gap-2">
            <Button variant="primary" icon={Download} onClick={() => exportReport('json')}>
              Export Report
            </Button>
            <Button icon={FileText} onClick={() => exportReport('txt')} aria-label="Export as text">
              .txt
            </Button>
            <Button variant="ghost" icon={Printer} onClick={() => window.print()} aria-label="Print report" />
          </div>
        </div>
        <dl className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            { label: 'Location', value: <span className="text-fg">{result.location}</span> },
            { label: 'Date', value: <span className="text-fg">{formatDateTime(result.completedAt)}</span> },
            {
              label: 'Overall Risk',
              value: (
                <span className="flex items-center gap-2">
                  <RiskBadge level={coordinator.overallRiskLevel} size="md" />
                  <span className="text-fg tabular">{pct(coordinator.overallScore)}%</span>
                </span>
              ),
            },
            { label: 'Confidence', value: <span className="text-fg tabular">{pct(coordinator.confidence)}%</span> },
          ].map((item) => (
            <div key={item.label} className="rounded-xl border border-black/[0.06] bg-ink-950/30 px-3 py-2.5">
              <dt className="eyebrow">{item.label}</dt>
              <dd className="mt-1 text-sm font-medium">{item.value}</dd>
            </div>
          ))}
        </dl>
      </header>

      <div className="divide-y divide-black/[0.05]">
        <Section index="01" title="Air Assessment" agent="air">
          <Summary result={air} label="Air" />
          {air && (
            <>
              <MeasurementTable measurements={air.measurements} />
              <Findings findings={air.findings} warnings={[...air.anomalies, ...air.warnings]} />
            </>
          )}
        </Section>

        <Section index="02" title="Water Assessment" agent="water">
          <Summary result={water} label="Water" />
          {water && (
            <>
              <MeasurementTable measurements={water.measurements} />
              <Findings findings={water.findings} warnings={water.warnings} />
            </>
          )}
        </Section>

        <Section index="03" title="Waste Assessment" agent="waste">
          <Summary result={waste} label="Waste" />
          {waste && (
            <>
              <p className="text-sm text-fg-muted">
                <span className="text-2xl font-semibold text-fg">{waste.totalObjects}</span> objects detected at {waste.sourceName} · density index {waste.densityIndex.toFixed(2)}
              </p>
              <CategoryBreakdown counts={waste.counts} className="mt-4 max-w-md" />
              <Findings findings={waste.findings} warnings={waste.warnings} />
            </>
          )}
        </Section>

        <Section index="04" title="Cross-Signal Reasoning">
          <p className="text-sm leading-relaxed text-fg">{coordinator.reasoning}</p>
          {coordinator.crossSignalInsights.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {coordinator.crossSignalInsights.map((insight) => (
                <li key={insight} className="flex gap-2 text-xs text-fg-muted">
                  <Sparkles className="mt-0.5 size-3.5 shrink-0 text-brand" />
                  {insight}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-5 grid gap-5 md:grid-cols-2">
            <div>
              <p className="eyebrow mb-2">Key contributing factors</p>
              <ul className="space-y-1.5">
                {coordinator.contributingFactors.map((factor) => (
                  <li key={factor.label} className="flex items-start gap-2 text-sm text-fg">
                    <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: AGENT_META[factor.agent].color }} />
                    <span>
                      {factor.label} <span className="text-xs text-fg-subtle">— {factor.detail}</span>
                    </span>
                  </li>
                ))}
                {coordinator.contributingFactors.length === 0 && <li className="text-xs text-fg-subtle">None identified.</li>}
              </ul>
            </div>
            <ContributionBar coordinator={coordinator} />
          </div>
        </Section>

        <Section index="05" title="Recommended Actions">
          <ul className="space-y-2.5">
            {coordinator.recommendations.map((recommendation, index) => (
              <RecommendationCard key={recommendation.id} recommendation={recommendation} index={index} interactive={false} />
            ))}
          </ul>
        </Section>
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-black/[0.06] px-6 py-4 text-[11px] text-fg-subtle sm:px-8">
        <span className="flex items-center gap-1.5">
          <FileBraces className="size-3.5" />
          Structured source: AnalysisResult · {result.runs.length} agent runs
        </span>
        <span>Generated by EcoSentinel AI multi-agent system{result.air?.isMock ? ' · mock data for demonstration' : ''}</span>
      </footer>
    </article>
  );
}
