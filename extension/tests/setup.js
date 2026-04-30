import { beforeEach, vi } from 'vitest';
import { createChromeMock } from './mocks/chrome.js';

beforeEach(() => {
  const chromeMock = createChromeMock();
  vi.stubGlobal('chrome', chromeMock);
  // Provide a fetch stub by default — tests override with vi.spyOn
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
});
