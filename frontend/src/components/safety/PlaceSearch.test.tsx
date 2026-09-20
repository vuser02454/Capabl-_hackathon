/**
 * Place search, shared by Report Issue and the Safety Map.
 *
 * The bug this file exists to prevent: the previous implementation asked for ONE match and adopted
 * it silently. "Whitefield" resolves to Whitefield, New Hampshire before Whitefield, Bengaluru, so
 * the map jumped to another continent with nothing on screen to say a choice had been made. The
 * tests therefore assert that several results are requested, that they are all shown, and that
 * nothing is adopted until the user picks one.
 *
 * Nothing here touches the network; `fetch` is stubbed and the real ApiClient is driven through it,
 * so the request asserted below is the one FastAPI would receive.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../../context/SettingsContext';
import { PlaceSearch } from './PlaceSearch';

const match = (displayName: string, latitude: number, longitude: number) => ({
  displayName, latitude, longitude,
  category: null, placeType: null, importance: null, isWater: false,
});

/** The real ordering Nominatim returns for "Whitefield" — the wrong one first. */
const WHITEFIELD = [
  match('Whitefield, Coös County, New Hampshire, United States', 44.37313, -71.61197),
  match('Whitefield, Bengaluru, Karnataka, India', 12.96980, 77.75000),
];

function stubFetch(body: unknown, ok = true) {
  const calls: Array<{ url: string; body: Record<string, unknown> | null }> = [];
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), body: init?.body ? JSON.parse(String(init.body)) : null });
    return Promise.resolve({
      ok, status: ok ? 200 : 503, text: () => Promise.resolve(JSON.stringify(body)),
    } as Response);
  }));
  return calls;
}

function renderSearch() {
  const onChoose = vi.fn();
  render(<SettingsProvider><PlaceSearch onChoose={onChoose} /></SettingsProvider>);
  return { onChoose };
}

const type = (text: string) =>
  fireEvent.change(screen.getByLabelText('Search location'), { target: { value: text } });
const clickSearch = () => fireEvent.click(screen.getByRole('button', { name: /^search$/i }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the request', () => {
  it('goes through the backend, never to a provider directly', async () => {
    const calls = stubFetch({ query: 'Whitefield', matches: WHITEFIELD, cached: false });
    renderSearch();
    type('Whitefield');
    clickSearch();

    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls[0].url).toContain('/api/location/search');
    // The rule the architecture test also enforces: the browser never names a provider host.
    expect(calls[0].url).not.toMatch(/nominatim|openstreetmap/i);
  });

  it('scopes the search to India', async () => {
    const calls = stubFetch({ query: 'Whitefield', matches: WHITEFIELD, cached: false });
    renderSearch();
    type('Whitefield');
    clickSearch();

    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    // Nominatim's own filter, applied before ranking — not a word appended to the query.
    expect(calls[0].body?.country_codes).toBe('in');
    expect(String(calls[0].body?.query)).not.toMatch(/india/i);
  });

  it('asks for several matches, not one', async () => {
    const calls = stubFetch({ query: 'Whitefield', matches: WHITEFIELD, cached: false });
    renderSearch();
    type('Whitefield');
    clickSearch();

    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    // Requesting a single match is what made the map jump to the wrong Whitefield.
    expect(Number(calls[0].body?.limit)).toBeGreaterThan(1);
  });

  it('does nothing at all for empty input', () => {
    const calls = stubFetch({ matches: [] });
    renderSearch();
    clickSearch();
    expect(calls).toEqual([]);
    expect(screen.queryByRole('status')).toBeNull();
  });
});

describe('the results', () => {
  it('shows every match so an ambiguous name can be resolved', async () => {
    stubFetch({ query: 'Whitefield', matches: WHITEFIELD, cached: false });
    const { onChoose } = renderSearch();
    type('Whitefield');
    clickSearch();

    await waitFor(() => expect(screen.getByText(/New Hampshire/)).toBeTruthy());
    expect(screen.getByText(/Whitefield, Bengaluru/)).toBeTruthy();
    // Crucially, nothing has been adopted yet.
    expect(onChoose).not.toHaveBeenCalled();
  });

  it('shows the coordinates of each result', async () => {
    stubFetch({ query: 'Whitefield', matches: WHITEFIELD, cached: false });
    renderSearch();
    type('Whitefield');
    clickSearch();

    await waitFor(() => expect(screen.getByText('12.96980, 77.75000')).toBeTruthy());
  });

  it('reports the chosen result only when the user picks it', async () => {
    stubFetch({ query: 'Whitefield', matches: WHITEFIELD, cached: false });
    const { onChoose } = renderSearch();
    type('Whitefield');
    clickSearch();

    await waitFor(() => expect(screen.getByText(/Whitefield, Bengaluru/)).toBeTruthy());
    fireEvent.click(screen.getByText(/Whitefield, Bengaluru/));

    expect(onChoose).toHaveBeenCalledWith({
      latitude: 12.96980, longitude: 77.75000,
      label: 'Whitefield, Bengaluru, Karnataka, India',
    });
  });

  it('closes the list once a result is chosen', async () => {
    stubFetch({ query: 'Whitefield', matches: WHITEFIELD, cached: false });
    renderSearch();
    type('Whitefield');
    clickSearch();

    await waitFor(() => expect(screen.getByText(/New Hampshire/)).toBeTruthy());
    fireEvent.click(screen.getByText(/Whitefield, Bengaluru/));

    expect(screen.queryByText(/New Hampshire/)).toBeNull();
  });

  it('says so when nothing matches', async () => {
    stubFetch({ query: 'zzzz', matches: [], cached: false });
    renderSearch();
    type('zzzz');
    clickSearch();

    await waitFor(() => expect(screen.getByText(/no locations found/i)).toBeTruthy());
  });
});

describe('when the provider fails', () => {
  it('reports it and points at the map instead of failing silently', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    const { onChoose } = renderSearch();
    type('Whitefield');
    clickSearch();

    await waitFor(() => expect(screen.getByText(/location search is unavailable/i)).toBeTruthy());
    // A failed lookup must not adopt anything, so an existing location survives it.
    expect(onChoose).not.toHaveBeenCalled();
  });

  it('surfaces the backend message on a 503', async () => {
    stubFetch({ error: { code: 'SERVICE_UNAVAILABLE', message: 'Nominatim is unreachable.' } }, false);
    renderSearch();
    type('KR Puram');
    clickSearch();

    await waitFor(() => expect(screen.getByText(/nominatim is unreachable/i)).toBeTruthy());
  });
});
