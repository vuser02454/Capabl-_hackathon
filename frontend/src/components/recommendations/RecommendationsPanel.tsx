import { ListChecks } from 'lucide-react';
import { useAnalysis } from '../../context/AnalysisContext';
import { cn } from '../../lib/format';
import { DashboardCard } from '../ui/DashboardCard';
import { LoadingState } from '../ui/LoadingState';
import { Chip } from '../ui/primitives';
import { RecommendationCard } from './RecommendationCard';

export function RecommendationsPanel({ className }: { className?: string }) {
  const { display, pending } = useAnalysis();
  const coordinator = display.coordinator;

  return (
    <DashboardCard
      title="AI Recommended Actions"
      subtitle="Prioritized by the Coordinator Agent from specialist evidence"
      icon={ListChecks}
      iconColor="#2dd4bf"
      className={className}
      actions={coordinator ? <Chip>{coordinator.recommendations.length} actions</Chip> : undefined}
    >
      {!coordinator ? (
        <LoadingState variant="skeleton" lines={4} />
      ) : (
        <ul className={cn('space-y-2.5 transition-opacity duration-300', pending.coordinator && 'opacity-35')}>
          {coordinator.recommendations.map((recommendation, index) => (
            <RecommendationCard key={`${coordinator.timestamp}-${recommendation.id}`} recommendation={recommendation} index={index} />
          ))}
        </ul>
      )}
    </DashboardCard>
  );
}
