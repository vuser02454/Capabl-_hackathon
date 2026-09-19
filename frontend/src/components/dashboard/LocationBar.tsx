import { AnimatePresence, motion } from 'framer-motion';
import { Crosshair, TriangleAlert, ScanSearch } from 'lucide-react';
import { locationKey, useAnalysis } from '../../context/AnalysisContext';
import { useSettings } from '../../context/SettingsContext';
import { cn, formatTime } from '../../lib/format';
import { AGENT_ORDER } from '../../services/analysisEngine';
import { AGENT_META } from '../agents/agentMeta';
import { Button } from '../ui/Button';
import { DashboardCard } from '../ui/DashboardCard';
import { Chip, ProgressBar } from '../ui/primitives';
import { LocationSelector } from './LocationSelector';

export function LocationBar() {
  const { state, selectLocation, selectPoint, browserLocation: browser, runAnalysis, progress } = useAnalysis();
  const { settings } = useSettings();
  const running = state.phase === 'running';
  const activeAgent = AGENT_ORDER.find((agent) => state.steps[agent].status === 'running');
  // Compare the analysis TARGET, not the coordinator's shortened location label.
  const stale =
    !running &&
    state.result !== null &&
    state.analyzedKey !== null &&
    state.analyzedKey !== locationKey(state.selectedLocation, state.selectedPoint);

  let status: React.ReactNode;
  if (running) {
    status = (
      <span className="text-fg-muted">
        <span className="font-medium text-brand">{state.runKind === 'image' ? 'Analyzing image…' : 'Analyzing Environment…'}</span>
        {activeAgent && <> · {AGENT_META[activeAgent].name}</>}
      </span>
    );
  } else if (stale) {
    status = <span className="text-risk-moderate">Location changed — run Analyze Area to update results</span>;
  } else if (state.result) {
    const agents = state.result.runs.filter((run) => run.status === 'complete').length;
    status = (
      <span>
        Last analysis <span className="text-fg-muted tabular">{formatTime(state.result.completedAt)}</span> · {state.result.location} · {agents} agent
        {agents === 1 ? '' : 's'} reported
      </span>
    );
  } else {
    status = 'Select a location and run the multi-agent analysis';
  }

  return (
    <DashboardCard bodyClassName="p-4 sm:p-5" className="!overflow-visible z-20">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
        <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row sm:items-center sm:gap-5">
          <LocationSelector
            value={state.selectedLocation}
            point={state.selectedPoint}
            onChange={selectLocation}
            onSelectPoint={selectPoint}
            browser={browser}
            disabled={running}
          />
          <p className="min-w-0 text-xs text-fg-subtle">{status}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          {!settings.demoMode && !state.selectedPoint && (
            <Button
              size="md"
              variant="secondary"
              icon={Crosshair}
              loading={browser.locating}
              disabled={running}
              onClick={() => {
                void browser.request().then((found) => {
                  if (found) selectPoint(found);
                });
              }}
            >
              Use My Location
            </Button>
          )}
          {settings.fault !== 'none' && (
            <Chip color="#d97706" icon={<TriangleAlert className="size-3 text-risk-moderate" />}>
              Fault injection: {settings.fault === 'water-timeout' ? 'water sensor timeout' : 'air source failure'}
            </Chip>
          )}
          <Button
            variant="primary"
            size="lg"
            icon={ScanSearch}
            loading={running}
            onClick={() => void runAnalysis()}
            className={cn('w-full sm:w-auto', stale && 'animate-pulse')}
          >
            {running ? 'Analyzing…' : 'Analyze Area'}
          </Button>
        </div>
      </div>
      {browser.error && (
        <p className="flex items-start gap-1.5 pt-3 text-[11px] text-risk-moderate">
          <TriangleAlert className="mt-px size-3 shrink-0" />
          <span>{browser.error.message}</span>
        </p>
      )}

      <AnimatePresence>
        {running && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="flex items-center gap-3 pt-4">
              <ProgressBar value={progress} height={3} />
              <span className="w-10 text-right text-[11px] text-fg-subtle tabular">{Math.round(progress * 100)}%</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </DashboardCard>
  );
}
