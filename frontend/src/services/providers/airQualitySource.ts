/**
 * Air-quality data source used by the Air Quality Agent.
 *
 * In the browser only the mock source exists: live OpenAQ calls go through the
 * FastAPI backend (backend/services/openaq_service.py) so API keys never reach
 * the client. Swap sources by implementing AirQualitySource.
 */
import type { LocationProfile } from '../../data/locations';
import { AppError } from '../errors';

export interface AirQualityReading {
  stationId: string;
  stationName: string;
  pm25: number | null;
  pm10: number | null;
  no2: number | null;
  o3: number | null;
  observedAt: string;
  provider: string;
  isMock: boolean;
}

export interface AirQualitySource {
  readonly name: string;
  getLatest(location: LocationProfile): Promise<AirQualityReading>;
}

export class MockAirQualitySource implements AirQualitySource {
  readonly name = 'Demo dataset (OpenAQ-compatible)';
  private readonly simulateFailure: boolean;

  constructor(options: { simulateFailure?: boolean } = {}) {
    this.simulateFailure = options.simulateFailure ?? false;
  }

  async getLatest(location: LocationProfile): Promise<AirQualityReading> {
    if (this.simulateFailure) {
      throw new AppError('DATA_SOURCE_ERROR', 'OpenAQ request failed (HTTP 503). Air data unavailable.');
    }
    const { air } = location;
    return {
      stationId: air.stationId,
      stationName: air.stationName,
      pm25: air.pm25,
      pm10: air.pm10,
      no2: air.no2,
      o3: air.o3,
      observedAt: new Date().toISOString(),
      provider: this.name,
      isMock: true,
    };
  }
}
