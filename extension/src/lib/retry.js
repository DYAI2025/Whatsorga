export const ALARM_NAME = 'whatsorga_retry';

/**
 * @param {number} attempt 0-indexed attempt counter
 * @returns {number} minutes to wait before the next attempt
 */
export function backoffMinutes(attempt) {
  // 0.5, 1, 2, 5, 5, 5 ...
  const ladder = [0.5, 1, 2, 5];
  return ladder[Math.min(attempt, ladder.length - 1)];
}

/** @param {number} minutes */
export function scheduleRetry(minutes) {
  chrome.alarms.create(ALARM_NAME, { delayInMinutes: minutes });
}

export async function clearRetry() {
  await chrome.alarms.clear(ALARM_NAME);
}
