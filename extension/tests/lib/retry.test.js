import { describe, it, expect } from 'vitest';
import { backoffMinutes, scheduleRetry, clearRetry } from '../../src/lib/retry.js';

describe('retry', () => {
  it('uses exponential backoff capped at 5 min', () => {
    expect(backoffMinutes(0)).toBe(0.5);   // 30s
    expect(backoffMinutes(1)).toBe(1);     // 1min
    expect(backoffMinutes(2)).toBe(2);
    expect(backoffMinutes(3)).toBe(5);     // cap
    expect(backoffMinutes(4)).toBe(5);
  });

  it('schedules a chrome alarm with the right delay', () => {
    scheduleRetry(2);
    expect(chrome.alarms.create).toHaveBeenCalledWith(
      'whatsorga_retry',
      { delayInMinutes: 2 }
    );
  });

  it('clearRetry removes the alarm', async () => {
    scheduleRetry(1);
    await clearRetry();
    expect(chrome.alarms.clear).toHaveBeenCalledWith('whatsorga_retry');
  });
});
