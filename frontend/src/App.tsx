import type { ComponentType } from 'react';
import { AppLayout } from './components/layout/AppLayout';
import { AnalysisProvider } from './context/AnalysisContext';
import { NavigationProvider, useNavigation } from './context/NavigationContext';
import { RoleProvider } from './context/RoleContext';
import { SettingsProvider } from './context/SettingsContext';
import { ToastProvider } from './context/ToastContext';
import type { RouteId } from './lib/routes';
import { AirAgentPage, WasteAgentPage, WaterAgentPage } from './pages/AgentPages';
import { AdminMapPage } from './pages/AdminMapPage';
import { MyReportsPage } from './pages/MyReportsPage';
import { MyRoutesPage } from './pages/MyRoutesPage';
import { NotificationsPage } from './pages/NotificationsPage';
import { WorkerRoutesPage } from './pages/WorkerRoutesPage';
import {
  AdminAnnouncementsPage, AdminDashboardPage, AdminHotspotsPage, AdminReportsPage,
} from './pages/AdminPages';
import { AnalyzeReportPage } from './pages/AnalyzeReportPage';
import { PatternIntelligencePage } from './pages/PatternIntelligencePage';
import { SafetyDashboardPage } from './pages/SafetyDashboardPage';
import { WorkerAlertsPage, WorkerMapPage, WorkerReportPage } from './pages/WorkerPages';
import { CoordinatorPage } from './pages/CoordinatorPage';
import { DashboardPage } from './pages/DashboardPage';
import { HowItWorksPage } from './pages/HowItWorksPage';
import { LandingPage } from './pages/LandingPage';
import { MapPage } from './pages/MapPage';
import { ReportsPage } from './pages/ReportsPage';
import { SettingsPage } from './pages/SettingsPage';

/** The landing experience renders full-bleed, outside the dashboard chrome. */
type AppRouteId = Exclude<RouteId, 'landing'>;

const PAGES: Record<AppRouteId, ComponentType> = {
  // C3 Safety Intelligence — the primary product.
  safety: SafetyDashboardPage,
  'worker-report': WorkerReportPage,
  'worker-map': WorkerMapPage,
  'worker-alerts': WorkerAlertsPage,
  'worker-my-reports': MyReportsPage,
  'admin-dashboard': AdminDashboardPage,
  'admin-map': AdminMapPage,
  'admin-reports': AdminReportsPage,
  'admin-hotspots': AdminHotspotsPage,
  'admin-announcements': AdminAnnouncementsPage,
  'admin-worker-routes': WorkerRoutesPage,
  'worker-my-routes': MyRoutesPage,
  notifications: NotificationsPage,
  analyze: AnalyzeReportPage,
  patterns: PatternIntelligencePage,
  // Retained environmental pages, reachable by URL but out of the primary navigation.
  dashboard: DashboardPage,
  map: MapPage,
  air: AirAgentPage,
  water: WaterAgentPage,
  waste: WasteAgentPage,
  coordinator: CoordinatorPage,
  reports: ReportsPage,
  settings: SettingsPage,
  'how-it-works': HowItWorksPage,
};

function RouteView() {
  const { route } = useNavigation();
  if (route === 'landing') return <LandingPage />;
  const Page = PAGES[route];
  return (
    <AppLayout>
      <Page />
    </AppLayout>
  );
}

export default function App() {
  return (
    <SettingsProvider>
      <ToastProvider>
        <AnalysisProvider>
          <NavigationProvider>
            <RoleProvider>
              <RouteView />
            </RoleProvider>
          </NavigationProvider>
        </AnalysisProvider>
      </ToastProvider>
    </SettingsProvider>
  );
}
