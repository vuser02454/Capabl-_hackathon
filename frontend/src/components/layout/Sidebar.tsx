import { AnimatePresence, motion } from 'framer-motion';
import {
  FileText,
  LayoutDashboard,
  Map as MapIcon,
  Settings as SettingsIcon,
  Workflow,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useAnalysis, type StepStatus } from '../../context/AnalysisContext';
import { useNavigation } from '../../context/NavigationContext';
import { cn } from '../../lib/format';
import type { RouteId } from '../../lib/routes';
import type { AgentId } from '../../types/agents';
import { AGENT_META } from '../agents/agentMeta';
import { StatusDot } from '../ui/primitives';
import { Logo } from './Logo';

interface NavEntry {
  id: RouteId;
  label: string;
  icon: LucideIcon;
  agent?: AgentId;
}

const GROUPS: Array<{ label: string; items: NavEntry[] }> = [
  {
    label: 'Monitor',
    items: [
      { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
      { id: 'map', label: 'Environmental Map', icon: MapIcon },
    ],
  },
  {
    label: 'Agents',
    items: [
      { id: 'air', label: 'Air Agent', icon: AGENT_META.air.icon, agent: 'air' },
      { id: 'water', label: 'Water Agent', icon: AGENT_META.water.icon, agent: 'water' },
      { id: 'waste', label: 'Waste Agent', icon: AGENT_META.waste.icon, agent: 'waste' },
      { id: 'coordinator', label: 'Coordinator', icon: AGENT_META.coordinator.icon, agent: 'coordinator' },
    ],
  },
  {
    label: 'Workspace',
    items: [
      { id: 'reports', label: 'Reports', icon: FileText },
      { id: 'settings', label: 'Settings', icon: SettingsIcon },
      { id: 'how-it-works', label: 'How it works', icon: Workflow },
    ],
  },
];

export const STATUS_TONE_COLORS = {
  operational: '#34d399',
  running: '#2dd4bf',
  degraded: '#f5b544',
  offline: '#f26b6b',
} as const;

const STEP_COLORS: Record<StepStatus, string> = {
  idle: 'rgb(255 255 255 / 0.12)',
  queued: 'rgb(255 255 255 / 0.2)',
  running: '#2dd4bf',
  complete: '#34d399',
  failed: '#f26b6b',
  timeout: '#f5b544',
};

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { route, navigate } = useNavigation();
  const { systemStatus, state } = useAnalysis();

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center gap-3 border-b border-white/[0.05] px-5">
        <Logo />
        <div className="leading-tight">
          <p className="text-[15px] font-semibold tracking-tight text-fg">
            EcoSentinel <span className="text-brand">AI</span>
          </p>
          <p className="text-[10.5px] text-fg-subtle">Environmental intelligence</p>
        </div>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-5" aria-label="Main navigation">
        {GROUPS.map((group) => (
          <div key={group.label}>
            <p className="eyebrow mb-1.5 px-3">{group.label}</p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = route === item.id;
                const Icon = item.icon;
                const step = item.agent ? state.steps[item.agent] : null;
                const accent = item.agent ? AGENT_META[item.agent].color : '#2dd4bf';
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => {
                        navigate(item.id);
                        onNavigate?.();
                      }}
                      aria-current={active ? 'page' : undefined}
                      className={cn(
                        'group relative flex h-9 w-full items-center gap-3 rounded-lg px-3 text-[13px] font-medium transition-colors',
                        active ? 'text-fg' : 'text-fg-muted hover:bg-white/[0.035] hover:text-fg',
                      )}
                    >
                      {active && (
                        <motion.span
                          layoutId="sidebar-active"
                          className="absolute inset-0 rounded-lg border border-white/[0.07] bg-white/[0.055]"
                          transition={{ type: 'spring', stiffness: 480, damping: 40 }}
                        >
                          <span className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full" style={{ background: accent }} />
                        </motion.span>
                      )}
                      <Icon className="relative size-4 shrink-0 transition-colors" style={{ color: active ? accent : undefined }} />
                      <span className="relative flex-1 truncate text-left">{item.label}</span>
                      {step && (
                        <span className="relative" title={`Agent ${step.status}`}>
                          {step.status === 'running' ? (
                            <StatusDot color={STEP_COLORS.running} size={6} />
                          ) : (
                            <span className="block size-1.5 rounded-full" style={{ background: STEP_COLORS[step.status] }} />
                          )}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="p-3">
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.025] p-3.5">
          <p className="eyebrow">System Status</p>
          <div className="mt-2 flex items-center gap-2 text-xs font-medium text-fg">
            <StatusDot color={STATUS_TONE_COLORS[systemStatus.tone]} pulse={systemStatus.tone !== 'offline'} />
            {systemStatus.label}
          </div>
          <div className="mt-3 grid grid-cols-4 gap-1" aria-hidden>
            {(['air', 'water', 'waste', 'coordinator'] as AgentId[]).map((agent) => (
              <span key={agent} className="h-1 rounded-full transition-colors duration-500" style={{ background: STEP_COLORS[state.steps[agent].status] }} />
            ))}
          </div>
          <div className="mt-1.5 grid grid-cols-4 gap-1 text-center text-[9px] text-fg-subtle">
            <span>AIR</span>
            <span>WATER</span>
            <span>WASTE</span>
            <span>COORD</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 border-r border-white/[0.05] bg-ink-950/70 backdrop-blur-xl lg:block">
        <SidebarContent />
      </aside>

      <AnimatePresence>
        {open && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <motion.div className="absolute inset-0 bg-black/60 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
            <motion.aside
              className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-white/[0.06] bg-ink-900"
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', stiffness: 380, damping: 38 }}
            >
              <button type="button" onClick={onClose} className="absolute top-4 right-3 rounded-lg p-2 text-fg-muted hover:bg-white/5" aria-label="Close menu">
                <X className="size-4" />
              </button>
              <SidebarContent onNavigate={onClose} />
            </motion.aside>
          </div>
        )}
      </AnimatePresence>
    </>
  );
}
