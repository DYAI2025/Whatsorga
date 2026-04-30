/**
 * Normalise a server URL: trim, lowercase scheme/host, strip trailing slashes,
 * strip a trailing /api suffix. Returns the normalised origin (no path).
 *
 * @param {unknown} raw
 * @returns {string} normalised URL, or empty string if input is unparseable.
 */
export function normalizeServerUrl(raw) {
  if (!raw || typeof raw !== 'string') return '';
  const trimmed = raw.trim();
  if (!trimmed) return '';
  try {
    const url = new URL(trimmed);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return '';
    if (!url.host) return '';
    const pathname = url.pathname || '/';
    if (pathname !== '/' && !/^\/api\/*$/i.test(pathname)) return '';
    return url.origin.toLowerCase();
  } catch {
    return '';
  }
}

/**
 * @param {unknown} raw
 * @returns {boolean}
 */
export function isValidServerUrl(raw) {
  return normalizeServerUrl(raw) !== '';
}
