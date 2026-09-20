/**
 * The grounded safety assistant, from the user's side.
 *
 * Three things must be visibly different on screen, because conflating them is how an assistant
 * becomes misleading: a grounded answer (shows which queries produced it), an ungrounded one
 * (says so, and offers a hint rather than guessing), and a refusal to act (points at the review
 * interface rather than reading like a failure).
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../../context/SettingsContext';
import { SafetyChat } from './SafetyChat';

function stubFetch(body: unknown, ok = true) {
  const calls: Array<Record<string, unknown> | null> = [];
  vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(init?.body ? JSON.parse(String(init.body)) : null);
    return Promise.resolve({
      ok, status: ok ? 200 : 500, text: () => Promise.resolve(JSON.stringify(body)),
    } as Response);
  }));
  return calls;
}

const GROUNDED = {
  answer: '1 worker(s) were rerouted by alert 4: EMP007.',
  deterministicAnswer: '1 worker(s) were rerouted by alert 4: EMP007.',
  answerSource: 'deterministic',
  evidence: [{ tool: 'get_workers_rerouted_by_alert',
               result: { alert_id: 4, count: 1, workers: [{ employee_id: 'EMP007', id: 12 }] } }],
  tools: ['get_workers_rerouted_by_alert'],
  grounded: true, refused: false, role: 'admin', note: 'Answers come from stored records.',
};

const render_ = (props: Partial<Parameters<typeof SafetyChat>[0]> = {}) => {
  const onOpenRoute = vi.fn();
  render(
    <SettingsProvider>
      <SafetyChat role="admin" onOpenRoute={onOpenRoute} {...props} />
    </SettingsProvider>,
  );
  return { onOpenRoute };
};

const ask = (text: string) => {
  fireEvent.change(screen.getByLabelText('Ask the safety assistant'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: /^ask$/i }));
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('before anything is asked', () => {
  it('says where answers come from, and offers examples', () => {
    stubFetch(GROUNDED);
    render_();
    expect(screen.getByText(/not from general knowledge/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /what safety patterns are emerging/i })).toBeTruthy();
  });

  it('offers worker-appropriate examples to a worker', () => {
    stubFetch(GROUNDED);
    render_({ role: 'worker', employeeId: 'EMP001' });
    expect(screen.getByRole('button', { name: /show my recent safety reports/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /which departments/i })).toBeNull();
  });
});

describe('a grounded answer', () => {
  it('sends the role and question, and shows the answer', async () => {
    const calls = stubFetch(GROUNDED);
    render_();
    ask('Which workers were rerouted by alert #4?');

    await waitFor(() => expect(screen.getByText(/1 worker\(s\) were rerouted/)).toBeTruthy());
    expect(calls[0]?.question).toBe('Which workers were rerouted by alert #4?');
    expect(calls[0]?.role).toBe('admin');
  });

  it('names the queries that produced it', async () => {
    stubFetch(GROUNDED);
    render_();
    ask('Which workers were rerouted?');
    // An answer whose evidence can be inspected is different from one that must be trusted.
    await waitFor(() => expect(screen.getByText(/get_workers_rerouted_by_alert/)).toBeTruthy());
  });

  it('offers to open a route event the evidence actually cites', async () => {
    stubFetch(GROUNDED);
    const { onOpenRoute } = render_();
    ask('Which workers were rerouted?');

    await waitFor(() => expect(screen.getByRole('button', { name: /view route re-12/i })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /view route re-12/i }));
    expect(onOpenRoute).toHaveBeenCalledWith(12);
  });
});

describe('an ungrounded answer', () => {
  it('says there is not enough data and offers a hint instead of guessing', async () => {
    stubFetch({ answer: "I don't have enough recorded data to answer that.", evidence: [],
                tools: [], grounded: false, refused: false,
                hint: 'Try naming an employee id like EMP001.', role: 'admin', note: '' });
    render_();
    ask('What is the capital of France?');

    await waitFor(() => expect(screen.getByText(/don't have enough recorded data/i)).toBeTruthy());
    expect(screen.getByText(/try naming an employee id/i)).toBeTruthy();
    // No evidence line, because there is none.
    expect(screen.queryByText(/^Evidence:/)).toBeNull();
  });
});

describe('a refusal to act', () => {
  it('is shown distinctly from a failure', async () => {
    stubFetch({ answer: 'I can explain the evidence behind this, but acting on it is a Safety '
                        + 'Admin action in the review interface.',
                evidence: [], tools: [], grounded: false, refused: true, role: 'admin', note: '' });
    render_();
    ask('Publish this hotspot');

    await waitFor(() => expect(screen.getByText(/Safety Admin action/i)).toBeTruthy());
    expect(screen.getByText(/explains; it does not act/i)).toBeTruthy();
  });
});

describe('when the assistant is unreachable', () => {
  it('reports it without losing the question', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    render_();
    ask('What patterns are emerging?');

    await waitFor(() => expect(screen.getByText(/could not reach|unavailable/i)).toBeTruthy());
    expect(screen.getByText('What patterns are emerging?')).toBeTruthy();
  });
});

describe('the standing disclaimer', () => {
  it('states that the assistant explains rather than decides', () => {
    stubFetch(GROUNDED);
    render_();
    expect(screen.getByText(/never makes or changes them/i)).toBeTruthy();
  });
});
