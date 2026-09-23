/**
 * Surviving a backend that was asleep.
 *
 * A free hosting tier spins the service down after a few minutes idle. Measured against the
 * deployed backend: a cold start answers in ~43 s, a warm one in ~0.3 s. Most calls in this
 * client budget 20 s, so after any idle period EVERY request failed and the whole app looked
 * broken — until a reload, by which point the service was awake and everything worked.
 *
 * The retry must be narrow: only a timeout or a connection failure, never a real HTTP error.
 * Waiting 75 s to re-ask a question the server already answered with a 404 is its own bug.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from './apiClient';

/** Fails `failures` times the way a sleeping service does, then answers. */
function stubFetch(failures: number, mode: 'timeout' | 'refused' = 'refused') {
  let calls = 0;
  vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    calls += 1;
    if (calls <= failures) {
      if (mode === 'timeout') {
        // Never settles; the client's own AbortController is what ends it.
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
        });
      }
      return Promise.reject(new TypeError('Failed to fetch'));
    }
    return Promise.resolve({
      ok: true, status: 200, text: () => Promise.resolve(JSON.stringify({ status: 'ok' })),
    } as Response);
  }));
  return () => calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('a backend waking from idle', () => {
  it('retries once and succeeds', async () => {
    const calls = stubFetch(1);
    const result = await new ApiClient('').agentsStatus();
    expect(result).toEqual({ status: 'ok' });
    expect(calls()).toBe(2);
  });

  it('retries a timeout, not just a refused connection', async () => {
    // Fake timers: the first attempt only aborts once its own budget elapses, which is longer
    // than a test should ever actually wait.
    vi.useFakeTimers();
    const calls = stubFetch(1, 'timeout');
    const pending = new ApiClient('').agentsStatus();
    await vi.advanceTimersByTimeAsync(120_000);
    await expect(pending).resolves.toEqual({ status: 'ok' });
    expect(calls()).toBe(2);
    vi.useRealTimers();
  });

  it('gives up after one retry rather than hanging forever', async () => {
    const calls = stubFetch(99);
    await expect(new ApiClient('').agentsStatus()).rejects.toThrow();
    // Two attempts total. A third would double an already long wait for no gain.
    expect(calls()).toBe(2);
  });
});

describe('what is NOT retried', () => {
  it('reports a real HTTP error immediately', async () => {
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(() => {
      calls += 1;
      return Promise.resolve({
        ok: false, status: 404,
        text: () => Promise.resolve(JSON.stringify({
          error: { code: 'NOT_FOUND', message: 'No such report.' } })),
      } as Response);
    }));

    await expect(new ApiClient('').agentsStatus()).rejects.toThrow(/no such report/i);
    // The server answered. Waiting 75 s to ask again would be its own bug.
    expect(calls).toBe(1);
  });

  it('does not retry once the caller has aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(() => { calls += 1; return Promise.reject(new TypeError('x')); }));

    await expect(new ApiClient('').agentsStatus(controller.signal)).rejects.toThrow();
    expect(calls).toBe(0);
  });
});

describe('the timeout message', () => {
  it('tells the user a hosted backend may be waking, rather than just failing', async () => {
    vi.useFakeTimers();
    stubFetch(99, 'timeout');
    const pending = new ApiClient('').agentsStatus();
    const assertion = expect(pending).rejects.toThrow(/waking from idle/i);
    await vi.advanceTimersByTimeAsync(200_000);
    await assertion;
    vi.useRealTimers();
  });
});
