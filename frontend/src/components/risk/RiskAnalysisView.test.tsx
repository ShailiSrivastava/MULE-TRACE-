import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RiskAnalysisView } from './RiskAnalysisView';

describe('RiskAnalysisView Component', () => {
  it('renders heading and empty state', () => {
    render(<RiskAnalysisView onNavigateHome={vi.fn()} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Risk Analysis' })).toBeInTheDocument();
    expect(screen.getByText(/No Risk Scores Computed Yet/i)).toBeInTheDocument();
  });
});