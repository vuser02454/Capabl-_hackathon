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

/** Where the API lives.
 *
 * Empty in development: requests go to a relative path and Vite's dev proxy forwards them to the
 * backend, which keeps the browser on one origin and means no CORS in local work. In a hosted
 * build there is no proxy, so `VITE_API_BASE_URL` supplies the backend's own origin at build time.
 *
 * This is a URL, not a secret — VITE_* variables are compiled into a bundle every visitor
 * downloads, so no key may ever be read this way. */
const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL as string | undefined)?.trim() ?? '';

const DEFAULTS: Settings = { demoMode: true, apiBaseUrl: API_BASE_URL, speed: 'normal', fault: 'none' };
const STORAGE_KEY = 'ecosentinel.settings.v1';

function loadSettings(): Settings {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return {
      demoMode: typeof parsed.demoMode === 'boolean' ? parsed.demoMode : DEFAULTS.demoMode,
      // A build-time base URL wins over a stale value saved in a previous deployment's
      // localStorage; otherwise a redeploy to a new backend would keep talking to the old one.
      apiBaseUrl: API_BASE_URL
        || (typeof parsed.apiBaseUrl === 'string' ? parsed.apiBaseUrl : DEFAULTS.apiBaseUrl),
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
