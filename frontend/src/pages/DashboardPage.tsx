import { AnimatePresence, motion } from 'framer-motion';
import { ArrowUpRight } from 'lucide-react';
import { AgentTimeline } from '../components/agents/AgentTimeline';
import { AirAgentCard, WasteAgentCard, WaterAgentCard } from '../components/agents/SpecialistCards';
import { TrendsSection } from '../components/charts/TrendsSection';
import { CoordinatorPanel } from '../components/coordinator/CoordinatorPanel';
import { AnalysisTrace } from '../components/coordinator/AnalysisTrace';
import { DecisionPanel } from '../components/coordinator/DecisionPanel';
import { EvidenceFusion } from '../components/coordinator/EvidenceFusion';
import { InvestigationMode } from '../components/coordinator/InvestigationMode';
import { RetrievedKnowledgePanel } from '../components/coordinator/RetrievedKnowledgePanel';
import { DataProvenance } from '../components/dashboard/DataProvenance';
import { LocationBar } from '../components/dashboard/LocationBar';
import { OverviewCards } from '../components/dashboard/OverviewCards';
import { MapCard } from '../components/map/EnvironmentalMap';
import { RecommendationsPanel } from '../components/recommendations/RecommendationsPanel';
import { Button } from '../components/ui/Button';
import { ErrorState } from '../components/ui/ErrorState';
import { SectionHeader } from '../components/ui/primitives';
import { useAnalysis } from '../context/AnalysisContext';
import { useNavigation } from '../context/NavigationContext';
import { useSettings } from '../context/SettingsContext';

export function DashboardPage() {
  const { state, clearError, runAnalysis } = useAnalysis();
  const { settings, updateSettings } = useSettings();
  const { navigate } = useNavigation();
  const blocking = state.phase === 'error' && !state.result;

  return (
    <div className="space-y-6">
      <LocationBar />

      <AnimatePresence>
        {state.error && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
            <ErrorState
              compact={!blocking}
              error={state.error}
              message={`${state.error.message}${state.result ? ` Showing the last successful analysis for ${state.result.location}.` : ''}`}
              onRetry={() => {
                clearError();
                void runAnalysis();
              }}
              onSwitchToDemo={settings.demoMode ? undefined : () => updateSettings({ demoMode: true })}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {!blocking && (
        <>
          <OverviewCards />

          {/* The architecture, drawn from the run that just happened: what fed the decision,
              what the engine computed, and what grounded the explanation. */}
          {state.result?.decision && <EvidenceFusion decision={state.result.decision} />}

          <DecisionPanel decision={state.result?.decision ?? null} />

          {state.result?.decision && (
            <div className="grid gap-4 xl:grid-cols-2">
              <AnalysisTrace
                decision={state.result.decision}
                runs={state.result.runs ?? []}
              />
              <InvestigationMode decision={state.result.decision} />
            </div>
          )}

          {state.result?.decision?.knowledge && (
            <RetrievedKnowledgePanel knowledge={state.result.decision.knowledge} />
          )}

          <DataProvenance result={state.result} point={state.selectedPoint} />

          <div className="grid gap-4 xl:grid-cols-12">
            <AgentTimeline className="xl:col-span-5" />
            <CoordinatorPanel className="xl:col-span-7" />
          </div>

          <section className="space-y-4">
            <SectionHeader
              eyebrow="Specialist agents"
              title="Independent agent reports"
              subtitle="Each agent owns its data source and emits a structured risk report for the Coordinator"
              actions={
                <Button size="sm" variant="ghost" iconRight={ArrowUpRight} onClick={() => navigate('how-it-works')}>
                  How agents collaborate
                </Button>
              }
            />
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <AirAgentCard delay={0} />
              <WaterAgentCard delay={0.05} />
              <WasteAgentCard delay={0.1} />
            </div>
          </section>

          <div className="grid gap-4 xl:grid-cols-12">
            <RecommendationsPanel className="xl:col-span-7" />
            <MapCard className="xl:col-span-5" />
          </div>

          <TrendsSection />
        </>
      )}
    </div>
  );
}
