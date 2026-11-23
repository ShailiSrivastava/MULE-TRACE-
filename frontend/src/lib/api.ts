export type UserRole = 'ADMIN' | 'INVESTIGATOR' | 'ANALYST';

export interface AuthenticatedUser {
  id: string;
  email: string;
  display_name: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface AuthSession {
  accessToken: string;
  expiresIn: number;
  user: AuthenticatedUser;
}

interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
}

export function getApiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');
}

async function readResponse(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function isTokenResponse(value: unknown): value is TokenResponse {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<TokenResponse>;
  return (
    typeof candidate.access_token === 'string' &&
    candidate.token_type === 'bearer' &&
    typeof candidate.expires_in === 'number'
  );
}

function isAuthenticatedUser(value: unknown): value is AuthenticatedUser {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<AuthenticatedUser>;
  return (
    typeof candidate.id === 'string' &&
    typeof candidate.email === 'string' &&
    typeof candidate.role === 'string' &&
    typeof candidate.is_active === 'boolean'
  );
}

function safeLoginError(status: number): string {
  if (status === 401) return 'Email or password is incorrect.';
  if (status === 503) return 'The sign-in service is temporarily unavailable.';
  return 'Sign-in could not be completed. Please try again.';
}

export async function authenticateUser(
  email: string,
  password: string,
  request: typeof fetch = fetch,
): Promise<AuthSession> {
  const baseUrl = getApiBaseUrl();
  const tokenResponse = await request(`${baseUrl}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const tokenPayload = await readResponse(tokenResponse);
  if (!tokenResponse.ok) throw new Error(safeLoginError(tokenResponse.status));
  if (!isTokenResponse(tokenPayload)) {
    throw new Error('The sign-in service returned an invalid response.');
  }

  const userResponse = await request(`${baseUrl}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${tokenPayload.access_token}` },
  });
  const userPayload = await readResponse(userResponse);
  if (!userResponse.ok || !isAuthenticatedUser(userPayload)) {
    throw new Error('Your sign-in could not be verified. Please try again.');
  }

  return {
    accessToken: tokenPayload.access_token,
    expiresIn: tokenPayload.expires_in,
    user: userPayload,
  };
}
