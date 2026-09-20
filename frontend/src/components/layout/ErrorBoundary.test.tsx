/**
 * The error boundary.
 *
 * It exists because a render crash previously produced a black page with nothing on it — no
 * message, no stack — and the only record was in the dev server's log, which somebody looking at
 * the page does not have. These tests check that a crash now SHOWS something, and that the
 * ordinary case is untouched.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from './ErrorBoundary';

function Boom({ message }: { message: string }): never {
  throw new Error(message);
}

beforeEach(() => {
  // React logs caught errors; silence it so a passing run is not full of red.
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('when nothing throws', () => {
  it('renders its children untouched', () => {
    render(<ErrorBoundary><p>the application</p></ErrorBoundary>);
    expect(screen.getByText('the application')).toBeTruthy();
    expect(screen.queryByText(/failed to render/i)).toBeNull();
  });
});

describe('when a child throws', () => {
  it('shows the message instead of a blank page', () => {
    render(<ErrorBoundary><Boom message="useSettings must be used inside SettingsProvider" /></ErrorBoundary>);
    expect(screen.getByText(/something failed to render/i)).toBeTruthy();
    // The actual error, not a generic apology — this is what makes it diagnosable.
    expect(screen.getByText(/useSettings must be used inside SettingsProvider/)).toBeTruthy();
  });

  it('suggests the stale-module fix for the errors that usually mean it', () => {
    render(<ErrorBoundary><Boom message="useSettings must be used inside SettingsProvider" /></ErrorBoundary>);
    expect(screen.getByText(/module graph has gone stale/i)).toBeTruthy();
    expect(screen.getByText(/node_modules\/\.vite/)).toBeTruthy();
  });

  it('does not offer that hint for an unrelated error', () => {
    render(<ErrorBoundary><Boom message="Network request failed" /></ErrorBoundary>);
    expect(screen.getByText(/Network request failed/)).toBeTruthy();
    // A wrong suggestion sends someone down the wrong path, so it is withheld.
    expect(screen.queryByText(/module graph has gone stale/i)).toBeNull();
  });

  it('offers a reload', () => {
    const reload = vi.fn();
    Object.defineProperty(window, 'location', {
      value: { ...window.location, reload }, writable: true, configurable: true,
    });
    render(<ErrorBoundary><Boom message="boom" /></ErrorBoundary>);
    fireEvent.click(screen.getByRole('button', { name: /reload/i }));
    expect(reload).toHaveBeenCalled();
  });

  it('logs the error so the stack is still reachable in the console', () => {
    render(<ErrorBoundary><Boom message="boom" /></ErrorBoundary>);
    expect(console.error).toHaveBeenCalled();
  });
});
