/**
 * Analyze Safety Report — paste a report, watch four agents work, read the evidence.
 *
 * The layout puts the classification and the reasoning that produced it side by side on purpose.
 * A risk level with no visible basis is something a safety officer has to either trust blindly or
 * ignore; showing which phrase scored what makes it possible to disagree with, which is the only
 * way a screening tool earns its place.
 */
import { AlertTriangle, ClipboardList, FileText, Loader2, ShieldCheck, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { AgentTrace } from '../components/safety/AgentTrace';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { DataModeBadge } from '../components/ui/DataModeBadge';
import { Chip } from '../components/ui/primitives';
import { RiskBadge } from '../components/ui/RiskBadge';
import { RiskGauge } from '../components/ui/RiskGauge';
import { useSettings } from '../context/SettingsContext';
import { toDisplayRisk, type SafetyAnalysisResult } from '../types/safety';

const DEMO_REPORT =
  'At approximately 10:30 AM, a worker nearly slipped in the loading bay after oil leaked from a ' +
  'forklift. No warning signage was placed around the affected area. The worker was not injured.';

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === '') return null;
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p className="mt-0.5 text-sm text-fg">{value}</p>
    </div>
  );
}

export function AnalyzeReportPage() {
  const { api } = useSettings();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SafetyAnalysisResult | null>(null);

  const analyze = async () => {
    const body = text.trim();
    if (!body) {
      setError('Enter a safety report before analysing.');
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.analyzeSafetyReport(body, true));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Analysis failed.');
    } finally {
      setBusy(false);
    }
  };

  const analysis = result?.analysis;
  const extraction = result?.extraction;
  const advice = result?.recommendations;

  return (
    <div className="space-y-4">
      <DashboardCard
        title="Analyze Safety Report"
        subtitle="Free-text incident, near-miss or observation report"
        icon={FileText}
        iconColor="#2563eb"
        actions={
          <Button size="sm" variant="ghost" onClick={() => setText(DEMO_REPORT)} disabled={busy}>
            Use example
          </Button>
        }
      >
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={5}
          placeholder="Paste a safety report…"
          className="w-full resize-y rounded-xl border border-black/[0.08] bg-black/[0.02] px-3.5 py-3 text-sm text-fg outline-none transition placeholder:text-fg-subtle focus:border-brand/40 focus:bg-black/[0.03]"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-[11px] text-fg-subtle">
            Risk level is decided by deterministic rules; the language model only writes the
            explanation.
          </p>
          <Button variant="primary" icon={busy ? Loader2 : Sparkles} loading={busy} onClick={() => void analyze()}>
            {busy ? 'Analysing…' : 'Analyze Report'}
          </Button>
        </div>
        {error && (
          <p className="mt-3 rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-xs text-risk-high">
            {error}
          </p>
        )}
      </DashboardCard>

      {result && analysis && extraction && advice && (
        <>
          <div className="grid gap-4 xl:grid-cols-5">
            <DashboardCard
              title="Risk Classification"
              subtitle={`Score ${analysis.riskScore}/100 · confidence ${Math.round(analysis.confidence * 100)}%`}
              icon={AlertTriangle}
              iconColor="#2563eb"
              className="xl:col-span-2"
              actions={<RiskBadge level={toDisplayRisk(analysis.riskLevel)} suffix="RISK" size="md" />}
            >
              <div className="flex items-center gap-5">
                <RiskGauge score={analysis.riskScore / 100} level={toDisplayRisk(analysis.riskLevel)} size={104} stroke={8} />
                <div className="min-w-0 space-y-2.5">
                  <Field label="Summary" value={extraction.summary} />
                  <Field label="Location" value={result.report.location ?? 'Not stated'} />
                  <Field label="Root cause" value={extraction.rootCause ?? 'Not stated in report'} />
                </div>
              </div>

              {analysis.ruleBasis.forcedHigh && (
                <p className="mt-3 rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-xs text-risk-high">
                  Escalated to HIGH by a critical signal, regardless of score.
                </p>
              )}
              {analysis.repeatHits > 0 && (
                <p className="mt-2 rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-xs text-risk-moderate">
                  {analysis.repeatHits} prior report{analysis.repeatHits === 1 ? '' : 's'} describe the
                  same hazard at this location — recurrence raised the score.
                </p>
              )}
              <p className="mt-3 text-[10.5px] leading-relaxed text-fg-subtle">
                Thresholds are application-level demo rules (HIGH ≥ {analysis.ruleBasis.highThreshold},
                MEDIUM ≥ {analysis.ruleBasis.mediumThreshold}), not a regulatory classification.
              </p>
            </DashboardCard>

            <DashboardCard
              title="Why this classification"
              subtitle="Each point traced to a phrase in the report"
              icon={ShieldCheck}
              iconColor="#2563eb"
              className="xl:col-span-3"
              actions={
                <DataModeBadge
                  tone={analysis.narrativeSource === 'llm' ? 'live' : 'historical'}
                  label={analysis.narrativeSource === 'llm' ? 'LLM explanation' : 'Rule-generated'}
                  size="sm"
                />
              }
            >
              <ol className="space-y-1.5">
                {analysis.reasoning.map((line, index) => (
                  <li key={index} className="flex gap-2 text-[13px] leading-relaxed text-fg-muted">
                    <span className="font-mono text-[10px] text-fg-subtle">{index + 1}</span>
                    <span>{line}</span>
                  </li>
                ))}
              </ol>

              {analysis.contributions.length > 0 && (
                <div className="mt-4">
                  <p className="eyebrow mb-1.5">Scored factors</p>
                  <ul className="space-y-1">
                    {analysis.contributions.map((contribution, index) => (
                      <li
                        key={index}
                        className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2"
                      >
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="text-xs text-fg">{contribution.factor}</span>
                          <span className="shrink-0 font-mono text-[11px] text-fg-muted">
                            +{contribution.points}
                          </span>
                        </div>
                        {contribution.evidence && (
                          <p className="mt-1 text-[10.5px] text-fg-subtle italic">{contribution.evidence}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </DashboardCard>
          </div>

          <div className="grid gap-4 xl:grid-cols-5">
            <DashboardCard
              title="Extracted Risk Factors"
              subtitle="Grounded in the report — absent information stays absent"
              icon={ClipboardList}
              iconColor="#2563eb"
              className="xl:col-span-2"
            >
              <div className="flex flex-wrap gap-1.5">
                {extraction.riskFactors.length ? (
                  extraction.riskFactors.map((factor) => <Chip key={factor}>{factor}</Chip>)
                ) : (
                  <p className="text-xs text-fg-subtle">No recognised risk factors.</p>
                )}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <Field label="Department" value={result.report.department ?? 'Not stated'} />
                <Field label="Equipment" value={result.report.equipment ?? 'Not stated'} />
                <Field label="Incident type" value={result.report.incidentType} />
                <Field
                  label="Injury"
                  value={
                    extraction.injuryPresent === null
                      ? 'Not stated'
                      : extraction.injuryPresent
                        ? 'Reported'
                        : 'None reported'
                  }
                />
              </div>
            </DashboardCard>

            <DashboardCard
              title="Recommended Actions"
              subtitle={`Priority: ${advice.priority}`}
              icon={ShieldCheck}
              iconColor="#2563eb"
              className="xl:col-span-3"
              actions={
                advice.humanReviewRequired ? (
                  <span className="rounded-full border border-risk-high/25 bg-risk-high/10 px-2.5 py-1 text-[10px] font-semibold tracking-wider text-risk-high uppercase">
                    Human review required
                  </span>
                ) : null
              }
            >
              <ol className="space-y-1.5">
                {advice.recommendedActions.map((action, index) => (
                  <li key={index} className="flex gap-2 text-[13px] leading-relaxed text-fg">
                    <span className="font-mono text-[10px] text-fg-subtle">{index + 1}</span>
                    <span>{action}</span>
                  </li>
                ))}
              </ol>
              {advice.preventiveActions.length > 0 && (
                <div className="mt-4">
                  <p className="eyebrow mb-1.5">Preventive</p>
                  <ul className="space-y-1">
                    {advice.preventiveActions.map((action, index) => (
                      <li key={index} className="text-[12.5px] leading-relaxed text-fg-muted">
                        · {action}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="mt-4 rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2 text-[10.5px] leading-relaxed text-fg-subtle">
                {result.disclaimer}
              </p>
            </DashboardCard>
          </div>

          <AgentTrace trace={result.trace} />
        </>
      )}
    </div>
  );
}
