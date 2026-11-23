import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReportsView } from './ReportsView';

describe('ReportsView Component', () => {
  it('renders heading and empty state', () => {
    render(<ReportsView onNavigateHome={vi.fn()} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Reports & Export' })).toBeInTheDocument();
    expect(screen.getByText(/No Regulatory Reports Generated Yet/i)).toBeInTheDocument();
  });
});