import { AnimatePresence, motion } from 'framer-motion';
import { FlaskConical, Menu, RefreshCw, Server } from 'lucide-react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useNavigation } from '../../context/NavigationContext';
import { useSettings } from '../../context/SettingsContext';
import { useClock } from '../../hooks/useClock';
import { cn, formatClock, formatLongDate } from '../../lib/format';
import { PAGE_TITLES } from '../../lib/routes';
import { StatusDot } from '../ui/primitives';
import { STATUS_TONE_COLORS } from './Sidebar';

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const { route, navigate } = useNavigation();
  const { title, subtitle } = PAGE_TITLES[route];
  const now = useClock();
  const { runAnalysis, state, systemStatus } = useAnalysis();
  const { settings } = useSettings();
  const running = state.phase === 'running';

  return (
    <header className="sticky top-0 z-30 border-b border-black/[0.05] bg-ink-950/75 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button type="button" onClick={onMenu} className="-ml-1 rounded-lg p-2 text-fg-muted hover:bg-black/5 hover:text-fg lg:hidden" aria-label="Open menu">
          <Menu className="size-5" />
        </button>

        <div className="min-w-0 flex-1">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={route} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.18 }}>
              <h1 className="truncate text-base font-semibold tracking-tight text-fg sm:text-lg">{title}</h1>
              <p className="hidden truncate text-xs text-fg-subtle sm:block">{subtitle}</p>
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <button
            type="button"
            onClick={() => navigate('settings')}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] font-semibold tracking-[0.1em] transition hover:brightness-125',
              settings.demoMode ? 'border-info/30 bg-info/10 text-info' : 'border-brand/30 bg-brand/10 text-brand',
            )}
            title="Change data mode in Settings"
          >
            {settings.demoMode ? <FlaskConical className="size-3" /> : <Server className="size-3" />}
            {settings.demoMode ? 'DEMO MODE' : 'LIVE API'}
          </button>

          <div className="hidden flex-col items-end leading-tight md:flex">
            <span className="text-xs font-medium text-fg tabular">{formatClock(now)}</span>
            <span className="text-[10.5px] text-fg-subtle">{formatLongDate(now)}</span>
          </div>

          <div className="hidden items-center gap-2 rounded-lg border border-black/[0.07] bg-black/[0.03] px-2.5 py-1.5 text-xs text-fg-muted xl:flex" role="status">
            <StatusDot color={STATUS_TONE_COLORS[systemStatus.tone]} size={7} pulse={systemStatus.tone !== 'offline'} />
            {systemStatus.label}
          </div>

          <button
            type="button"
            onClick={() => void runAnalysis({ instant: true })}
            disabled={running}
            className="grid size-9 place-items-center rounded-xl border border-black/10 bg-black/[0.04] text-fg-muted transition hover:border-black/15 hover:bg-black/[0.08] hover:text-fg disabled:opacity-60"
            aria-label="Refresh environmental data"
            title="Refresh data"
          >
            <RefreshCw className={cn('size-4', running && 'animate-spin')} />
          </button>
        </div>
      </div>
    </header>
  );
}
