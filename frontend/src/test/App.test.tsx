import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from '../App';

describe('MuleTrace Authentication & Navigation Flow', () => {
  /* =========================================================================
   * 1. Authentication & Login Tests (Unauthenticated by default)
   * ========================================================================= */
  it('renders Analyst Login view by default when unauthenticated', () => {
    render(<App />);

    expect(screen.getByText('Analyst Sign In')).toBeInTheDocument();
    expect(screen.getByLabelText(/Analyst Email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Remember session/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Sign In$/i })).toBeInTheDocument();
    expect(
      screen.getByRole('button', {
        name: /Preview Investigator Workspace \(Demo Session\)/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Enterprise AML & Network Intelligence|MuleTrace/i).length).toBeGreaterThanOrEqual(1);
  });

  it('displays form validation errors for invalid email and short password', async () => {
    render(<App />);

    const submitBtn = screen.getByRole('button', { name: /^Sign In$/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Analyst email is required/i)).toBeInTheDocument();
      expect(screen.getByText(/Password is required/i)).toBeInTheDocument();
    });

    const emailInput = screen.getByLabelText(/Analyst Email/i);
    const passwordInput = screen.getByLabelText(/^Password$/i);

    fireEvent.change(emailInput, { target: { value: 'not-an-email' } });
    fireEvent.change(passwordInput, { target: { value: 'pass' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Please enter a valid email address/i)).toBeInTheDocument();
      expect(screen.getByText(/Password must be at least 8 characters/i)).toBeInTheDocument();
    });
  });

  it('authenticates via valid form submission and navigates to the dashboard', async () => {
    render(<App />);

    const emailInput = screen.getByLabelText(/Analyst Email/i);
    const passwordInput = screen.getByLabelText(/^Password$/i);
    const submitBtn = screen.getByRole('button', { name: /^Sign In$/i });

    fireEvent.change(emailInput, { target: { value: 'analyst@muletrace.internal' } });
    fireEvent.change(passwordInput, { target: { value: 'SuperSecret123!' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText('Financial Intelligence Overview')).toBeInTheDocument();
      expect(screen.getByText('Engine Ready')).toBeInTheDocument();
    });
  });

  it('authenticates instantly via Preview Investigator Workspace (Demo Session)', () => {
    render(<App />);

    const demoBtn = screen.getByRole('button', {
      name: /Preview Investigator Workspace \(Demo Session\)/i,
    });
    fireEvent.click(demoBtn);

    expect(screen.getByText('Financial Intelligence Overview')).toBeInTheDocument();
    expect(screen.getAllByText('Overview Dashboard').length).toBeGreaterThanOrEqual(1);
  });

  it('signs back out to the Login view using the Sign Out button in the header', () => {
    render(<App initialAuthenticated={true} />);

    expect(screen.getByText('Financial Intelligence Overview')).toBeInTheDocument();

    const signOutBtns = screen.getAllByRole('button', { name: /Sign Out/i });
    fireEvent.click(signOutBtns[0]);

    expect(screen.getByText('Analyst Sign In')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Sign In$/i })).toBeInTheDocument();
  });

  /* =========================================================================
   * 2. Authenticated Workspace & Navigation Tests
   * ========================================================================= */
  it('renders MuleTrace branding and Financial Intelligence title in workspace', () => {
    render(<App initialAuthenticated={true} />);
    expect(screen.getAllByText('MuleTrace').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Financial Intelligence/i).length).toBeGreaterThanOrEqual(1);
  });

  it('displays enterprise AML label in workspace', () => {
    render(<App initialAuthenticated={true} />);
    expect(screen.getByText(/AML Detection Engine/i)).toBeInTheDocument();
  });

  it('renders all 7 navigation links in the sidebar', () => {
    render(<App initialAuthenticated={true} />);
    expect(screen.getAllByText('Overview Dashboard').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Transactions')).toBeInTheDocument();
    expect(screen.getByText('Network Graph')).toBeInTheDocument();
    expect(screen.getByText('Suspicious Alerts')).toBeInTheDocument();
    expect(screen.getByText('Investigation Cases')).toBeInTheDocument();
    expect(screen.getByText('Risk Analysis')).toBeInTheDocument();
    expect(screen.getByText('Reports & Export')).toBeInTheDocument();
  });

  it('renders the 4 placeholder KPI cards on the Overview Dashboard', () => {
    render(<App initialAuthenticated={true} />);
    expect(screen.getByText('Total Monitored Volume')).toBeInTheDocument();
    expect(screen.getByText('Active High-Risk Alerts')).toBeInTheDocument();
    expect(screen.getByText('Open Investigations')).toBeInTheDocument();
    expect(screen.getByText('Flagged Mule Networks')).toBeInTheDocument();
  });

  it('renders empty-state panels ready for real FastAPI endpoints', () => {
    render(<App initialAuthenticated={true} />);
    expect(screen.getByText('Suspicious Activity Stream')).toBeInTheDocument();
    expect(screen.getByText('Mule Network Topology')).toBeInTheDocument();
    expect(screen.getByText('No Suspicious Activity Detected')).toBeInTheDocument();
    expect(screen.getByText('Graph Canvas Ready')).toBeInTheDocument();
  });

  it('switches views when navigation links are clicked', () => {
    render(<App initialAuthenticated={true} />);

    // Click Transactions
    const txLink = screen.getByText('Transactions');
    fireEvent.click(txLink);
    expect(screen.getByRole('heading', { level: 1, name: 'Transactions Monitor' })).toBeInTheDocument();
    expect(screen.getByText(/Ready for FastAPI \/api\/v1\/transactions endpoints/i)).toBeInTheDocument();

    // Click Network Graph
    const graphLink = screen.getByText('Network Graph');
    fireEvent.click(graphLink);
    expect(screen.getByRole('heading', { level: 1, name: 'Mule Network Graph' })).toBeInTheDocument();
    expect(screen.getByText(/Ready for Cytoscape.js graph state/i)).toBeInTheDocument();

    // Click Suspicious Alerts
    const alertsLink = screen.getByText('Suspicious Alerts');
    fireEvent.click(alertsLink);
    expect(screen.getByRole('heading', { level: 1, name: 'Suspicious Alerts' })).toBeInTheDocument();
    expect(screen.getByText(/Ready for FastAPI \/api\/v1\/alerts streaming endpoints/i)).toBeInTheDocument();

    // Click Investigation Cases
    const casesLink = screen.getByText('Investigation Cases');
    fireEvent.click(casesLink);
    expect(screen.getByRole('heading', { level: 1, name: 'Investigation Cases' })).toBeInTheDocument();
    expect(screen.getByText(/Ready for FastAPI \/api\/v1\/cases persistence models/i)).toBeInTheDocument();

    // Return to Overview
    const backButton = screen.getAllByRole('button', { name: /Back to Overview/i })[0];
    fireEvent.click(backButton);
    expect(screen.getByText('Financial Intelligence Overview')).toBeInTheDocument();
  });

  it('provides a backend health probe button', () => {
    render(<App initialAuthenticated={true} />);
    const pingButtons = screen.getAllByRole('button', { name: /Ping \/health|Check Backend Health/i });
    expect(pingButtons.length).toBeGreaterThanOrEqual(1);
  });
});
