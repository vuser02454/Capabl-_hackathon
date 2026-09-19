/**
 * Test setup for the location integrations.
 *
 * jsdom gives the hooks a `navigator` to stub — no test here ever touches a real geolocation
 * device or a real network, and every external provider is a stub.
 */
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@shared': fileURLToPath(new URL('../shared', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
