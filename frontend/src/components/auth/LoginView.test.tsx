import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { LoginView } from './LoginView';
import { AuthSession } from '../../lib/api';

const session: AuthSession = {
  accessToken: 'test-access-token',
  expiresIn: 1800,
  user: {
    id: 'user-1',
    email: 'investigator@example.com',
    display_name: 'Investigator',
    role: 'INVESTIGATOR',
    is_active: true,
    created_at: '2026-11-23T00:00:00Z',
  },
};

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('LoginView Component', () => {
  it('renders the API-backed sign-in form and branding without a demo bypass', () => {
    const handleAuth = vi.fn();
    render(<LoginView onAuthenticated={handleAuth} />);

    expect(screen.getByText('Analyst Sign In')).toBeInTheDocument();
    expect(screen.getByLabelText(/Analyst Email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Password$/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Sign In$/i })).toBeInTheDocument();
    expect(screen.queryByText(/Demo Session/i)).not.toBeInTheDocument();
    expect(screen.getByText(/verified by the MuleTrace API/i)).toBeInTheDocument();
    expect(screen.getByText(/Enterprise AML & Network Intelligence/i)).toBeInTheDocument();
  });

  it('toggles password visibility when show/hide is selected', () => {
    render(<LoginView onAuthenticated={vi.fn()} />);

    const passwordInput = screen.getByLabelText(/^Password$/i) as HTMLInputElement;
    expect(passwordInput.type).toBe('password');

    fireEvent.click(screen.getByLabelText(/Show password/i));
    expect(passwordInput.type).toBe('text');

    fireEvent.click(screen.getByLabelText(/Hide password/i));
    expect(passwordInput.type).toBe('password');
  });

  it('validates malformed email and missing password before contacting the API', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(<LoginView onAuthenticated={vi.fn()} />);

    const submit = screen.getByRole('button', { name: /^Sign In$/i });
    fireEvent.click(submit);
    expect(await screen.findByText(/Analyst email is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Password is required/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Analyst Email/i), {
      target: { value: 'not-an-email' },
    });
    fireEvent.change(screen.getByLabelText(/^Password$/i), {
      target: { value: 'valid-password' },
    });
    fireEvent.click(submit);

    expect(await screen.findByText(/Please enter a valid email address/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('exchanges credentials for a JWT and verifies the current user', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({
        access_token: session.accessToken,
        token_type: 'bearer',
        expires_in: session.expiresIn,
      }))
      .mockResolvedValueOnce(response(session.user));
    vi.stubGlobal('fetch', fetchMock);
    const handleAuth = vi.fn();
    render(<LoginView onAuthenticated={handleAuth} />);

    fireEvent.change(screen.getByLabelText(/Analyst Email/i), {
      target: { value: session.user.email },
    });
    fireEvent.change(screen.getByLabelText(/^Password$/i), {
      target: { value: 'SecurePass123!' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^Sign In$/i }));

    await waitFor(() => expect(handleAuth).toHaveBeenCalledWith(session));
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://localhost:8000/api/v1/auth/login',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: session.user.email, password: 'SecurePass123!' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://localhost:8000/api/v1/auth/me',
      expect.objectContaining({
        headers: { Authorization: `Bearer ${session.accessToken}` },
      }),
    );
  });

  it('shows the generic backend authentication error without bypassing the API', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      response({ error: { message: 'Email or password is incorrect.' } }, 401),
    );
    vi.stubGlobal('fetch', fetchMock);
    const handleAuth = vi.fn();
    render(<LoginView onAuthenticated={handleAuth} />);

    fireEvent.change(screen.getByLabelText(/Analyst Email/i), {
      target: { value: session.user.email },
    });
    fireEvent.change(screen.getByLabelText(/^Password$/i), {
      target: { value: 'WrongPassword' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^Sign In$/i }));

    expect(await screen.findByText('Email or password is incorrect.')).toBeInTheDocument();
    expect(handleAuth).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reports an unavailable API without authenticating locally', async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError('network unavailable'));
    vi.stubGlobal('fetch', fetchMock);
    const handleAuth = vi.fn();
    render(<LoginView onAuthenticated={handleAuth} />);

    fireEvent.change(screen.getByLabelText(/Analyst Email/i), {
      target: { value: session.user.email },
    });
    fireEvent.change(screen.getByLabelText(/^Password$/i), {
      target: { value: 'SecurePass123!' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^Sign In$/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to reach the sign-in service/i);
    expect(handleAuth).not.toHaveBeenCalled();
  });
});
