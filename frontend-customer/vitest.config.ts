import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Component tests need a DOM, which `vite.config.ts` has no reason to carry —
// keeping them apart means the dev/build config stays exactly what it was.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
