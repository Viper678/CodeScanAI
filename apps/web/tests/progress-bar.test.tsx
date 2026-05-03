import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ProgressBar } from '@/components/scan-progress/progress-bar';

describe('<ProgressBar />', () => {
  it('renders the percent on the bar and the X / Y counter', () => {
    render(<ProgressBar status="running" done={47} total={312} etaMs={null} />);

    const bar = screen.getByRole('progressbar', { name: /scan progress/i });
    // 47/312 = 15.06% → rounded.
    expect(bar.getAttribute('aria-valuenow')).toBe('15');
    expect(screen.getByTestId('progress-counter')).toHaveTextContent(
      '47 / 312',
    );
  });

  it('shows the estimating placeholder when etaMs is null', () => {
    render(<ProgressBar status="running" done={1} total={10} etaMs={null} />);
    expect(screen.getByTestId('progress-eta')).toHaveTextContent(
      /estimating eta/i,
    );
  });

  it('formats sub-minute eta as Xs', () => {
    render(<ProgressBar status="running" done={1} total={10} etaMs={45_000} />);
    expect(screen.getByTestId('progress-eta')).toHaveTextContent('ETA 45s');
  });

  it('formats minute-plus eta as Xm Ys', () => {
    render(
      <ProgressBar status="running" done={1} total={10} etaMs={125_000} />,
    );
    expect(screen.getByTestId('progress-eta')).toHaveTextContent('ETA 2m 5s');
  });

  it('renders 0% when total is zero (avoids divide-by-zero)', () => {
    render(<ProgressBar status="pending" done={0} total={0} etaMs={null} />);
    const bar = screen.getByRole('progressbar', { name: /scan progress/i });
    expect(bar.getAttribute('aria-valuenow')).toBe('0');
    expect(screen.getByTestId('progress-counter')).toHaveTextContent('0 / 0');
  });

  it('uses the Queued… label for pending status', () => {
    render(<ProgressBar status="pending" done={0} total={5} etaMs={null} />);
    expect(screen.getByText(/queued/i)).toBeInTheDocument();
  });
});
