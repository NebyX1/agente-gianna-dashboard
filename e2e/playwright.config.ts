import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './tests', fullyParallel: false, workers: 1, timeout: 90000, expect: { timeout: 10000 }, use: { browserName: 'chromium', trace: 'retain-on-failure', screenshot: 'only-on-failure' }, reporter: [['list'], ['html', { open: 'never' }]], outputDir: './test-results' });
