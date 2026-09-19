import { AnimatePresence, motion } from 'framer-motion';
import { ArrowUpRight, Brain, ChevronRight, Database, Filter, FlaskConical, ImageIcon, ListChecks, MapPin, Play, Radio, Scale, Search, ShieldAlert, User, type LucideIcon } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useNavigation } from '../../context/NavigationContext';
import { cn, pct } from '../../lib/format';
import type { AgentId } from '../../types/agents';
import { AgentPipelineSpec } from '../agents/AgentDetails';
import { AGENT_META, SPECIALISTS } from '../agents/agentMeta';
import { Button } from '../ui/Button';
import { RiskBadge } from '../ui/RiskBadge';
import { BranchConnector, VerticalConnector } from './Connectors';

/**
 * The nodes mirror the real LangGraph the backend executes
 * (backend/agents/langgraph_orchestrator.py::_build_graph). This diagram is documentation, not
 * decoration: if a stage is added or removed there, it must change here too, or the picture
 * starts lying about what the system does.
 */
type NodeId =
  | 'user'
  | 'inputs'
  | 'triage'
  | AgentId
  | 'risk'
  | 'evidence'
  | 'problems'
  | 'reasoning'
  | 'decision'
  | 'actions';

const SEQUENCE: NodeId[] = [
  'user', 'inputs', 'triage', 'air', 'water', 'waste',
  'coordinator', 'risk', 'evidence', 'problems', 'reasoning', 'decision', 'actions',
];

const INFO: Record<Exclude<NodeId, AgentId>, { eyebrow: string; title: string; icon: LucideIcon; role: string; details?: string[] }> = {
  user: {
    eyebrow: 'Trigger',
    title: 'User',
    icon: User,
    role: 'An operator selects an area and clicks Analyze Area, or uploads an image for inspection. The request is dispatched to the agents — not to a single model.',
  },
  inputs: {
    eyebrow: 'Data sources',
    title: 'Location · Sensor · Image',
    icon: Database,
    role: 'Each specialist owns its own data source behind a swappable service interface. Today they serve realistic mock data; integrations plug in without touching the agents.',
    details: ['OpenAQ → services/openaq_service.py', 'ESP32 → Firebase/MQTT → services/water_sensor_service.py', 'Camera / upload → YOLO → services/waste_detection_service.py'],
  },
  triage: {
    eyebrow: 'Graph node · triage_environment',
    title: 'Environmental triage',
    icon: Filter,
    role: 'Decides which investigations this location warrants, using deterministic availability rules only. A domain is skipped solely when its provider cannot answer — never because a model judged it irrelevant, since skipping a measurement on a guess is how a real exceedance goes unreported.',
  },
  risk: {
    eyebrow: 'Graph node · coordinate',
    title: 'Deterministic risk score',
    icon: ShieldAlert,
    role: 'Weighted aggregation (Air 38% · Water 27% · Waste 35%) plus the cross-signal adjustment produces the overall level. This remains the single risk authority — the decision engine consumes this score and never computes a rival one.',
  },
  evidence: {
    eyebrow: 'Graph node · normalize_evidence',
    title: 'Evidence normalization',
    icon: FlaskConical,
    role: 'Turns every specialist report into one common representation, so later stages never need to know that air measures µg/m³ against a WHO guideline while waste counts objects in a frame. Severity is carried over from the specialists, not recomputed.',
    details: ['Air / PM2.5 → measurement', 'Water / turbidity → measurement', 'Waste / plastic → detection', 'OpenStreetMap → context (severity 0)'],
  },
  problems: {
    eyebrow: 'Graph node · detect_problems',
    title: 'Problem detection',
    icon: Search,
    role: 'Determines which problems the evidence actually supports. Nothing is emitted without at least one supporting evidence id, so a clean location can report no problems rather than having one invented for it.',
  },
  reasoning: {
    eyebrow: 'Graph node · cross_signal_reasoning',
    title: 'Cross-signal reasoning',
    icon: Brain,
    role: 'Finds independent signals that co-occur — elevated particulates alongside mapped industry, litter beside elevated turbidity. Co-occurrence is reported as warranting investigation and never as causation; causality is fixed at "not established".',
  },
  decision: {
    eyebrow: 'Graph nodes · check_data_sufficiency → decision_synthesis',
    title: 'Decision synthesis',
    icon: Scale,
    role: 'Ranks problems deterministically by severity × confidence × evidence strength × persistence, then checks whether the evidence settles the question. A conditional edge routes an under-evidenced analysis to investigation planning instead of a confident-sounding answer.',
  },
  actions: {
    eyebrow: 'Graph node · explain_decision',
    title: 'Investigation plan & explanation',
    icon: ListChecks,
    role: 'Says what is missing, why it matters and which provider can supply it. The deterministic explanation is always present; an optional LLM may add plain-language prose about the finished decision, but cannot change the score, confidence, priorities or evidence.',
  },
};

