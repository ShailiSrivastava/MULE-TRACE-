import { useState } from 'react';
import {
  CheckCircle2,
  Database,
  Layers,
  Network,
  Radio,
  Server,
  Users,
} from 'lucide-react';

export default function App() {
  const [apiStatus, setApiStatus] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const checkBackendHealth = async () => {
    setIsLoading(true);
    setApiStatus(null);
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
    try {
      const res = await fetch(`${baseUrl}/health`);
      if (res.ok) {
        const data = await res.json();
        setApiStatus(`Connected: ${JSON.stringify(data)}`);
      } else {
        setApiStatus(`Error: HTTP ${res.status}`);
      }
    } catch {
      setApiStatus('Unable to connect (ensure FastAPI is running on ' + baseUrl + ')');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100 p-6 md:p-12">
      <div className="max-w-5xl mx-auto space-y-8">
        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-center justify-between border-b pb-6 gap-4">
          <div>
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-lg bg-blue-600 text-white shadow-md">
                <Network className="h-6 w-6" />
              </div>
              <h1 className="text-3xl font-extrabold tracking-tight">MuleTrace</h1>
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              Full-Stack Application Foundation & Trace Analysis Platform
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Foundation Initialized
            </span>
          </div>
        </header>

        {/* Team Collaboration Notice */}
        <section className="bg-white dark:bg-slate-900 rounded-xl p-5 border shadow-sm">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-300">
            <Users className="h-4 w-4 text-blue-600" />
            <span>Collaborators: Shaili &amp; Raj</span>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Repository initialized and configured for synchronized local development on Windows.
          </p>
        </section>

        {/* Foundation Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Frontend Card */}
          <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border shadow-sm space-y-4">
            <div className="flex items-center gap-2 font-bold text-base text-slate-800 dark:text-slate-200">
              <Layers className="h-5 w-5 text-indigo-600" />
              <h3>Frontend Stack</h3>
            </div>
            <ul className="text-xs space-y-2 text-slate-600 dark:text-slate-300">
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-indigo-500"></span>
                React 18 &amp; TypeScript
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-indigo-500"></span>
                Vite Bundler &amp; Dev Server
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-indigo-500"></span>
                Tailwind CSS &amp; shadcn/ui Utility
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-indigo-500"></span>
                Cytoscape.js &amp; Recharts
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-indigo-500"></span>
                Vitest &amp; React Testing Library
              </li>
            </ul>
          </div>

          {/* Backend Card */}
          <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border shadow-sm space-y-4">
            <div className="flex items-center gap-2 font-bold text-base text-slate-800 dark:text-slate-200">
              <Server className="h-5 w-5 text-emerald-600" />
              <h3>Backend Stack</h3>
            </div>
            <ul className="text-xs space-y-2 text-slate-600 dark:text-slate-300">
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                Python 3 &amp; FastAPI
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                SQLAlchemy 2.0 ORM
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                PostgreSQL Driver (psycopg2)
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                Pydantic Settings &amp; CORS
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                Pytest &amp; HTTPX Test Client
              </li>
            </ul>
          </div>

          {/* Testing & Verification Card */}
          <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border shadow-sm space-y-4">
            <div className="flex items-center gap-2 font-bold text-base text-slate-800 dark:text-slate-200">
              <Database className="h-5 w-5 text-purple-600" />
              <h3>API &amp; Testing</h3>
            </div>
            <ul className="text-xs space-y-2 text-slate-600 dark:text-slate-300">
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-purple-500"></span>
                Postman Collection &amp; Environment
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-purple-500"></span>
                Automated Health Check Route
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-purple-500"></span>
                Interactive OpenAPI Swagger (/docs)
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-purple-500"></span>
                Vitest Component Unit Tests
              </li>
            </ul>
          </div>
        </div>

        {/* Interactive Backend Probe */}
        <section className="bg-white dark:bg-slate-900 rounded-xl p-6 border shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-base text-slate-800 dark:text-slate-200">
              <Radio className="h-5 w-5 text-blue-600" />
              <h3>Backend Connectivity Check</h3>
            </div>
            <button
              onClick={checkBackendHealth}
              disabled={isLoading}
              className="px-4 py-2 text-xs font-semibold rounded-md bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 transition"
            >
              {isLoading ? 'Checking...' : 'Ping /health'}
            </button>
          </div>
          {apiStatus && (
            <div className="p-3 rounded-lg text-xs font-mono bg-slate-100 dark:bg-slate-800 border">
              {apiStatus}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
