import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ScanLine } from 'lucide-react';

import { AppShell } from '@/components/app-shell/app-shell';
import { EmptyState } from '@/components/empty-state';
import { Stepper } from '@/components/stepper';
import { ThemeProvider } from '@/components/theme-provider';

vi.mock('next/navigation', () => ({
  usePathname: () => '/scans',
}));

describe('AppShell', () => {
  beforeEach(() => {
    document.documentElement.className = '';
  });

  it('renders the primary navigation items', () => {
    render(
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
        <AppShell>
          <div>Page content</div>
        </AppShell>
      </ThemeProvider>,
    );

    expect(
      screen.getByRole('navigation', { name: 'Primary navigation' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Scans' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Uploads' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument();
  });
});

describe('EmptyState', () => {
  it('renders the title and action', () => {
    render(
      <EmptyState
        icon={ScanLine}
        title="No scans yet"
        description="Waiting for the first scan."
        action={{
          href: '/scans/new',
          label: 'Run your first scan',
        }}
      />,
    );

    expect(
      screen.getByRole('heading', { name: 'No scans yet' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Run your first scan' }),
    ).toBeInTheDocument();
  });
});

describe('Stepper', () => {
  it('marks the current step as active', () => {
    render(
      <Stepper
        currentStep={2}
        steps={['Upload', 'Select files', 'Scan configuration', 'Confirm']}
      />,
    );

    expect(
      screen.getByText('Scan configuration').closest('[data-state="active"]'),
    ).toHaveClass('border-primary');
  });
});