function FlowNode({
  id,
  selected,
  lit,
  onSelect,
  index,
  className,
}: {
  id: NodeId;
  selected: boolean;
  lit: boolean;
  onSelect: (id: NodeId) => void;
  index: number;
  className?: string;
}) {
  const isAgent = id in AGENT_META;
  const meta = isAgent ? AGENT_META[id as AgentId] : null;
  const info = isAgent ? null : INFO[id as Exclude<NodeId, AgentId>];
  const Icon = meta?.icon ?? info!.icon;
  const color = meta?.color ?? '#2563eb';
  const eyebrow = meta ? (id === 'coordinator' ? 'Orchestrating agent' : 'Specialist') : info!.eyebrow;
  const title = meta ? (id === 'coordinator' ? meta.name : meta.short) : info!.title;

  return (
    <motion.button
      type="button"
      onClick={() => onSelect(id)}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.35 }}
      whileHover={{ y: -2 }}
      aria-pressed={selected}
      className={cn(
        'group relative flex w-full items-center gap-3 rounded-xl border bg-ink-900/70 p-3 text-left transition-colors duration-300',
        selected ? 'bg-black/[0.04]' : 'border-black/[0.08] hover:border-black/[0.16]',
        className,
      )}
      style={selected || lit ? { borderColor: `${color}80`, boxShadow: `0 0 0 1px ${color}30, 0 0 36px -10px ${color}90` } : undefined}
    >
      <span className="relative grid size-9 shrink-0 place-items-center rounded-lg" style={{ background: `${color}14`, color, border: `1px solid ${color}30` }}>
        {lit && <span className="absolute inset-0 animate-pulse-ring rounded-lg" style={{ background: `${color}40` }} />}
        <Icon className="relative size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[10px] font-semibold tracking-[0.12em] text-fg-subtle uppercase">{eyebrow}</span>
        <span className="block truncate text-sm font-medium text-fg">{title}</span>
      </span>
      <ChevronRight className={cn('size-4 shrink-0 text-fg-subtle transition-opacity', selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100')} />
    </motion.button>
  );
}

