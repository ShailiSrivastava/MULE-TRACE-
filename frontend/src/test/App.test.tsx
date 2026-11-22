import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import App from '../App';

describe('MuleTrace Financial Intelligence UI Shell', () => {
  it('renders MuleTrace branding and Financial Intelligence title', () => {
    render(<App />);
    expect(screen.getAllByText('MuleTrace').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Financial Intelligence/i).length).toBeGreaterThanOrEqual(1);
  });

  it('displays collaborators Shaili & Raj', () => {
    render(<App />);
    expect(screen.getByText(/Shaili & Raj/i)).toBeInTheDocument();
  });

  it('renders all 7 navigation links in the sidebar', () => {
    render(<App />);
    expect(screen.getAllByText('Overview Dashboard').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Transactions')).toBeInTheDocument();
    expect(screen.getByText('Network Graph')).toBeInTheDocument();
    expect(screen.getByText('Suspicious Alerts')).toBeInTheDocument();
    expect(screen.getByText('Investigation Cases')).toBeInTheDocument();
    expect(screen.getByText('Risk Analysis')).toBeInTheDocument();
    expect(screen.getByText('Reports & Export')).toBeInTheDocument();
  });

  it('renders the 4 placeholder KPI cards on the Overview Dashboard', () => {
    render(<App />);
    expect(screen.getByText('Total Monitored Volume')).toBeInTheDocument();
    expect(screen.getByText('Active High-Risk Alerts')).toBeInTheDocument();
    expect(screen.getByText('Open Investigations')).toBeInTheDocument();
    expect(screen.getByText('Flagged Mule Networks')).toBeInTheDocument();
  });

  it('renders empty-state panels ready for real FastAPI endpoints', () => {
    render(<App />);
    expect(screen.getByText('Suspicious Activity Stream')).toBeInTheDocument();
    expect(screen.getByText('Mule Network Topology')).toBeInTheDocument();
    expect(screen.getByText('No Suspicious Activity Detected')).toBeInTheDocument();
    expect(screen.getByText('Graph Canvas Ready')).toBeInTheDocument();
  });

  it('switches views when navigation links are clicked', () => {
    render(<App />);
    
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

    // Return to Overview
    const backButton = screen.getByRole('button', { name: /Back to Overview/i });
    fireEvent.click(backButton);
    expect(screen.getByText('Financial Intelligence Overview')).toBeInTheDocument();
  });

  it('provides a backend health probe button', () => {
    render(<App />);
    const pingButtons = screen.getAllByRole('button', { name: /Ping \/health|Check Backend Health/i });
    expect(pingButtons.length).toBeGreaterThanOrEqual(1);
  });
});
