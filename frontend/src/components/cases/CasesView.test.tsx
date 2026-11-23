import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CasesView } from './CasesView';

describe('CasesView Component', () => {
  it('renders header, dossier manager badge, and integration indicator', () => {
    const handleNavigate = vi.fn();
    render(<CasesView onNavigateHome={handleNavigate} />);

    expect(screen.getByRole('heading', { level: 1, name: 'Investigation Cases' })).toBeInTheDocument();
    expect(screen.getByText('Dossier Manager')).toBeInTheDocument();
    expect(
      screen.getByText(/Ready for FastAPI \/api\/v1\/cases persistence models/i),
    ).toBeInTheDocument();
  });

  it('renders status tabs and clean empty state by default', () => {
    render(<CasesView onNavigateHome={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'All Cases' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'In Review' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Escalated / SAR Filed' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Closed' })).toBeInTheDocument();

    expect(
      screen.getByText('No Investigation Dossiers Created Yet'),
    ).toBeInTheDocument();
  });

  it('opens and closes the New Investigation Case modal', () => {
    render(<CasesView onNavigateHome={vi.fn()} />);

    const openBtn = screen.getByRole('button', { name: /New Investigation Case/i });
    fireEvent.click(openBtn);

    expect(screen.getByRole('heading', { level: 3, name: 'Create Investigation Case' })).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);

    expect(screen.queryByRole('heading', { level: 3, name: 'Create Investigation Case' })).not.toBeInTheDocument();
  });

  it('displays validation errors when submitting invalid case inputs', async () => {
    render(<CasesView onNavigateHome={vi.fn()} />);

    const openBtn = screen.getByRole('button', { name: /New Investigation Case/i });
    fireEvent.click(openBtn);

    const submitBtn = screen.getByRole('button', { name: /Save Dossier/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Case title is required/i)).toBeInTheDocument();
      expect(screen.getByText(/Primary account ID is required/i)).toBeInTheDocument();
    });

    const titleInput = screen.getByLabelText(/Case Title/i);
    const accountInput = screen.getByLabelText(/Primary Account ID/i);

    fireEvent.change(titleInput, { target: { value: 'ab' } });
    fireEvent.change(accountInput, { target: { value: 'cd' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Case title must be at least 3 characters/i)).toBeInTheDocument();
      expect(screen.getByText(/Primary account ID must be at least 3 characters/i)).toBeInTheDocument();
    });
  });

  it('creates and renders a new case dossier card upon valid form submission', async () => {
    render(<CasesView onNavigateHome={vi.fn()} />);

    const openBtn = screen.getByRole('button', { name: /New Investigation Case/i });
    fireEvent.click(openBtn);

    const titleInput = screen.getByLabelText(/Case Title/i);
    const accountInput = screen.getByLabelText(/Primary Account ID/i);
    const prioritySelect = screen.getByLabelText(/Priority/i);
    const notesInput = screen.getByLabelText(/Analyst Notes/i);
    const submitBtn = screen.getByRole('button', { name: /Save Dossier/i });

    fireEvent.change(titleInput, { target: { value: 'Rapid Funnel Structuring Ring' } });
    fireEvent.change(accountInput, { target: { value: 'ACC-8832-MULE' } });
    fireEvent.change(prioritySelect, { target: { value: 'Critical' } });
    fireEvent.change(notesInput, { target: { value: 'High velocity layered hops detected across accounts' } });

    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.queryByRole('heading', { level: 3, name: 'Create Investigation Case' })).not.toBeInTheDocument();
      expect(screen.getByText('Rapid Funnel Structuring Ring')).toBeInTheDocument();
      expect(screen.getByText(/Subject: ACC-8832-MULE/i)).toBeInTheDocument();
      expect(screen.getByText(/Critical Priority/i)).toBeInTheDocument();
      expect(screen.getByText(/High velocity layered hops detected across accounts/i)).toBeInTheDocument();
    });
  });

  it('filters cases by status tabs', async () => {
    render(<CasesView onNavigateHome={vi.fn()} />);

    // Create a new open case
    fireEvent.click(screen.getByRole('button', { name: /New Investigation Case/i }));
    fireEvent.change(screen.getByLabelText(/Case Title/i), { target: { value: 'Layering Network 01' } });
    fireEvent.change(screen.getByLabelText(/Primary Account ID/i), { target: { value: 'ACC-1100' } });
    fireEvent.click(screen.getByRole('button', { name: /Save Dossier/i }));

    await waitFor(() => {
      expect(screen.getByText('Layering Network 01')).toBeInTheDocument();
    });

    // Switch to Closed tab
    fireEvent.click(screen.getByRole('button', { name: 'Closed' }));
    expect(screen.queryByText('Layering Network 01')).not.toBeInTheDocument();
    expect(screen.getByText('No Investigation Dossiers Created Yet')).toBeInTheDocument();

    // Switch back to Open tab
    fireEvent.click(screen.getByRole('button', { name: 'Open' }));
    expect(screen.getByText('Layering Network 01')).toBeInTheDocument();
  });

  it('triggers onNavigateHome callback when Back to Overview is clicked', () => {
    const handleNavigate = vi.fn();
    render(<CasesView onNavigateHome={handleNavigate} />);

    const backBtn = screen.getByRole('button', { name: /Back to Overview/i });
    fireEvent.click(backBtn);
    expect(handleNavigate).toHaveBeenCalledTimes(1);
  });
});
