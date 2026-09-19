import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { FaultInjection } from '../services/analysisEngine';
import { ApiClient } from '../services/apiClient';

export interface Settings {
  demoMode: boolean;
  apiBaseUrl: string;
  speed: 'normal' | 'fast';
  /** Not persisted: resets to 'none' on reload so a demo never starts broken. */
  fault: FaultInjection;
}

const DEFAULTS: Settings = { demoMode: true, apiBaseUrl: '', speed: 'normal', fault: 'none' };
const STORAGE_KEY = 'ecosentinel.settings.v1';

function loadSettings(): Settings {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return {
      demoMode: typeof parsed.demoMode === 'boolean' ? parsed.demoMode : DEFAULTS.demoMode,
      apiBaseUrl: typeof parsed.apiBaseUrl === 'string' ? parsed.apiBaseUrl : DEFAULTS.apiBaseUrl,
      speed: parsed.speed === 'fast' ? 'fast' : 'normal',
      fault: 'none',
    };
  } catch {
    return DEFAULTS;
  }
}

interface SettingsValue {
  settings: Settings;
  updateSettings: (patch: Partial<Settings>) => void;
  api: ApiClient;
}

const SettingsContext = createContext<SettingsValue | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(loadSettings);

  useEffect(() => {
    try {
      const { fault: _fault, ...persisted } = settings;
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
    } catch {
      /* storage unavailable — settings stay in memory */
    }
  }, [settings]);

  const updateSettings = useCallback((patch: Partial<Settings>) => setSettings((current) => ({ ...current, ...patch })), []);
  const api = useMemo(() => new ApiClient(settings.apiBaseUrl), [settings.apiBaseUrl]);
  const value = useMemo(() => ({ settings, updateSettings, api }), [settings, updateSettings, api]);

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  const context = useContext(SettingsContext);
  if (!context) throw new Error('useSettings must be used inside SettingsProvider');
  return context;
}
