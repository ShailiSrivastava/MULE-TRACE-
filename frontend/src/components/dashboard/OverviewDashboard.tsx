import React from 'react';
import {
  Wallet,
  AlertTriangle,
  FolderSearch,
  Network,
  Activity,
  ArrowUpRight,
  ShieldCheck,
  CheckCircle2,
  ExternalLink,
  Clock,
  Radio,
  Zap,
} from 'lucide-react';

interface OverviewDashboardProps {
  apiStatus: string | null;
  isLoading: boolean;
  onCheckHealth: () => void;
  onNavigateToTab: (tab: 'transactions' | 'graph' | 'alerts' | 'cases') => void;
}

export const OverviewDashboard: React.FC<OverviewDashboardProps> = ({
  apiStatus,
  isLoading,
  onCheckHealth,
  onNavigateToTab,
}) => {
  return (
    <div className="space-y-6">
      {/* Sleek Royal Purple Gradient Hero Banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#3B0764] via-[#5B21B6] to-[#7C3AED] p-6 md:p-8 text-white shadow-xl shadow-purple-950/20 border border-purple-500/30">
        {/* Subtle Decorative Radial Glows */}
        <div className="absolute -right-16 -top-16 w-64 h-64 bg-purple-400/20 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute right-32 -bottom-20 w-56 h-56 bg-indigo-500/20 rounded-full blur-2xl pointer-events-none" />
        <div className="absolute left-1/3 top-1/2 -translate-y-1/2 w-48 h-48 bg-fuchsia-400/15 rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="max-w-2xl space-y-2">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-white/10 text-purple-100 border border-white/20 backdrop-blur-md">
              <Zap className="h-3.5 w-3.5 text-yellow-300" />
              <span>Real-Time Graph Surveillance</span>
            </div>
            <h1 className="text-2xl md:text-3xl font-black tracking-tight text-white">
              Financial Intelligence Overview
            </h1>
            <p className="text-sm text-purple-100/90 leading-relaxed">
              Real-time monitoring and mule account network telemetry.
            </p>
          </div>

          {/* Frosted-Glass Status & Ping /health Control */}
          <div className="flex flex-wrap items-center gap-3 self-start md:self-auto">
            <span className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold bg-white/10 text-white border border-white/20 backdrop-blur-md shadow-inner">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
              Engine Ready
            </span>
            <button
              onClick={onCheckHealth}
              disabled={isLoading}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold bg-white text-[#5B21B6] hover:bg-purple-50 shadow-lg shadow-purple-950/30 transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
            >
              <Radio className={`h-3.5 w-3.5 ${isLoading ? 'animate-pulse text-[#7C3AED]' : 'text-[#7C3AED]'}`} />
              {isLoading ? 'Pinging API...' : 'Ping /health'}
            </button>
          </div>
        </div>

        {/* Live Status Toast inside Hero if triggered */}
        {apiStatus && (
          <div className="relative z-10 mt-4 p-3.5 rounded-xl bg-black/25 backdrop-blur-md border border-white/20 text-xs font-mono text-purple-100 flex items-center justify-between">
            <span className="truncate">{apiStatus}</span>
            <span className="text-[10px] uppercase font-bold text-emerald-300 px-2 py-0.5 rounded bg-emerald-950/50 border border-emerald-400/30">
              Live Verified
            </span>
          </div>
        )}
      </div>

      {/* KPI Cards Grid (Crisp White + Subtle Purple Borders + Top Purple Accent Bar) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {/* KPI 1: Total Monitored Volume */}
        <div className="bg-white rounded-2xl p-5 border border-purple-200/80 shadow-sm hover:shadow-lg hover:shadow-purple-900/10 hover:-translate-y-0.5 transition-all relative overflow-hidden group">
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#7C3AED] to-[#9333EA]" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Total Monitored Volume
            </span>
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-[#6D28D9] to-[#9333EA] text-white flex items-center justify-center shadow-md shadow-purple-600/25">
              <Wallet className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3.5">
            <div className="text-3xl font-black text-[#1E1B4B] tracking-tight">
              $0.00
            </div>
            <div className="flex items-center gap-1.5 text-xs text-purple-900/60 font-medium mt-1">
              <Clock className="h-3.5 w-3.5 text-[#7C3AED]" />
              <span>Awaiting backend ingestion feed</span>
            </div>
          </div>
        </div>

        {/* KPI 2: Active High-Risk Alerts */}
        <div className="bg-white rounded-2xl p-5 border border-purple-200/80 shadow-sm hover:shadow-lg hover:shadow-purple-900/10 hover:-translate-y-0.5 transition-all relative overflow-hidden group">
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#9333EA] to-[#C084FC]" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Active High-Risk Alerts
            </span>
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-[#7C3AED] to-[#C084FC] text-white flex items-center justify-center shadow-md shadow-purple-600/25">
              <AlertTriangle className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3.5">
            <div className="text-3xl font-black text-[#1E1B4B] tracking-tight">
              0
            </div>
            <div className="flex items-center gap-1.5 text-xs text-purple-900/60 font-medium mt-1">
              <span className="inline-block h-2 w-2 rounded-full bg-purple-400" />
              <span>Rule-based &amp; AI anomaly queue</span>
            </div>
          </div>
        </div>

        {/* KPI 3: Open Investigations */}
        <div className="bg-white rounded-2xl p-5 border border-purple-200/80 shadow-sm hover:shadow-lg hover:shadow-purple-900/10 hover:-translate-y-0.5 transition-all relative overflow-hidden group">
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#5B21B6] to-[#7C3AED]" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Open Investigations
            </span>
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-[#5B21B6] to-[#7C3AED] text-white flex items-center justify-center shadow-md shadow-purple-600/25">
              <FolderSearch className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3.5">
            <div className="text-3xl font-black text-[#1E1B4B] tracking-tight">
              0
            </div>
            <div className="flex items-center gap-1.5 text-xs text-purple-900/60 font-medium mt-1">
              <Activity className="h-3.5 w-3.5 text-[#7C3AED]" />
              <span>Dossiers pending reviewer triage</span>
            </div>
          </div>
        </div>

        {/* KPI 4: Flagged Mule Networks */}
        <div className="bg-white rounded-2xl p-5 border border-purple-200/80 shadow-sm hover:shadow-lg hover:shadow-purple-900/10 hover:-translate-y-0.5 transition-all relative overflow-hidden group">
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#4C1D95] to-[#6D28D9]" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Flagged Mule Networks
            </span>
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-[#4C1D95] to-[#6D28D9] text-white flex items-center justify-center shadow-md shadow-purple-600/25">
              <Network className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3.5">
            <div className="text-3xl font-black text-[#1E1B4B] tracking-tight">
              0
            </div>
            <div className="flex items-center gap-1.5 text-xs text-purple-900/60 font-medium mt-1">
              <ShieldCheck className="h-3.5 w-3.5 text-[#7C3AED]" />
              <span>Circular &amp; multi-hop clusters</span>
            </div>
          </div>
        </div>
      </div>

      {/* Clean Elevated Empty-State Panels Ready for Real FastAPI Endpoints */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Panel 1: Live Suspicious Activity Stream */}
        <div className="bg-white rounded-2xl border border-purple-200/80 shadow-sm hover:shadow-lg hover:shadow-purple-900/10 hover:-translate-y-0.5 transition-all p-6 flex flex-col justify-between relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#6D28D9] via-[#7C3AED] to-[#9333EA]" />
          <div>
            <div className="flex items-center justify-between pb-4 border-b border-purple-100">
              <div className="flex items-center gap-3">
                <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-[#6D28D9] to-[#9333EA] text-white flex items-center justify-center shadow-sm">
                  <Activity className="h-4 w-4" />
                </div>
                <div>
                  <h3 className="text-sm font-extrabold text-[#1E1B4B]">
                    Suspicious Activity Stream
                  </h3>
                  <p className="text-xs text-purple-900/60 font-medium">
                    Real-time transaction ingestion &amp; heuristic flags
                  </p>
                </div>
              </div>
              <button
                onClick={() => onNavigateToTab('alerts')}
                className="text-xs font-bold text-[#7C3AED] hover:text-[#5B21B6] flex items-center gap-1 group"
              >
                View Alerts <ArrowUpRight className="h-3.5 w-3.5 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
              </button>
            </div>

            {/* Empty state content */}
            <div className="py-12 flex flex-col items-center justify-center text-center px-4">
              <div className="h-16 w-16 rounded-2xl bg-[#F4F0FF] border border-purple-200 text-[#7C3AED] flex items-center justify-center mb-3 shadow-inner">
                <Clock className="h-7 w-7" />
              </div>
              <h4 className="text-sm font-bold text-[#1E1B4B]">
                No Suspicious Activity Detected
              </h4>
              <p className="text-xs text-slate-500 max-w-sm mt-1.5 leading-relaxed">
                Telemetry feed is idle. Once backend ingestion triggers transaction events, flagged anomalies will stream directly into this queue.
              </p>
              <div className="mt-4 px-3.5 py-1.5 rounded-full text-[11px] font-mono text-[#5B21B6] bg-[#F4F0FF] border border-purple-200/80 font-semibold">
                FastAPI: /health (Ready)
              </div>
            </div>
          </div>

          <div className="pt-4 border-t border-purple-100 flex items-center justify-between text-xs text-purple-900/60 font-medium">
            <span>Status: Connected to local broker</span>
            <button
              onClick={() => onNavigateToTab('transactions')}
              className="text-[#7C3AED] hover:underline font-bold"
            >
              Browse Transactions &rarr;
            </button>
          </div>
        </div>

        {/* Panel 2: Mule Network Topology Preview */}
        <div className="bg-white rounded-2xl border border-purple-200/80 shadow-sm hover:shadow-lg hover:shadow-purple-900/10 hover:-translate-y-0.5 transition-all p-6 flex flex-col justify-between relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#7C3AED] via-[#9333EA] to-[#C084FC]" />
          <div>
            <div className="flex items-center justify-between pb-4 border-b border-purple-100">
              <div className="flex items-center gap-3">
                <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-[#7C3AED] to-[#C084FC] text-white flex items-center justify-center shadow-sm">
                  <Network className="h-4 w-4" />
                </div>
                <div>
                  <h3 className="text-sm font-extrabold text-[#1E1B4B]">
                    Mule Network Topology
                  </h3>
                  <p className="text-xs text-purple-900/60 font-medium">
                    Cytoscape.js graph rendering canvas
                  </p>
                </div>
              </div>
              <button
                onClick={() => onNavigateToTab('graph')}
                className="text-xs font-bold text-[#7C3AED] hover:text-[#5B21B6] flex items-center gap-1 group"
              >
                Open Full Graph <ArrowUpRight className="h-3.5 w-3.5 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
              </button>
            </div>

            {/* Empty state content */}
            <div className="py-12 flex flex-col items-center justify-center text-center px-4">
              <div className="h-16 w-16 rounded-2xl bg-[#F4F0FF] border border-purple-200 text-[#7C3AED] flex items-center justify-center mb-3 shadow-inner">
                <Network className="h-7 w-7" />
              </div>
              <h4 className="text-sm font-bold text-[#1E1B4B]">
                Graph Canvas Ready
              </h4>
              <p className="text-xs text-slate-500 max-w-sm mt-1.5 leading-relaxed">
                The Cytoscape.js visualization engine is initialized. Suspicious money mule clusters and flow loops will render here when transaction graphs are queried.
              </p>
              <div className="mt-4 px-3.5 py-1.5 rounded-full text-[11px] font-mono text-[#5B21B6] bg-[#F4F0FF] border border-purple-200/80 font-semibold">
                Cytoscape.js 3.30 + Recharts 2.13 (Mounted)
              </div>
            </div>
          </div>

          <div className="pt-4 border-t border-purple-100 flex items-center justify-between text-xs text-purple-900/60 font-medium">
            <span>Visualizer: Directed bipartite graph</span>
            <button
              onClick={() => onNavigateToTab('graph')}
              className="text-[#7C3AED] hover:underline font-bold"
            >
              Launch Visualizer &rarr;
            </button>
          </div>
        </div>
      </div>

      {/* Backend Engine & API Integration Card */}
      <div className="bg-white rounded-2xl border border-purple-200/80 p-6 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#3B0764] to-[#7C3AED]" />
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-extrabold text-[#1E1B4B]">
              Backend Engine &amp; API Integration
            </h3>
            <p className="text-xs text-purple-900/60 font-medium mt-0.5">
              Probe the FastAPI microservice and review OpenAPI specifications.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-[#6D28D9] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition"
            >
              OpenAPI Swagger <ExternalLink className="h-3 w-3" />
            </a>
            <button
              onClick={onCheckHealth}
              disabled={isLoading}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-[#7C3AED] hover:bg-[#6D28D9] text-white shadow-sm shadow-purple-600/30 transition disabled:opacity-50"
            >
              <Radio className="h-3.5 w-3.5" />
              {isLoading ? 'Pinging...' : 'Check Backend Health'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
