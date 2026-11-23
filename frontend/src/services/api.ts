const BASE = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';

function token() {
  try { return localStorage.getItem('muletrace_token'); } catch { return null; }
}

async function request(path: string, init?: RequestInit) {
  const headers: Record<string, string> = { ...(init?.headers as any) };
  const t = token();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  try {
    const res = await fetch(`${BASE}${path}`, { ...init, headers });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function loginAnalyst(email: string, password: string) {
  try {
    const res = await fetch(`${BASE}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    try { localStorage.setItem('muletrace_token', data.access_token); } catch {}
    return data;
  } catch {
    return null;
  }
}

export const getHealth = () => request('/health');
export const getDashboardOverview = () => request('/api/v1/dashboard/overview');
export const getTransactions = (search?: string, status?: string) => {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (status) params.set('status', status);
  const q = params.toString();
  return request(`/api/v1/transactions${q ? `?${q}` : ''}`);
};
export const createTransaction = (payload: any) => request('/api/v1/transactions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
export async function uploadTransactionsCsv(file: File) {
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch(`${BASE}/api/v1/transactions/upload-csv`, { method: 'POST', body: form, headers: token() ? { Authorization: `Bearer ${token()}` } : {} });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}
export const getNetworkGraph = (hops = 1) => request(`/api/v1/graph/network?hops=${hops}`);
export const getAlerts = (severity?: string) => request(`/api/v1/alerts${severity ? `?severity=${severity}` : ''}`);
export const updateAlertStatus = (id: number, status: string) => request(`/api/v1/alerts/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
export const getCases = () => request('/api/v1/cases');
export const createCase = (payload: any) => request('/api/v1/cases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
export const updateCase = (id: number, payload: any) => request(`/api/v1/cases/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
export const getRiskAnalysis = () => request('/api/v1/risk/analysis');
export async function exportReport(report_type: string, format: string) {
  try {
    const res = await fetch(`${BASE}/api/v1/reports/export?report_type=${report_type}&format=${format}`, { headers: token() ? { Authorization: `Bearer ${token()}` } : {} });
    if (!res.ok) return null;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `report.${format === 'csv' ? 'csv' : 'json'}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    return true;
  } catch { return null; }
}