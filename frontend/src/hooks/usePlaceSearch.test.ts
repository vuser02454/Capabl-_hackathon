/**
 * Manual location search: typed text -> backend -> Nominatim -> real coordinates.
 *
 * Two properties are load-bearing. First, courtesy: Nominatim's usage policy caps the whole
 * application at one request per second, so the UI must not fire per keystroke. Second, honesty:
 * a query that matches nothing returns nothing — the hook never invents a coordinate, and it
 * distinguishes "no match" from "provider unreachable", because the user's next move differs.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MIN_QUERY_LENGTH, SEARCH_DEBOUNCE_MS, usePlaceSearch } from './usePlaceSearch';
import type { PlaceMatch } from '../types/environment';

const BENGALURU: PlaceMatch = {
  displayName: 'Bengaluru, Karnataka, India',
  latitude: 12.9716,
  longitude: 77.5946,
  category: 'place',
  placeType: 'city',
  importance: 0.7,
  isWater: false,
};

const BELLANDUR: PlaceMatch = {
  displayName: 'Bellandur Lake, Bengaluru, Karnataka, India',
  latitude: 12.9345,
  longitude: 77.6745,
  category: 'water',
  placeType: 'lake',
  importance: 0.4,
  isWater: true,
};

const searchReturning = (matches: PlaceMatch[]) => vi.fn().mockResolvedValue({ matches });

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** Push past the debounce window so a pending search actually fires. */
const settle = async () => {
  await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS + 10);
};

describe('search results', () => {
  it('returns the provider\'s own matches with their real coordinates', async () => {
    const search = searchReturning([BENGALURU, BELLANDUR]);
    const { result } = renderHook(() => usePlaceSearch('Bengaluru', { search }));

    await settle();

    await waitFor(() => expect(result.current.matches).toEqual([BENGALURU, BELLANDUR]));
    expect(search).toHaveBeenCalledWith('Bengaluru', 6, expect.any(AbortSignal));
    expect(result.current.matches[0].latitude).toBe(12.9716);
  });

  it('flags a water feature so a UI can surface lakes ahead of addresses', async () => {
    const { result } = renderHook(() => usePlaceSearch('Bellandur', { search: searchReturning([BELLANDUR]) }));
    await settle();
    await waitFor(() => expect(result.current.matches[0].isWater).toBe(true));
  });

  it('reports "no match" distinctly from an outage, and invents nothing', async () => {
    const { result } = renderHook(() => usePlaceSearch('zzzzqqqq', { search: searchReturning([]) }));
    await settle();

    await waitFor(() => expect(result.current.empty).toBe(true));
    expect(result.current.matches).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it('surfaces a retryable message when the provider is unreachable', async () => {
    const search = vi.fn().mockRejectedValue(new Error('502'));
    const { result } = renderHook(() => usePlaceSearch('Bengaluru', { search }));
    await settle();

    await waitFor(() =>
      expect(result.current.error).toBe('Location search is temporarily unavailable. Please try again.'),
    );
    expect(result.current.empty).toBe(false);
  });
});

describe('request discipline', () => {
  it('does not search before the debounce window elapses', async () => {
    const search = searchReturning([BENGALURU]);
    renderHook(() => usePlaceSearch('Bengaluru', { search }));

    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS - 50);
    expect(search).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(100);
    expect(search).toHaveBeenCalledTimes(1);
  });

  it('issues one request per pause in typing, not one per keystroke', async () => {
    const search = searchReturning([BENGALURU]);
    const { rerender } = renderHook(({ query }) => usePlaceSearch(query, { search }), {
      initialProps: { query: 'Ben' },
    });

    for (const query of ['Beng', 'Benga', 'Bengal', 'Bengalu', 'Bengaluru']) {
      await vi.advanceTimersByTimeAsync(50);
      rerender({ query });
    }
    await settle();

    expect(search).toHaveBeenCalledTimes(1);
    expect(search).toHaveBeenCalledWith('Bengaluru', 6, expect.any(AbortSignal));
  });

  it('never searches a query too short to be meaningful', async () => {
    const search = searchReturning([BENGALURU]);
    renderHook(() => usePlaceSearch('Be', { search }));
    await settle();
    expect(search).not.toHaveBeenCalled();
    expect('Be'.length).toBeLessThan(MIN_QUERY_LENGTH);
  });

  it('does not search in Demo Mode, which has no backend to ask', async () => {
    const search = searchReturning([BENGALURU]);
    renderHook(() => usePlaceSearch('Bengaluru', { search, disabled: true }));
    await settle();
    expect(search).not.toHaveBeenCalled();
  });

  it('clears results when the query is emptied', async () => {
    const search = searchReturning([BENGALURU]);
    const { result, rerender } = renderHook(({ query }) => usePlaceSearch(query, { search }), {
      initialProps: { query: 'Bengaluru' },
    });
    await settle();
    await waitFor(() => expect(result.current.matches).toHaveLength(1));

    rerender({ query: '' });
    await waitFor(() => expect(result.current.matches).toEqual([]));
  });

  it('aborts an in-flight request when the query changes', async () => {
    const signals: AbortSignal[] = [];
    const search = vi.fn((_q: string, _limit: number, signal: AbortSignal) => {
      signals.push(signal);
      return new Promise<{ matches: PlaceMatch[] }>(() => {}); // never settles
    });
    const { rerender } = renderHook(({ query }) => usePlaceSearch(query, { search }), {
      initialProps: { query: 'Bengaluru' },
    });
    await settle();
    rerender({ query: 'Chennai' });
    await settle();

    expect(signals).toHaveLength(2);
    expect(signals[0].aborted).toBe(true);
  });

  it('reset() clears every piece of state', async () => {
    const { result } = renderHook(() => usePlaceSearch('Bengaluru', { search: searchReturning([BENGALURU]) }));
    await settle();
    await waitFor(() => expect(result.current.matches).toHaveLength(1));

    result.current.reset();

    await waitFor(() => {
      expect(result.current.matches).toEqual([]);
      expect(result.current.error).toBeNull();
      expect(result.current.empty).toBe(false);
    });
  });
});
