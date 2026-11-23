import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TransactionsView } from './TransactionsView';

describe('TransactionsView Component', () => {
  it('renders heading, table columns, and the clean empty state', () => {
    const handleBack = vi.fn();
    render(<TransactionsView onNavigateHome={handleBack} />);

    // Header checks
    expect(
      screen.getByRole('heading', { level: 1, name: 'Transactions Monitor' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Ready for FastAPI \/api\/v1\/transactions endpoints/i),
    ).toBeInTheDocument();

    // Table Column Headers
    expect(screen.getByText('Transaction ID')).toBeInTheDocument();
    expect(screen.getByText('Timestamp')).toBeInTheDocument();
    expect(screen.getByText('Source Account')).toBeInTheDocument();
    expect(screen.getByText('Destination Account')).toBeInTheDocument();
    expect(screen.getByText('Amount')).toBeInTheDocument();
    expect(screen.getByText('Channel')).toBeInTheDocument();
    expect(screen.getByText('Risk Status')).toBeInTheDocument();

    // Clean Empty State
    expect(screen.getByText('No Transactions Loaded Yet')).toBeInTheDocument();
    expect(
      screen.getByText(/FastAPI \/api\/v1\/transactions: Standing By/i),
    ).toBeInTheDocument();
  });

  it('updates search input and clears when clear button is clicked', () => {
    const handleBack = vi.fn();
    render(<TransactionsView onNavigateHome={handleBack} />);

    const searchInput = screen.getByPlaceholderText(
      /Search by Account ID or Transaction ID/i,
    ) as HTMLInputElement;
    fireEvent.change(searchInput, { target: { value: 'TX-9824' } });
    expect(searchInput.value).toBe('TX-9824');

    const clearButton = screen.getByLabelText(/Clear search/i);
    fireEvent.click(clearButton);
    expect(searchInput.value).toBe('');
  });

  it('filters risk status via dropdown', () => {
    const handleBack = vi.fn();
    render(<TransactionsView onNavigateHome={handleBack} />);

    const filterSelect = screen.getByLabelText(
      /Filter by Risk Status/i,
    ) as HTMLSelectElement;
    expect(filterSelect.value).toBe('All');

    fireEvent.change(filterSelect, { target: { value: 'Flagged' } });
    expect(filterSelect.value).toBe('Flagged');

    fireEvent.change(filterSelect, { target: { value: 'Under Review' } });
    expect(filterSelect.value).toBe('Under Review');
  });

  it('opens CSV dropzone, previews selected file and expected column schema', () => {
    const handleBack = vi.fn();
    render(<TransactionsView onNavigateHome={handleBack} />);

    // Open Dropzone
    const uploadBtn = screen.getByRole('button', { name: /Upload CSV Batch/i });
    fireEvent.click(uploadBtn);

    expect(
      screen.getByText(/Batch Transaction Ingestion \(CSV\)/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Click to browse or drag and drop a \.csv batch file/i),
    ).toBeInTheDocument();

    // Create a mock CSV file
    const file = new File(
      ['transaction_id,source_account,destination_account,amount,currency,timestamp,channel\nTX-1,A1,B1,100,USD,2026-11-23,Wire'],
      'mule_batch_sample.csv',
      { type: 'text/csv' },
    );

    const input = document.getElementById('csv-file-upload') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    // File info preview
    expect(screen.getByText('mule_batch_sample.csv')).toBeInTheDocument();
    expect(screen.getByText(/CSV Validated/i)).toBeInTheDocument();

    // Schema preview check
    expect(screen.getByText('Expected CSV Column Headers Schema')).toBeInTheDocument();
    expect(screen.getByText('transaction_id')).toBeInTheDocument();
    expect(screen.getByText('source_account')).toBeInTheDocument();
    expect(screen.getByText('destination_account')).toBeInTheDocument();
    expect(screen.getByText('amount')).toBeInTheDocument();
    expect(screen.getByText('currency')).toBeInTheDocument();
    expect(screen.getByText('timestamp')).toBeInTheDocument();
    expect(screen.getByText('channel')).toBeInTheDocument();

    // Remove file
    const removeBtn = screen.getByLabelText(/Remove file/i);
    fireEvent.click(removeBtn);

    expect(screen.queryByText('mule_batch_sample.csv')).not.toBeInTheDocument();
  });

  it('navigates back to overview when Back to Overview button is clicked', () => {
    const handleBack = vi.fn();
    render(<TransactionsView onNavigateHome={handleBack} />);

    const backBtn = screen.getByRole('button', { name: /Back to Overview/i });
    fireEvent.click(backBtn);
    expect(handleBack).toHaveBeenCalledTimes(1);
  });
});
