/**
 * Catches a render crash and shows what broke.
 *
 * Without this, a throw anywhere in the tree unmounts everything and leaves a black page: no
 * message, no stack, nothing to act on. That is exactly what a stale dev server produced when
 * duplicate module instances made a context lookup fail — and diagnosing it needed the dev
 * server's own log, which a user looking at the page does not have.
 *
 * React names this in its own warning ("Consider adding an error boundary"), and it has to be a
 * class: there is no hook equivalent of componentDidCatch.
 *
 * The recovery hint is deliberately specific. The commonest cause of a blank page in development
 * is an accumulated HMR module graph, and "restart the dev server" is the fix a developer would
 * otherwise spend a while arriving at.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface State {
  error: Error | null;
  componentStack: string | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, componentStack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept in the console too: the stack is more useful there, where it is expandable.
    console.error('EcoSentinel render error:', error, info.componentStack);
    this.setState({ componentStack: info.componentStack ?? null });
  }

  render() {
    const { error, componentStack } = this.state;
    if (!error) return this.props.children;

    const looksLikeStaleModules = /must be used inside|Cannot read propert|is not a function/i
      .test(error.message);

    return (
      <div className="flex min-h-screen items-start justify-center bg-ink-950 p-6">
        <div className="mt-16 w-full max-w-2xl rounded-2xl border border-white/10 bg-white/[0.04] p-6">
          <h1 className="text-lg font-semibold text-white">Something failed to render</h1>
          <p className="mt-1 text-[13px] text-white/60">
            The page stopped before it could draw. The error is below rather than a blank screen.
          </p>

          <pre className="mt-4 overflow-x-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-[11.5px] leading-relaxed text-red-300">
            {error.message}
          </pre>

          {looksLikeStaleModules && (
            <p className="mt-3 rounded-lg border border-amber-400/25 bg-amber-400/[0.08] px-3 py-2 text-[12px] leading-relaxed text-amber-200">
              In development this usually means the dev server's module graph has gone stale after
              many hot reloads — two copies of the same module, so a context lookup finds nothing.
              Stop the dev server, delete <code className="font-mono">node_modules/.vite</code>,
              and start it again.
            </p>
          )}

          {componentStack && (
            <details className="mt-3">
              <summary className="cursor-pointer text-[12px] text-white/50 hover:text-white/80">
                Component stack
              </summary>
              <pre className="mt-2 max-h-60 overflow-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-[10.5px] leading-relaxed text-white/50">
                {componentStack}
              </pre>
            </details>
          )}

          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-4 rounded-lg border border-white/20 bg-white/[0.06] px-4 py-2 text-[13px] font-medium text-white transition hover:bg-white/[0.12]"
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
