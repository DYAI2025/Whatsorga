const TIMEOUT_MS = 8_000;

/**
 * @param {{ serverUrl:string, apiKey:string, counts:Record<string,number>, queueSize:number, timeoutMs?:number }} params
 * @returns {Promise<{ sent:string[], remaining:Record<string,number>, skipped?:string }>}
 */
export async function runHeartbeat({
  serverUrl, apiKey, counts, queueSize, timeoutMs = TIMEOUT_MS,
}) {
  if (!serverUrl || !apiKey) return { sent: [], remaining: { ...counts }, skipped: 'not_configured' };

  const entries = Object.entries(counts).filter(([, n]) => n > 0);
  const remaining = { ...counts };
  for (const [chatId] of entries) remaining[chatId] = counts[chatId];

  const sent = [];

  const tasks = entries.map(async ([chatId, n]) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${serverUrl}/api/heartbeat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({
          chatId, messageCount: n, queueSize, timestamp: new Date().toISOString(),
        }),
        signal: ctrl.signal,
      });
      if (res.ok) {
        sent.push(chatId);
        delete remaining[chatId];
      }
    } catch {
      // keep remaining[chatId] as-is
    } finally {
      clearTimeout(timer);
    }
  });

  await Promise.all(tasks);

  // Strip zero counters that came in already at 0
  for (const k of Object.keys(remaining)) {
    if (remaining[k] === 0) delete remaining[k];
  }
  return { sent, remaining };
}
