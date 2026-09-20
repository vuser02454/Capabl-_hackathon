/**
 * India-only validation of a coordinate.
 *
 * The rule that matters is what happens on the unhappy paths. A location outside India is
 * DISCARDED, never nudged to the nearest Indian point — silently relocating a worker's report is
 * worse than refusing it. And a check that cannot run accepts the location as unverified, because
 * blocking a worker in a yard in Pune when Nominatim is down loses the report for no safety gain.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../context/SettingsContext';
import { useIndiaCheck } from './useIndiaCheck';
import type { ReactNode } from 'react';

const wrapper = ({ children }: { children: ReactNode }) => (
  <SettingsProvider>{children}</SettingsProvider>
);

function stubFetch(body: unknown, ok = true) {
  const calls: Array<Record<string, unknown> | null> = [];
  vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(init?.body ? JSON.parse(String(init.body)) : null);
    return Promise.resolve({
      ok, status: ok ? 200 : 503, text: () => Promise.resolve(JSON.stringify(body)),
    } as Response);
  }));
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('a coordinate inside India', () => {
  it('is accepted, with the country reported', async () => {
    const calls = stubFetch({ accepted: true, verified: true, countryCode: 'in',
                              reason: null, place: 'Bengaluru, India', method: 'reverse geocoded' });
    const { result } = renderHook(() => useIndiaCheck(), { wrapper });

    let verdict: Awaited<ReturnType<typeof result.current.check>> | undefined;
    await act(async () => { verdict = await result.current.check(12.9716, 77.5946); });

    expect(verdict?.accepted).toBe(true);
    expect(verdict?.countryCode).toBe('in');
    expect(result.current.rejection).toBeNull();
    expect(calls[0]).toEqual({ latitude: 12.9716, longitude: 77.5946 });
  });
});

describe('a coordinate outside India', () => {
  it('is rejected and the reason is surfaced', async () => {
    stubFetch({ accepted: false, verified: true, countryCode: 'us',
                reason: 'This application currently supports locations in India.',
                place: 'New York, United States', method: 'reverse geocoded' });
    const { result } = renderHook(() => useIndiaCheck(), { wrapper });

    let verdict: Awaited<ReturnType<typeof result.current.check>> | undefined;
    await act(async () => { verdict = await result.current.check(40.7128, -74.0060); });

    expect(verdict?.accepted).toBe(false);
    await waitFor(() => expect(result.current.rejection).toMatch(/supports locations in India/i));
  });

  it('returns the original coordinate rather than an altered one', async () => {
    stubFetch({ accepted: false, verified: true, countryCode: 'np',
                reason: 'This application currently supports locations in India.',
                place: 'Kathmandu, Nepal', method: 'reverse geocoded' });
    const { result } = renderHook(() => useIndiaCheck(), { wrapper });

    let verdict: Awaited<ReturnType<typeof result.current.check>> | undefined;
    await act(async () => { verdict = await result.current.check(27.7172, 85.3240); });

    // Nothing in the verdict carries a substitute coordinate — a rejected point is dropped.
    expect(verdict).not.toHaveProperty('latitude');
    expect(verdict).not.toHaveProperty('longitude');
  });
});

describe('when the check itself fails', () => {
  it('accepts the location as unverified rather than losing it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    const { result } = renderHook(() => useIndiaCheck(), { wrapper });

    let verdict: Awaited<ReturnType<typeof result.current.check>> | undefined;
    await act(async () => { verdict = await result.current.check(12.9716, 77.5946); });

    expect(verdict?.accepted).toBe(true);
    expect(verdict?.verified).toBe(false);
    expect(result.current.rejection).toBeNull();
  });
});

describe('clearing', () => {
  it('drops a previous rejection so a new attempt starts clean', async () => {
    stubFetch({ accepted: false, verified: true, countryCode: 'us',
                reason: 'Outside India.', place: null, method: 'box' });
    const { result } = renderHook(() => useIndiaCheck(), { wrapper });

    await act(async () => { await result.current.check(40.7, -74.0); });
    await waitFor(() => expect(result.current.rejection).toBeTruthy());

    act(() => result.current.clear());
    expect(result.current.rejection).toBeNull();
  });
});
