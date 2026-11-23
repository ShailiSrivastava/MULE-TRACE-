import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AlertsView } from './AlertsView';

describe('AlertsView Component', () => {
  it('renders header, live status badges, and integration indicator', () => {
    const handleNavigate = vi.fn();
    render(<AlertsView onNavigateHome={handleNavigate} />);

    expect(screen.getByRole('heading', { level: 1, name: 'Suspicious Alerts' })).toBeInTheDocument();
    expect(screen.getByText('Live Triage')).toBeInTheDocument();
    expect(
      screen.getByText(/Ready for FastAPI \/api\/v1\/alerts streaming endpoints/i),
    ).toBeInTheDocument();
  });

  it('renders all four severity summary cards with counts initialized at 0', () => {
    render(<AlertsView onNavigateHome={vi.fn()} />);

    expect(screen.getByText('P0 Severity')).toBeInTheDocument();
    expect(screen.getByText('P1 Severity')).toBeInTheDocument();
    expect(screen.getByText('P2 Severity')).toBeInTheDocument();
    expect(screen.getByText('P3 Severity')).toBeInTheDocument();

    const countElements = screen.getAllByText('0');
    expect(countElements.length).toBeGreaterThanOrEqual(4);
  });

  it('renders table columns and clean empty-state awaiting detection engine stream', () => {
    render(<AlertsView onNavigateHome={vi.fn()} />);

    expect(screen.getByText('Alert ID')).toBeInTheDocument();
    expect(screen.getByText('Pattern Type')).toBeInTheDocument();
    expect(screen.getByText('Primary Account')).toBeInTheDocument();
    expect(screen.getByText('Risk Score')).toBeInTheDocument();
    expect(screen.getByText('Detected At')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();

    expect(
      screen.getByText('No Active Suspicious Alerts — Awaiting backend detection engine stream'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/FastAPI \/api\/v1\/alerts: Standing By/i),
    ).toBeInTheDocument();
  });

  it('allows clicking severity filter pills and updating active filter', () => {
    render(<AlertsView onNavigateHome={vi.fn()} />);

    const critPill = screen.getByRole('button', { name: 'Critical' });
    fireEvent.click(critPill);
    expect(screen.getByText(/Active Severity Filter: Critical/i)).toBeInTheDocument();

    const highPill = screen.getByRole('button', { name: 'High' });
    fireEvent.click(highPill);
    expect(screen.getByText(/Active Severity Filter: High/i)).toBeInTheDocument();

    const allPill = screen.getByRole('button', { name: 'All' });
    fireEvent.click(allPill);
    expect(screen.getByText(/Active Severity Filter: All/i)).toBeInTheDocument();
  });

  it('handles search input and clear search button', () => {
    render(<AlertsView onNavigateHome={vi.fn()} />);

    const searchInput = screen.getByPlaceholderText(/Search by Alert ID, Account, or Pattern.../i);
    fireEvent.change(searchInput, { target: { value: 'ACC-1234' } });
    expect(searchInput).toHaveValue('ACC-1234');

    const clearButton = screen.getByRole('button', { name: /Clear search/i });
    fireEvent.click(clearButton);
    expect(searchInput).toHaveValue('');
  });

  it('triggers onNavigateHome callback when navigation buttons are clicked', () => {
    const handleNavigate = vi.fn();
    render(<AlertsView onNavigateHome={handleNavigate} />);

    const backBtn = screen.getByRole('button', { name: /Back to Overview/i });
    fireEvent.click(backBtn);
    expect(handleNavigate).toHaveBeenCalledTimes(1);

    const bottomLink = screen.getByRole('button', { name: /Overview Dashboard/i });
    fireEvent.click(bottomLink);
    expect(handleNavigate).toHaveBeenCalledTimes(2);
  });
});
