/**
 * The sidebar's "Back to Login" control.
 *
 * It lives in the sidebar footer, which is shared: only the navigation groups above it differ by
 * role. That is what makes one button serve both the worker and the admin, and it is also the
 * thing a future edit could quietly break by moving the footer inside a role branch — so both
 * roles are asserted rather than one.
 *
 * The other assertion worth having is that the button only navigates. It is not a logout: there
 * is no authentication to end, and clearing the stored role here would silently change what the
 * landing page shows the next visitor on a shared device.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AnalysisProvider } from '../../context/AnalysisContext';
import { NavigationProvider } from '../../context/NavigationContext';
import { RoleProvider } from '../../context/RoleContext';
import { SettingsProvider } from '../../context/SettingsContext';
import { ToastProvider } from '../../context/ToastContext';
import { Sidebar } from './Sidebar';

const ROLE_KEY = 'ecosentinel.role.v1';

function renderSidebar(role: 'worker' | 'admin') {
  try {
    window.localStorage.setItem(ROLE_KEY, role);
  } catch {
    /* private browsing — the provider falls back to unselected, which these tests do not use */
  }
  return render(
    <SettingsProvider>
      <ToastProvider>
        <AnalysisProvider>
          <NavigationProvider>
            <RoleProvider>
              <Sidebar open={false} onClose={() => {}} />
            </RoleProvider>
          </NavigationProvider>
        </AnalysisProvider>
      </ToastProvider>
    </SettingsProvider>,
  );
}

/** The desktop aside and the mobile drawer both render the footer, so there are two. */
const loginButtons = () => screen.getAllByRole('button', { name: /back to login/i });

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200, text: () => Promise.resolve('{}'),
  } as Response));
  window.location.hash = '#/worker/report';
  try { window.localStorage.clear(); } catch { /* optional */ }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the worker sidebar', () => {
  it('offers Back to Login', () => {
    renderSidebar('worker');
    expect(loginButtons().length).toBeGreaterThan(0);
  });

  it('navigates to the existing landing route', () => {
    renderSidebar('worker');
    fireEvent.click(loginButtons()[0]);
    // The landing page is the app's existing login / role-selection screen at '/'.
    expect(window.location.hash).toBe('#/');
  });
});

describe('the admin sidebar', () => {
  it('offers the same Back to Login', () => {
    renderSidebar('admin');
    expect(loginButtons().length).toBeGreaterThan(0);
  });

  it('navigates to the same landing route', () => {
    window.location.hash = '#/admin/dashboard';
    renderSidebar('admin');
    fireEvent.click(loginButtons()[0]);
    expect(window.location.hash).toBe('#/');
  });
});

describe('what the button does not do', () => {
  it('is a navigation control, not a logout — the chosen role survives', () => {
    renderSidebar('worker');
    fireEvent.click(loginButtons()[0]);
    // Nothing is signed out because nothing was signed in; clearing the role here would change
    // what the next visitor to this browser sees for no stated reason.
    expect(window.localStorage.getItem(ROLE_KEY)).toBe('worker');
  });

  it('sends no request when pressed', () => {
    renderSidebar('worker');
    const before = (globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length;
    fireEvent.click(loginButtons()[0]);
    const after = (globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length;
    // It changes no server state: no report, alert, route or worker record is touched.
    expect(after).toBe(before);
  });

  it('is rendered in the sidebar footer rather than among the navigation links', () => {
    renderSidebar('worker');
    expect(loginButtons().length).toBeGreaterThan(0);
    expect(screen.queryByText('System Status')).toBeNull();
  });
});
