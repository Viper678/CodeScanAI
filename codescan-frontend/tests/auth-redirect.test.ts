import { describe, expect, it } from 'vitest';

import {
  APP_HOME_PATH,
  LOGIN_PATH,
  buildLoginRedirect,
  resolvePostLoginDestination,
} from '@/lib/auth/redirect';

describe('buildLoginRedirect', () => {
  it('returns plain /login when current path is empty', () => {
    expect(buildLoginRedirect('')).toBe(LOGIN_PATH);
  });

  it('returns plain /login when already on /login', () => {
    expect(buildLoginRedirect(LOGIN_PATH)).toBe(LOGIN_PATH);
  });

  it('appends an encoded ?from for protected paths', () => {
    expect(buildLoginRedirect('/scans/abc')).toBe(
      `${LOGIN_PATH}?from=%2Fscans%2Fabc`,
    );
  });
});

describe('resolvePostLoginDestination', () => {
  it('falls back to the app home when from is missing', () => {
    expect(resolvePostLoginDestination(null)).toBe(APP_HOME_PATH);
    expect(resolvePostLoginDestination('')).toBe(APP_HOME_PATH);
  });

  it('returns same-origin paths verbatim', () => {
    expect(resolvePostLoginDestination('/scans/abc')).toBe('/scans/abc');
  });

  it('refuses external URLs to avoid open redirects', () => {
    expect(resolvePostLoginDestination('https://evil.example.com')).toBe(
      APP_HOME_PATH,
    );
    expect(resolvePostLoginDestination('//evil.example.com/path')).toBe(
      APP_HOME_PATH,
    );
  });

  it('refuses relative paths', () => {
    expect(resolvePostLoginDestination('scans/abc')).toBe(APP_HOME_PATH);
  });

  it('refuses bouncing back to /login or /register', () => {
    expect(resolvePostLoginDestination('/login')).toBe(APP_HOME_PATH);
    expect(resolvePostLoginDestination('/register')).toBe(APP_HOME_PATH);
  });
});
