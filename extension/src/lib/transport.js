const DEFAULT_TIMEOUT_MS = 10_000;

/**
 * @typedef {{ outcome:'ok' }
 *   | { outcome:'auth_error', status:number }
 *   | { outcome:'server_error', status:number }
 *   | { outcome:'client_error', status:number }
 *   | { outcome:'network_error', error:string }
 *   | { outcome:'timeout' }
 *   | { outcome:'not_configured' }
 * } SendResult
 */

/**
 * @param {{ serverUrl:string, apiKey:string, messages:object[], timeoutMs?:number, eventVersion?:number }} params
 * @returns {Promise<SendResult>}
 */
export async function sendBatch({
  serverUrl, apiKey, messages, timeoutMs = DEFAULT_TIMEOUT_MS, eventVersion = 1,
}) {
  if (!serverUrl || !apiKey) return { outcome: 'not_configured' };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${serverUrl}/api/ingest`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({ messages, eventVersion }),
      signal: controller.signal,
    });
    if (response.ok) return { outcome: 'ok' };
    if (response.status === 401 || response.status === 403)
      return { outcome: 'auth_error', status: response.status };
    if (response.status >= 500) return { outcome: 'server_error', status: response.status };
    return { outcome: 'client_error', status: response.status };
  } catch (/** @type {any} */ err) {
    if (err && err.name === 'AbortError') return { outcome: 'timeout' };
    return { outcome: 'network_error', error: err instanceof Error ? err.message : String(err) };
  } finally {
    clearTimeout(timer);
  }
}
