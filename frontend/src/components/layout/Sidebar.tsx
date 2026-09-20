import { AnimatePresence, motion } from 'framer-motion';
import {
  Bell,
  Crosshair,
  FileSearch,
  HardHat,
  FileText,
  LayoutDashboard,
  LogIn,
  Settings as SettingsIcon,
  TrendingUp,
  Workflow,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useAnalysis, type StepStatus } from '../../context/AnalysisContext';
import { useNavigation } from '../../context/NavigationContext';
import { useRole } from '../../context/RoleContext';
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

type Group = { label: string; items: NavEntry[] };

// A worker sees only their own three screens. Keeping the admin entries out of their sidebar is a
// clarity measure, not a security one — the privacy guarantee is enforced by the worker API, which
// never returns raw reports or unpublished hotspots whatever the client asks for.
const WORKER_GROUPS: Group[] = [
  {
    label: 'Worker',
    items: [
      { id: 'worker-report', label: 'Report Issue', icon: HardHat },
      { id: 'worker-map', label: 'Safety Map', icon: Crosshair },
      { id: 'worker-alerts', label: 'Alerts', icon: TrendingUp },
      { id: 'worker-my-reports', label: 'My Reports', icon: FileText },
      { id: 'worker-my-routes', label: 'My Routes', icon: Crosshair },
      { id: 'notifications', label: 'Notifications', icon: Bell },
    ],
  },
];

// The environmental agents (air/water/waste/coordinator) are no longer the product and are out of
// the primary navigation. Their routes still resolve, so a bookmarked URL keeps working.
const GROUPS: Group[] = [
  {
    label: 'Safety Intelligence',
    items: [
      { id: 'safety', label: 'Dashboard', icon: LayoutDashboard },
      { id: 'analyze', label: 'Analyze Report', icon: FileSearch },
      { id: 'patterns', label: 'Pattern Intelligence', icon: TrendingUp },
      { id: 'admin-map', label: 'Safety Map', icon: Crosshair },
      { id: 'admin-worker-routes', label: 'Route Intelligence', icon: TrendingUp },
      { id: 'notifications', label: 'Notifications', icon: Bell },
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
  operational: '#059669',
  running: '#2563eb',
  degraded: '#d97706',
  offline: '#dc2626',
} as const;

const STEP_COLORS: Record<StepStatus, string> = {
  idle: 'rgb(15 23 42 / 0.12)',
  queued: 'rgb(15 23 42 / 0.2)',
  running: '#2563eb',
  complete: '#059669',
  failed: '#dc2626',
  timeout: '#d97706',
};

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { route, navigate } = useNavigation();
  const { state } = useAnalysis();
  const { role } = useRole();
  // A worker's sidebar shows only their three screens. This is clarity, not access control —
  // the worker API is what actually withholds reports and unpublished hotspots.
  const groups = role === 'worker' ? WORKER_GROUPS : GROUPS;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center gap-3 border-b border-black/[0.05] px-5">
        <Logo />
        <div className="leading-tight">
          <p className="text-[15px] font-semibold tracking-tight text-fg">
            EcoSentinel <span className="text-brand">AI</span>
          </p>
          <p className="text-[10.5px] text-fg-subtle">Safety Intelligence</p>
        </div>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-5" aria-label="Main navigation">
        {groups.map((group) => (
          <div key={group.label}>
            <p className="eyebrow mb-1.5 px-3">{group.label}</p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = route === item.id;
                const Icon = item.icon;
                const step = item.agent ? state.steps[item.agent] : null;
                const accent = item.agent ? AGENT_META[item.agent].color : '#2563eb';
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
                        active ? 'text-fg' : 'text-fg-muted hover:bg-black/[0.035] hover:text-fg',
                      )}
                    >
                      {active && (
                        <motion.span
                          layoutId="sidebar-active"
                          className="absolute inset-0 rounded-lg border border-black/[0.07] bg-black/[0.055]"
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
        <button
          type="button"
          onClick={() => {
            navigate('landing');
            onNavigate?.();
          }}
          aria-label="Back to Login"
          className="flex h-9 w-full items-center gap-2.5 rounded-lg border border-black/[0.06] bg-black/[0.025] px-3 text-[13px] font-medium text-fg-muted transition-colors hover:border-black/10 hover:bg-black/[0.05] hover:text-fg"
        >
          <LogIn className="size-4 shrink-0 text-fg-subtle" />
          <span>Back to Login</span>
        </button>
      </div>
    </div>
  );
}

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 border-r border-black/[0.05] bg-ink-950/70 backdrop-blur-xl lg:block">
        <SidebarContent />
      </aside>

      <AnimatePresence>
        {open && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <motion.div className="absolute inset-0 bg-black/60 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
            <motion.aside
              className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-black/[0.06] bg-ink-900"
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', stiffness: 380, damping: 38 }}
            >
              <button type="button" onClick={onClose} className="absolute top-4 right-3 rounded-lg p-2 text-fg-muted hover:bg-black/5" aria-label="Close menu">
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
