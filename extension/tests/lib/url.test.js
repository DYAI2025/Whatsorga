import { describe, it, expect } from 'vitest';
import { normalizeServerUrl, isValidServerUrl } from '../../src/lib/url.js';

describe('normalizeServerUrl', () => {
  it.each([
    ['http://localhost:8900', 'http://localhost:8900'],
    ['http://localhost:8900/', 'http://localhost:8900'],
    ['http://localhost:8900/api/', 'http://localhost:8900'],
    ['  https://example.com/api  ', 'https://example.com'],
    ['HTTPS://EXAMPLE.COM', 'https://example.com'],
  ])('%s -> %s', (input, expected) => {
    expect(normalizeServerUrl(input)).toBe(expected);
  });

  it.each([
    [''],
    ['   '],
    [null],
    [undefined],
    ['not a url'],
    ['ftp://example.com'],
    ['http://'],
  ])('rejects %s -> empty string', (input) => {
    expect(normalizeServerUrl(input)).toBe('');
  });
});

describe('isValidServerUrl', () => {
  it('accepts http/https URLs with host', () => {
    expect(isValidServerUrl('http://localhost:8900')).toBe(true);
    expect(isValidServerUrl('https://radar.example.com')).toBe(true);
  });
  it('rejects empty, non-http schemes, and missing host', () => {
    expect(isValidServerUrl('')).toBe(false);
    expect(isValidServerUrl('ftp://example.com')).toBe(false);
    expect(isValidServerUrl('not a url')).toBe(false);
    expect(isValidServerUrl('http://')).toBe(false);
  });
});
