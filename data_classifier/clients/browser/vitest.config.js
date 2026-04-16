import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/unit/**/*.test.js'],
    setupFiles: [],
    server: {
      deps: {
        inline: ['@vitest/web-worker'],
      },
    },
  },
});
