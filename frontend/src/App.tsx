import type { ComponentType } from 'react';
import { AppLayout } from './components/layout/AppLayout';
import { AnalysisProvider } from './context/AnalysisContext';
import { NavigationProvider, useNavigation } from './context/NavigationContext';
import { SettingsProvider } from './context/SettingsContext';
import { ToastProvider } from './context/ToastContext';
import type { RouteId } from './lib/routes';
import { AirAgentPage, WasteAgentPage, WaterAgentPage } from './pages/AgentPages';
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
            <RouteView />
          </NavigationProvider>
        </AnalysisProvider>
      </ToastProvider>
    </SettingsProvider>
  );
}
