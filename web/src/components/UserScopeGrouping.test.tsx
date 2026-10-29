import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { UserScopeGrouping } from './UserScopeGrouping';

describe('frozen user Scope values', () => {
  it('shows a genuine zero separately from an unavailable Scope and retains excluded values', () => {
    render(<UserScopeGrouping grouping={{ scopes: {
      scope_1: { value: 0, unit: 'kg CO2-Eq', term_count: 1 },
      scope_2: { value: 94.732787, unit: 'kg CO2-Eq', term_count: 3 },
      scope_3: { value: null, unit: null, term_count: 0 },
    }, excluded: { value: 193.4592, unit: 'kg CO2-Eq' }, reconciled: true }} />);
    expect(screen.getByRole('row', { name: '范围1 0 kg CO2-Eq' })).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /范围2 94/ })).toBeInTheDocument();
    expect(screen.getByRole('row', { name: '范围3 —' })).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /用户排除 193/ })).toBeInTheDocument();
  });
});
