import { Bot, Check, X } from 'lucide-react';
import { AGENT_META } from '../components/agents/agentMeta';
import { ArchitectureFlow } from '../components/architecture/ArchitectureFlow';
import { DashboardCard } from '../components/ui/DashboardCard';
import { SectionHeader } from '../components/ui/primitives';
import type { AgentId } from '../types/agents';

const CONTRACTS: Array<{ agent: AgentId; name: string; fields: string[] }> = [
  { agent: 'air', name: 'AirAgentResult', fields: ['riskLevel: RiskLevel', 'riskScore: number', 'pm25 · pm10 · no2 · o3', 'aqi · dominantPollutant', 'anomalies: string[]', 'findings: Finding[]'] },
  { agent: 'water', name: 'WaterAgentResult', fields: ['riskLevel: RiskLevel', 'riskScore: number', 'ph · turbidity · temperature', "sensorStatus: 'online' | 'degraded'", 'warnings: string[]', 'findings: Finding[]'] },
  { agent: 'waste', name: 'WasteAgentResult', fields: ['riskLevel: RiskLevel', 'riskScore: number', 'totalObjects: number', 'counts: { plastic, paper, other }', 'detections: Detection[]', 'densityIndex: number'] },
  { agent: 'coordinator', name: 'CoordinatorResult', fields: ['overallRiskLevel · overallScore', 'confidence: number', 'reasoning · crossSignalInsights', 'contributingFactors[]', 'contributions: SignalContribution[]', 'recommendations: Recommendation[]'] },
];

export function HowItWorksPage() {
  return (
    <div className="space-y-8">
      <ArchitectureFlow />

      <div className="grid gap-4 md:grid-cols-2">
        <DashboardCard title="Not a chatbot" icon={X} iconColor="#dc2626">
          <p className="font-mono text-sm text-fg-muted">User → LLM → Answer</p>
          <p className="mt-2 text-xs leading-relaxed text-fg-subtle">A single model sees everything at once, so no source can be audited, swapped or trusted on its own.</p>
        </DashboardCard>
        <DashboardCard title="A multi-agent system" icon={Check} iconColor="#059669">
          <p className="font-mono text-sm text-fg">Data → Specialist Agents → Coordinator → Decision</p>
          <p className="mt-2 text-xs leading-relaxed text-fg-subtle">
            Each agent owns one data source and emits a typed report. The Coordinator consumes only those reports, so a failing sensor degrades one input — not the decision.
          </p>
        </DashboardCard>
      </div>

      <section className="space-y-4">
        <SectionHeader eyebrow="Structured contracts" title="Agent outputs are typed, not free text" subtitle="Shared between frontend/src/types/agents.ts and backend/schemas.py" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {CONTRACTS.map((contract) => {
            const meta = AGENT_META[contract.agent];
            return (
              <DashboardCard key={contract.name} accent={meta.color} bodyClassName="p-4">
                <div className="flex items-center gap-2">
                  <meta.icon className="size-4" style={{ color: meta.color }} />
                  <p className="font-mono text-[13px] font-medium text-fg">{contract.name}</p>
                </div>
                <pre className="mt-3 overflow-x-auto rounded-lg border border-black/[0.05] bg-ink-950/60 p-3 font-mono text-[11px] leading-relaxed text-fg-muted">
                  {'{\n'}
                  {contract.fields.map((field) => `  ${field}\n`).join('')}
                  {'}'}
                </pre>
              </DashboardCard>
            );
          })}
        </div>
        <p className="flex items-center gap-2 text-xs text-fg-subtle">
          <Bot className="size-3.5" /> Swap mock sources for OpenAQ, ESP32 telemetry or YOLO without changing any agent contract.
        </p>
      </section>
    </div>
  );
}
