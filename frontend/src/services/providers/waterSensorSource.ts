/**
 * Water telemetry source used by the Water Quality Agent.
 *
 * Future pipeline: ESP32 -> Wi-Fi -> Firebase / MQTT -> FastAPI -> agent.
 * The browser reaches real sensors only through the backend API.
 */
import type { LocationProfile } from '../../data/locations';
import { AppError } from '../errors';

export interface WaterSensorReading {
  sensorId: string;
  sensorName: string;
  status: 'online' | 'degraded' | 'offline';
  ph: number | null;
  turbidity: number | null;
  temperature: number | null;
  observedAt: string;
  provider: string;
  isMock: boolean;
}

export interface WaterSensorSource {
  readonly name: string;
  getLatest(location: LocationProfile): Promise<WaterSensorReading>;
}

export class MockWaterSensorSource implements WaterSensorSource {
  readonly name = 'Demo IoT sensor (ESP32 profile)';
  private readonly simulateTimeout: boolean;

  constructor(options: { simulateTimeout?: boolean } = {}) {
    this.simulateTimeout = options.simulateTimeout ?? false;
  }

  getLatest(location: LocationProfile): Promise<WaterSensorReading> {
    if (this.simulateTimeout) {
      // Sensor never answers — the engine's agent timeout handles it.
      return new Promise<WaterSensorReading>(() => undefined);
    }
    const { water } = location;
    if (water.status === 'offline') {
      return Promise.reject(
        new AppError('SENSOR_DATA_UNAVAILABLE', `Water sensor for ${location.name} is offline — no telemetry received.`),
      );
    }
    return Promise.resolve({
      sensorId: water.sensorId,
      sensorName: water.sensorName,
      status: water.status,
      ph: water.ph,
      turbidity: water.turbidity,
      temperature: water.temperature,
      observedAt: new Date().toISOString(),
      provider: this.name,
      isMock: true,
    });
  }
}
