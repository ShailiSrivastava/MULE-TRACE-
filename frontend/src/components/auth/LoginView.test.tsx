import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LoginView } from './LoginView';

describe('LoginView Component', () => {
  it('renders all required form controls and executive branding', () => {
    const handleAuth = vi.fn();
    render(<LoginView onAuthenticated={handleAuth} />);

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
    expect(screen.getByText(/Enterprise AML & Network Intelligence/i)).toBeInTheDocument();
  });

  it('toggles password visibility when show/hide button is clicked', () => {
    const handleAuth = vi.fn();
    render(<LoginView onAuthenticated={handleAuth} />);

    const passwordInput = screen.getByLabelText(/^Password$/i) as HTMLInputElement;
    expect(passwordInput.type).toBe('password');

    const toggleButton = screen.getByLabelText(/Show password/i);
    fireEvent.click(toggleButton);
    expect(passwordInput.type).toBe('text');

    const hideButton = screen.getByLabelText(/Hide password/i);
    fireEvent.click(hideButton);
    expect(passwordInput.type).toBe('password');
  });

  it('displays validation errors on invalid submission', async () => {
    const handleAuth = vi.fn();
    render(<LoginView onAuthenticated={handleAuth} />);

    const submitBtn = screen.getByRole('button', { name: /^Sign In$/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Analyst email is required/i)).toBeInTheDocument();
      expect(screen.getByText(/Password is required/i)).toBeInTheDocument();
    });

    const emailInput = screen.getByLabelText(/Analyst Email/i);
    const passwordInput = screen.getByLabelText(/^Password$/i);

    fireEvent.change(emailInput, { target: { value: 'invalid-email' } });
    fireEvent.change(passwordInput, { target: { value: 'short' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Please enter a valid email address/i)).toBeInTheDocument();
      expect(screen.getByText(/Password must be at least 8 characters/i)).toBeInTheDocument();
    });

    expect(handleAuth).not.toHaveBeenCalled();
  });

  it('triggers onAuthenticated with credentials upon valid form submission', async () => {
    const handleAuth = vi.fn();
    render(<LoginView onAuthenticated={handleAuth} />);

    const emailInput = screen.getByLabelText(/Analyst Email/i);
    const passwordInput = screen.getByLabelText(/^Password$/i);
    const submitBtn = screen.getByRole('button', { name: /^Sign In$/i });

    fireEvent.change(emailInput, { target: { value: 'investigator@muletrace.internal' } });
    fireEvent.change(passwordInput, { target: { value: 'SecurePass123!' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(handleAuth).toHaveBeenCalledWith(
        expect.objectContaining({
          email: 'investigator@muletrace.internal',
        }),
      );
    });
  });

  it('triggers onAuthenticated immediately when clicking Demo Preview button', () => {
    const handleAuth = vi.fn();
    render(<LoginView onAuthenticated={handleAuth} />);

    const demoBtn = screen.getByRole('button', {
      name: /Preview Investigator Workspace \(Demo Session\)/i,
    });
    fireEvent.click(demoBtn);

    expect(handleAuth).toHaveBeenCalledWith(
      expect.objectContaining({
        email: 'investigator@muletrace.internal',
      }),
    );
  });
});
