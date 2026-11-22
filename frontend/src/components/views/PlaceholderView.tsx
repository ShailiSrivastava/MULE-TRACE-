import React from 'react';
import {
  ArrowLeftRight,
  Network,
  AlertTriangle,
  FolderSearch,
  ShieldAlert,
  FileSpreadsheet,
  Layers,
  ArrowRight,
} from 'lucide-react';
import { NavTabId } from '../../types/navigation';

interface PlaceholderViewProps {
  tab: NavTabId;
  onNavigateHome: () => void;
}

const TAB_CONFIGS: Record<
  NavTabId,
  {
    title: string;
    subtitle: string;
    icon: React.ComponentType<{ className?: string }>;
    description: string;
    integrationNote: string;
  }
> = {
  overview: {
    title: 'Overview Dashboard',
    subtitle: 'System telemetry and KPI overview',
    icon: Layers,
    description: 'System overview view.',
    integrationNote: 'FastAPI /health',
  },
  transactions: {
    title: 'Transactions Monitor',
    subtitle: 'High-throughput financial ledger and transaction audit trail',
    icon: ArrowLeftRight,
    description:
      'Monitor incoming and outgoing payments with multi-attribute filtering (amount, velocity, accounts, counterparty bank).',
    integrationNote: 'Ready for FastAPI /api/v1/transactions endpoints',
  },
  graph: {
    title: 'Mule Network Graph',
    subtitle: 'Interactive multi-hop network visualization powered by Cytoscape.js',
    icon: Network,
    description:
      'Trace fund flows across mule clusters, layer accounts, and cash-out nodes in an interactive graph layout.',
    integrationNote: 'Ready for Cytoscape.js graph state and graph query endpoints',
  },
  alerts: {
    title: 'Suspicious Alerts',
    subtitle: 'Heuristic and machine learning financial anomaly detections',
    icon: AlertTriangle,
    description:
      'Triage active alerts generated from structuring, rapid fund movement, circular flows, and velocity spikes.',
    integrationNote: 'Ready for FastAPI /api/v1/alerts streaming endpoints',
  },
  cases: {
    title: 'Investigation Cases',
    subtitle: 'Compliance and fraud analyst case management dossiers',
    icon: FolderSearch,
    description:
      'Manage investigation workflows, attach transaction evidence, collaborate with team members, and prepare SAR filings.',
    integrationNote: 'Ready for FastAPI /api/v1/cases persistence models',
  },
  risk: {
    title: 'Risk Analysis',
    subtitle: 'Account risk scoring and behavioral pattern metrics',
    icon: ShieldAlert,
    description:
      'Evaluate account risk profiles, historical score trajectories, and geographical velocity anomalies.',
    integrationNote: 'Ready for FastAPI /api/v1/risk analytical endpoints',
  },
  reports: {
    title: 'Reports & Export',
    subtitle: 'Regulatory filing exports and audit dossier generation',
    icon: FileSpreadsheet,
    description:
      'Generate automated compliance reports, export CSV/JSON transaction audit logs, and export visual network evidence.',
    integrationNote: 'Ready for FastAPI report generation and file export streams',
  },
};

export const PlaceholderView: React.FC<PlaceholderViewProps> = ({
  tab,
  onNavigateHome,
}) => {
  const config = TAB_CONFIGS[tab];
  const Icon = config.icon;

  return (
    <div className="space-y-6">
      {/* View Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <h1 className="text-2xl font-black text-[#1E1B4B] tracking-tight">
            {config.title}
          </h1>
          <p className="text-sm text-purple-900/60 font-medium mt-1">
            {config.subtitle}
          </p>
        </div>
        <button
          onClick={onNavigateHome}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-[#6D28D9] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition self-start sm:self-auto shadow-sm"
        >
          &larr; Back to Overview
        </button>
      </div>

      {/* Main Elevated Card with Top Accent Bar */}
      <div className="bg-white rounded-2xl border border-purple-200/80 p-8 md:p-12 shadow-sm hover:shadow-lg hover:shadow-purple-900/10 hover:-translate-y-0.5 transition-all text-center flex flex-col items-center relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#6D28D9] via-[#7C3AED] to-[#9333EA]" />

        <div className="h-16 w-16 rounded-2xl bg-gradient-to-tr from-[#6D28D9] to-[#9333EA] text-white flex items-center justify-center mb-4 shadow-lg shadow-purple-600/30">
          <Icon className="h-8 w-8" />
        </div>

        <h3 className="text-lg font-bold text-[#1E1B4B]">Module Integration</h3>
        <p className="text-sm text-slate-500 max-w-lg mt-2 leading-relaxed">
          {config.description}
        </p>

        <div className="mt-6 inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-mono text-[#5B21B6] bg-[#F4F0FF] border border-purple-200/80 font-semibold shadow-sm">
          <span className="h-2 w-2 rounded-full bg-[#7C3AED] animate-pulse" />
          {config.integrationNote}
        </div>

        <div className="mt-8 pt-6 border-t border-purple-100 w-full max-w-md flex items-center justify-between text-xs text-purple-900/60 font-medium">
          <span>Enterprise Financial Intelligence</span>
          <button
            onClick={onNavigateHome}
            className="text-[#7C3AED] hover:text-[#5B21B6] font-bold flex items-center gap-1"
          >
            Dashboard <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
