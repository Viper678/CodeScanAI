import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SeverityCounters } from '@/components/scan-progress/severity-counters';

describe('<SeverityCounters />', () => {
  it('renders all five severities with their counts', () => {
    render(
      <SeverityCounters
        summary={{
          by_severity: {
            critical: 3,
            high: 5,
            info: 1,
            low: 7,
            medium: 2,
          },
          by_type: {},
        }}
      />,
    );

    expect(screen.getByTestId('severity-count-critical')).toHaveTextContent(
      '3',
    );
    expect(screen.getByTestId('severity-count-high')).toHaveTextContent('5');
    expect(screen.getByTestId('severity-count-medium')).toHaveTextContent('2');
    expect(screen.getByTestId('severity-count-low')).toHaveTextContent('7');
    expect(screen.getByTestId('severity-count-info')).toHaveTextContent('1');
  });

  it('defaults missing keys to 0', () => {
    render(
      <SeverityCounters
        summary={{
          by_severity: { critical: 2 },
          by_type: {},
        }}
      />,
    );

    expect(screen.getByTestId('severity-count-critical')).toHaveTextContent(
      '2',
    );
    expect(screen.getByTestId('severity-count-high')).toHaveTextContent('0');
    expect(screen.getByTestId('severity-count-medium')).toHaveTextContent('0');
    expect(screen.getByTestId('severity-count-low')).toHaveTextContent('0');
    expect(screen.getByTestId('severity-count-info')).toHaveTextContent('0');
  });

  it('renders zero in every cell when by_severity is empty', () => {
    render(<SeverityCounters summary={{ by_severity: {}, by_type: {} }} />);

    for (const sev of ['critical', 'high', 'medium', 'low', 'info']) {
      expect(screen.getByTestId(`severity-count-${sev}`)).toHaveTextContent(
        '0',
      );
    }
  });
});
