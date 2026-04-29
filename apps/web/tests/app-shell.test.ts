import { describe, expect, it } from 'vitest';

import { NAV_ITEMS } from '../lib/app-shell';

describe('app shell', () => {
  it('defines the placeholder navigation items', () => {
    expect(NAV_ITEMS).toEqual(['Scans', 'Uploads', 'Settings']);
  });
});
