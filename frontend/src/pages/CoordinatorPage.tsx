import { ArrowUpRight, FileInput, Workflow } from 'lucide-react';
import { AgentPipelineSpec, RESULT_TYPE_NAMES, StructuredOutput } from '../components/agents/AgentDetails';
import { AGENT_META, SPECIALISTS } from '../components/agents/agentMeta';
import { AgentTimeline } from '../components/agents/AgentTimeline';
import { CoordinatorPanel } from '../components/coordinator/CoordinatorPanel';
import { RecommendationsPanel } from '../components/recommendations/RecommendationsPanel';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { RiskBadge } from '../components/ui/RiskBadge';
import { useAnalysis } from '../context/AnalysisContext';
import { useNavigation } from '../context/NavigationContext';
import { pct } from '../lib/format';

export function CoordinatorPage() {
  const { display, failures } = useAnalysis();
  const { navigate } = useNavigation();
  const coordinator = display.coordinator;

  return (
    <div className="space-y-6">
      <CoordinatorPanel />

      <div className="grid gap-4 xl:grid-cols-12">
        <RecommendationsPanel className="xl:col-span-7" />
        <DashboardCard title="Agent interface" subtitle="What the Coordinator consumes and produces" icon={Workflow} iconColor="#2dd4bf" className="xl:col-span-5">
          <AgentPipelineSpec agent="coordinator" stacked />
        </DashboardCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <AgentTimeline agents={['coordinator']} />
        <DashboardCard title="Inputs consumed" subtitle="The Coordinator reads only these structured reports — never raw data" icon={FileInput} iconColor="#2dd4bf">
          <ul className="space-y-2">
            {SPECIALISTS.map((agent) => {
              const report = display[agent];
              const meta = AGENT_META[agent];
              return (
                <li key={agent} className="flex items-center gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
                  <span className="grid size-9 shrink-0 place-items-center rounded-lg" style={{ background: `${meta.color}14`, color: meta.color }}>
                    <meta.icon className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-xs text-fg">{RESULT_TYPE_NAMES[agent]}</p>
                    <p className="truncate text-[11px] text-fg-subtle">
                      {report
                        ? `${report.findings.length} findings · confidence ${pct(report.confidence)}% · weight ${Math.round((coordinator?.contributions.find((c) => c.agent === agent)?.weight ?? 0) * 100)}%`
                        : failures[agent] ?? 'Not received'}
                    </p>
                  </div>
                  {report ? (
                    <div className="text-right">
                      <RiskBadge level={report.riskLevel} />
                      <p className="mt-1 text-xs font-semibold text-fg tabular">{pct(report.riskScore)}%</p>
                    </div>
                  ) : (
                    <RiskBadge level={null} emptyLabel="Missing" />
                  )}
                </li>
              );
            })}
          </ul>
          <Button size="sm" variant="ghost" className="mt-4" iconRight={ArrowUpRight} onClick={() => navigate('how-it-works')}>
            See the full architecture
          </Button>
        </DashboardCard>
      </div>

      {coordinator && <StructuredOutput data={coordinator} typeName="CoordinatorResult" />}
    </div>
  );
}
