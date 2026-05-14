import { useState } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { KeywordsEditor } from '@/components/scan-config/keywords-editor';

type Value = {
  items: string[];
  case_sensitive: boolean;
  regex: boolean;
};

function Harness({ initial }: Readonly<{ initial: Value }>) {
  const [value, setValue] = useState<Value>(initial);
  return <KeywordsEditor value={value} onChange={setValue} />;
}

describe('<KeywordsEditor />', () => {
  it('shows a per-pattern error when Validate is clicked on an invalid regex', () => {
    render(
      <Harness
        initial={{
          case_sensitive: false,
          items: ['[unclosed'],
          regex: true,
        }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /validate/i }));

    const results = screen.getByTestId('keyword-validation-results');
    const row = within(results).getByText('[unclosed').closest('li');
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute('data-state', 'error');
    // The exact text varies between JS engines; just confirm a message
    // was attached after the em-dash separator.
    expect(row?.textContent).toMatch(/—\s+\S/);
  });

  it('shows OK indicators when Validate is clicked on a valid regex', () => {
    render(
      <Harness
        initial={{
          case_sensitive: false,
          items: ['^password\\s*='],
          regex: true,
        }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /validate/i }));

    const results = screen.getByTestId('keyword-validation-results');
    const row = within(results).getByText('^password\\s*=').closest('li');
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute('data-state', 'ok');
  });

  it('treats every non-empty plain (non-regex) item as OK', () => {
    render(
      <Harness
        initial={{
          case_sensitive: false,
          items: ['[unclosed'],
          regex: false,
        }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /validate/i }));

    const results = screen.getByTestId('keyword-validation-results');
    const row = within(results).getByText('[unclosed').closest('li');
    expect(row).toHaveAttribute('data-state', 'ok');
  });
});