function NodeDetail({ id }: { id: NodeId }) {
  const { display } = useAnalysis();
  const { navigate } = useNavigation();
  const isAgent = id in AGENT_META;

  if (isAgent) {
    const agent = id as AgentId;
    const meta = AGENT_META[agent];
    const level = agent === 'coordinator' ? display.coordinator?.overallRiskLevel : display[agent]?.riskLevel;
    const score = agent === 'coordinator' ? display.coordinator?.overallScore : display[agent]?.riskScore;
    return (
      <>
        <p className="text-[10.5px] font-semibold tracking-[0.12em] uppercase" style={{ color: meta.color }}>
          {agent === 'coordinator' ? 'Orchestrating agent' : 'Specialist agent'}
        </p>
        <h3 className="mt-1 text-lg font-semibold tracking-tight text-fg">{meta.name}</h3>
        <p className="mt-2 text-sm leading-relaxed text-fg-muted">{meta.role}</p>
        <div className="mt-4">
          <AgentPipelineSpec agent={agent} stacked />
        </div>
        {level && score !== undefined && (
          <div className="mt-4 flex items-center justify-between rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5 text-xs text-fg-subtle">
            Latest output
            <span className="flex items-center gap-2">
              <RiskBadge level={level} />
              <span className="font-semibold text-fg tabular">{pct(score)}%</span>
            </span>
          </div>
        )}
        <Button size="sm" className="mt-4 w-full" iconRight={ArrowUpRight} onClick={() => navigate(meta.route)}>
          Open {meta.short}
        </Button>
      </>
    );
  }

  const info = INFO[id as Exclude<NodeId, AgentId>];
  return (
    <>
      <p className="eyebrow !text-brand">{info.eyebrow}</p>
      <h3 className="mt-1 text-lg font-semibold tracking-tight text-fg">{info.title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-fg-muted">{info.role}</p>
      {info.details && (
        <ul className="mt-4 space-y-1.5">
          {info.details.map((detail) => (
            <li key={detail} className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-2.5 py-1.5 font-mono text-[11px] text-fg-muted">
              {detail}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function ArchitectureFlow() {
  const [selected, setSelected] = useState<NodeId>('coordinator');
  const [playing, setPlaying] = useState<number | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
  }, []);

  const play = () => {
    if (timer.current) window.clearInterval(timer.current);
    let step = 0;
    setPlaying(0);
    setSelected(SEQUENCE[0]);
    timer.current = window.setInterval(() => {
      step += 1;
      if (step >= SEQUENCE.length) {
        if (timer.current) window.clearInterval(timer.current);
        timer.current = null;
        setPlaying(null);
        return;
      }
      setPlaying(step);
      setSelected(SEQUENCE[step]);
    }, 850);
  };

  const litNode = playing === null ? null : SEQUENCE[playing];
  const nodeProps = (id: NodeId) => ({
    id,
    selected: selected === id,
    lit: litNode === id,
    onSelect: (next: NodeId) => {
      if (timer.current) window.clearInterval(timer.current);
      timer.current = null;
      setPlaying(null);
      setSelected(next);
    },
    index: SEQUENCE.indexOf(id),
  });

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="glass p-5 sm:p-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="eyebrow !text-brand">Architecture</p>
            <p className="mt-1 text-sm text-fg-muted">
              Data → Investigators → Evidence → Problems → Decision. <span className="text-fg-subtle">Mirrors the LangGraph the backend runs. Click any node to see its role.</span>
            </p>
          </div>
          <Button size="sm" icon={Play} onClick={play} loading={playing !== null}>
            {playing !== null ? 'Playing…' : 'Play data flow'}
          </Button>
        </div>

        <div className="mx-auto max-w-2xl">
          <div className="mx-auto max-w-xs">
            <FlowNode {...nodeProps('user')} />
          </div>
          <VerticalConnector />
          <div className="mx-auto max-w-sm">
            <FlowNode {...nodeProps('inputs')} />
            <div className="mt-2 flex justify-center gap-1.5 text-[10.5px] text-fg-subtle">
              <span className="inline-flex items-center gap-1 rounded-md border border-black/[0.06] px-1.5 py-0.5"><MapPin className="size-3" />Location</span>
              <span className="inline-flex items-center gap-1 rounded-md border border-black/[0.06] px-1.5 py-0.5"><Radio className="size-3" />Sensor</span>
              <span className="inline-flex items-center gap-1 rounded-md border border-black/[0.06] px-1.5 py-0.5"><ImageIcon className="size-3" />Image</span>
            </div>
          </div>
          <VerticalConnector />
          <div className="mx-auto max-w-xs">
            <FlowNode {...nodeProps('triage')} />
          </div>
          <BranchConnector direction="out" running={playing !== null && playing <= 3} />
          <div className="rounded-2xl border border-dashed border-black/[0.1] p-3 sm:p-4">
            <p className="eyebrow mb-3 text-center">Specialist investigators · run concurrently</p>
            <div className="grid gap-2.5 sm:grid-cols-3">
              {SPECIALISTS.map((agent) => (
                <FlowNode key={agent} {...nodeProps(agent)} />
              ))}
            </div>
          </div>
          <BranchConnector direction="in" running={playing !== null && playing >= 4 && playing <= 6} />
          <div className="mx-auto max-w-sm">
            <FlowNode {...nodeProps('coordinator')} />
          </div>
          <VerticalConnector />
          <div className="mx-auto max-w-xs">
            <FlowNode {...nodeProps('risk')} />
          </div>

          <div className="my-4 rounded-2xl border border-dashed border-brand/25 p-3 sm:p-4">
            <p className="eyebrow mb-3 text-center !text-brand">Decision engine · evidence → problem → decision</p>
            <div className="space-y-0">
              <div className="mx-auto max-w-xs">
                <FlowNode {...nodeProps('evidence')} />
              </div>
              <VerticalConnector />
              <div className="mx-auto max-w-xs">
                <FlowNode {...nodeProps('problems')} />
              </div>
              <VerticalConnector />
              <div className="mx-auto max-w-xs">
                <FlowNode {...nodeProps('reasoning')} />
              </div>
              <VerticalConnector />
              <div className="mx-auto max-w-xs">
                <FlowNode {...nodeProps('decision')} />
              </div>
              {/* The one conditional edge in the graph, drawn so the branch is visible. */}
              <p className="mt-2 text-center text-[10.5px] text-fg-subtle">
                conditional edge · enough evidence? → decision, otherwise → investigation plan
              </p>
            </div>
          </div>

          <div className="mx-auto max-w-xs">
            <FlowNode {...nodeProps('actions')} />
          </div>
        </div>
      </div>

      <aside className="glass h-fit p-5 xl:sticky xl:top-24">
        <AnimatePresence mode="wait">
          <motion.div key={selected} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} transition={{ duration: 0.2 }}>
            <NodeDetail id={selected} />
          </motion.div>
        </AnimatePresence>
      </aside>
    </div>
  );
}
