import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NetworkGraphView } from './NetworkGraphView';

describe('NetworkGraphView Component', () => {
  it('renders heading, cytoscape canvas container, and empty-state overlay', () => {
    const handleBack = vi.fn();
    render(<NetworkGraphView onNavigateHome={handleBack} />);

    // Header & Badge checks
    expect(
      screen.getByRole('heading', { level: 1, name: 'Mule Network Graph' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Ready for Cytoscape.js graph state/i),
    ).toBeInTheDocument();

    // Dedicated Cytoscape Canvas Container
    const canvasContainer = screen.getByTestId('cytoscape-canvas');
    expect(canvasContainer).toBeInTheDocument();

    // Clean Empty State Message
    expect(
      screen.getByText(
        /No Account Network Loaded Yet — Select an investigation case or connect backend graph data to render multi-hop money flow clusters/i,
      ),
    ).toBeInTheDocument();
  });

  it('renders interactive layout and hop depth controls', () => {
    const handleBack = vi.fn();
    render(<NetworkGraphView onNavigateHome={handleBack} />);

    // Layout options
    expect(screen.getByRole('button', { name: 'Force-Directed (COSE)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hierarchical (Breadthfirst)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Circular' })).toBeInTheDocument();

    // Hop depth options
    expect(screen.getByRole('button', { name: '1 Hop' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '2 Hops' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '3+ Hops' })).toBeInTheDocument();

    // Clicking layout and hop depth updates active state
    const hierarchicalBtn = screen.getByRole('button', { name: 'Hierarchical (Breadthfirst)' });
    fireEvent.click(hierarchicalBtn);

    const hopBtn = screen.getByRole('button', { name: '3+ Hops' });
    fireEvent.click(hopBtn);
  });

  it('renders zoom controls and risk legend', () => {
    const handleBack = vi.fn();
    render(<NetworkGraphView onNavigateHome={handleBack} />);

    // Zoom controls
    const zoomInBtn = screen.getByRole('button', { name: /Zoom In/i });
    const zoomOutBtn = screen.getByRole('button', { name: /Zoom Out/i });
    const fitBtn = screen.getByRole('button', { name: /Fit to Screen/i });

    expect(zoomInBtn).toBeInTheDocument();
    expect(zoomOutBtn).toBeInTheDocument();
    expect(fitBtn).toBeInTheDocument();

    fireEvent.click(zoomInBtn);
    fireEvent.click(zoomOutBtn);
    fireEvent.click(fitBtn);

    // Risk Legend
    expect(screen.getByText('High-Risk Mule Hub')).toBeInTheDocument();
    expect(screen.getByText('Intermediary Pass-Through')).toBeInTheDocument();
    expect(screen.getByText('Originator / Beneficiary')).toBeInTheDocument();
  });

  it('renders Account Node Inspector with empty state and inspected node details', () => {
    const handleBack = vi.fn();
    render(<NetworkGraphView onNavigateHome={handleBack} />);

    expect(screen.getByText('Account Node Inspector')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Click any account node in the topology canvas to inspect transaction flow metrics',
      ),
    ).toBeInTheDocument();

    // Click sample node preview
    const sampleBtn = screen.getByRole('button', { name: /Inspect Sample Node/i });
    fireEvent.click(sampleBtn);

    // Verify Inspector Displays Required Properties:
    // 1. Account ID
    expect(screen.getByText('Account ID')).toBeInTheDocument();
    expect(screen.getByText('ACC-9924-MULE')).toBeInTheDocument();

    // 2. Risk Score
    expect(screen.getByText('Risk Score')).toBeInTheDocument();
    expect(screen.getByText(/94 \/ 100/i)).toBeInTheDocument();

    // 3. Inbound / Outbound Velocity
    expect(screen.getByText('Inbound / Outbound Velocity')).toBeInTheDocument();
    expect(screen.getByText(/\$142,500 Inbound \/ \$139,800 Outbound/i)).toBeInTheDocument();

    // 4. Flagged Patterns
    expect(screen.getByText('Flagged Patterns')).toBeInTheDocument();
    expect(screen.getByText('Layering (Structuring)')).toBeInTheDocument();
    expect(screen.getByText('Rapid Fund Dispersal')).toBeInTheDocument();
    expect(screen.getByText('Circular Loop Return')).toBeInTheDocument();

    // Clear Selection
    const clearBtn = screen.getByRole('button', { name: /Clear selected node/i });
    fireEvent.click(clearBtn);
    expect(
      screen.getByText(
        'Click any account node in the topology canvas to inspect transaction flow metrics',
      ),
    ).toBeInTheDocument();
  });

  it('navigates back to overview when Back to Overview is clicked', () => {
    const handleBack = vi.fn();
    render(<NetworkGraphView onNavigateHome={handleBack} />);

    const backBtn = screen.getByRole('button', { name: /Back to Overview/i });
    fireEvent.click(backBtn);
    expect(handleBack).toHaveBeenCalledTimes(1);
  });
});
