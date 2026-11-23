import React, { useState } from 'react';
import {
  AlertTriangle,
  AlertOctagon,
  ShieldAlert,
  Info,
  Filter,
  ArrowRight,
  Search,
  X,
} from 'lucide-react';

export type AlertSeverity = 'All' | 'Critical' | 'High' | 'Medium' | 'Low';

export interface AlertItem {
  alert_id: string;
  pattern_type: string;
  primary_account: string;
  risk_score: number;
  detected_at: string;
  status: 'New' | 'Investigating' | 'Dismissed';
  severity: 'Critical' | 'High' | 'Medium' | 'Low';
}

interface AlertsViewProps {
  onNavigateHome: () => void;
}

export const AlertsView: React.FC<AlertsViewProps> = ({ onNavigateHome }) => {
  const [selectedSeverity, setSelectedSeverity] = useState<AlertSeverity>('All');
  const [searchTerm, setSearchTerm] = useState('');

  // By default, no alerts are hardcoded - awaiting backend telemetry stream
  const alerts: AlertItem[] = [];

  // Severity counts initialized at 0
  const severityCounts = {
    Critical: 0,
    High: 0,
    Medium: 0,
    Low: 0,
  };

  const filteredAlerts = alerts.filter((alert) => {
    const matchesSeverity =
      selectedSeverity === 'All' || alert.severity === selectedSeverity;
    const matchesSearch =
      searchTerm === '' ||
      alert.alert_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      alert.primary_account.toLowerCase().includes(searchTerm.toLowerCase()) ||
      alert.pattern_type.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesSeverity && matchesSearch;
  });

  return (
    <div className="space-y-6 antialiased">
      {/* View Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-[#1E1B4B] tracking-tight">
              Suspicious Alerts
            </h1>
            <span className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-700 border border-rose-200">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-500 animate-pulse" />
              Live Triage
            </span>
          </div>
          <p className="text-sm text-purple-900/60 font-medium mt-1">
            Heuristic and machine learning financial anomaly detections
          </p>
        </div>

        <div className="flex items-center gap-2.5 self-start sm:self-auto">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-mono text-[#5B21B6] bg-white border border-purple-200/80 font-semibold shadow-sm">
            <span className="h-2 w-2 rounded-full bg-[#7C3AED] animate-pulse" />
            Ready for FastAPI /api/v1/alerts streaming endpoints
          </div>
          <button
            onClick={onNavigateHome}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-[#6D28D9] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition shadow-sm"
          >
            &larr; Back to Overview
          </button>
        </div>
      </div>

      {/* Severity Summary Strip (Critical, High, Medium, Low initialized at 0) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Critical Card */}
        <div className="bg-white rounded-2xl p-4 border border-rose-200 shadow-sm relative overflow-hidden group hover:shadow-md transition">
          <div className="absolute top-0 left-0 right-0 h-1 bg-rose-500" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-rose-700 uppercase tracking-wider">
              Critical
            </span>
            <div className="h-8 w-8 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center">
              <AlertOctagon className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-[#1E1B4B]">
              {severityCounts.Critical}
            </span>
            <span className="text-[10px] text-rose-600 font-bold bg-rose-50 px-2 py-0.5 rounded-full">
              P0 Severity
            </span>
          </div>
        </div>

        {/* High Card */}
        <div className="bg-white rounded-2xl p-4 border border-orange-200 shadow-sm relative overflow-hidden group hover:shadow-md transition">
          <div className="absolute top-0 left-0 right-0 h-1 bg-orange-500" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-orange-700 uppercase tracking-wider">
              High
            </span>
            <div className="h-8 w-8 rounded-xl bg-orange-50 text-orange-600 flex items-center justify-center">
              <AlertTriangle className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-[#1E1B4B]">
              {severityCounts.High}
            </span>
            <span className="text-[10px] text-orange-600 font-bold bg-orange-50 px-2 py-0.5 rounded-full">
              P1 Severity
            </span>
          </div>
        </div>

        {/* Medium Card */}
        <div className="bg-white rounded-2xl p-4 border border-amber-200 shadow-sm relative overflow-hidden group hover:shadow-md transition">
          <div className="absolute top-0 left-0 right-0 h-1 bg-amber-500" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-amber-700 uppercase tracking-wider">
              Medium
            </span>
            <div className="h-8 w-8 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center">
              <ShieldAlert className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-[#1E1B4B]">
              {severityCounts.Medium}
            </span>
            <span className="text-[10px] text-amber-600 font-bold bg-amber-50 px-2 py-0.5 rounded-full">
              P2 Severity
            </span>
          </div>
        </div>

        {/* Low Card */}
        <div className="bg-white rounded-2xl p-4 border border-purple-200 shadow-sm relative overflow-hidden group hover:shadow-md transition">
          <div className="absolute top-0 left-0 right-0 h-1 bg-[#7C3AED]" />
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-purple-700 uppercase tracking-wider">
              Low
            </span>
            <div className="h-8 w-8 rounded-xl bg-purple-50 text-[#7C3AED] flex items-center justify-center">
              <Info className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-[#1E1B4B]">
              {severityCounts.Low}
            </span>
            <span className="text-[10px] text-purple-600 font-bold bg-purple-50 px-2 py-0.5 rounded-full">
              P3 Severity
            </span>
          </div>
        </div>
      </div>

      {/* Filterable Toolbar: Severity Filter Pills & Search */}
      <div className="bg-white rounded-2xl border border-purple-200/80 p-4 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Severity Filter Pills */}
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-[#7C3AED]" />
          <span className="text-[11px] font-bold text-purple-950 uppercase tracking-wider">
            Severity:
          </span>
          {(['All', 'Critical', 'High', 'Medium'] as AlertSeverity[]).map((severity) => (
            <button
              key={severity}
              onClick={() => setSelectedSeverity(severity)}
              className={`px-3 py-1 text-xs font-bold rounded-xl transition ${
                selectedSeverity === severity
                  ? 'bg-[#7C3AED] text-white shadow-sm'
                  : 'bg-purple-50/60 text-purple-900/70 hover:bg-purple-100 hover:text-[#1E1B4B]'
              }`}
            >
              {severity}
            </button>
          ))}
        </div>

        {/* Search Input */}
        <div className="relative w-full md:max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-purple-900/40" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search by Alert ID, Account, or Pattern..."
            className="w-full pl-9 pr-8 py-1.5 text-xs rounded-xl bg-purple-50/40 border border-purple-200/80 text-[#1E1B4B] placeholder:text-purple-900/40 focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:border-[#7C3AED] focus:bg-white transition"
          />
          {searchTerm && (
            <button
              onClick={() => setSearchTerm('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-purple-900/40 hover:text-purple-900"
              aria-label="Clear search"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Filterable Alert Triage Table & Empty State */}
      <div className="bg-white rounded-2xl border border-purple-200/80 shadow-sm overflow-hidden relative">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-rose-500 via-[#7C3AED] to-[#9333EA]" />

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-purple-100 bg-[#FAF8FF] text-purple-900/70 font-bold uppercase tracking-wider text-[10px]">
                <th className="py-3.5 px-4 font-bold">Alert ID</th>
                <th className="py-3.5 px-4 font-bold">Pattern Type</th>
                <th className="py-3.5 px-4 font-bold">Primary Account</th>
                <th className="py-3.5 px-4 font-bold">Risk Score</th>
                <th className="py-3.5 px-4 font-bold">Detected At</th>
                <th className="py-3.5 px-4 font-bold">Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredAlerts.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-16 px-4 text-center">
                    <div className="flex flex-col items-center justify-center max-w-md mx-auto space-y-3">
                      <div className="h-16 w-16 rounded-2xl bg-[#F4F0FF] border border-purple-200 text-[#7C3AED] flex items-center justify-center shadow-inner">
                        <AlertTriangle className="h-7 w-7" />
                      </div>
                      <h3 className="text-base font-extrabold text-[#1E1B4B]">
                        No Active Suspicious Alerts — Awaiting backend detection engine stream
                      </h3>
                      <p className="text-xs text-slate-500 leading-relaxed">
                        The heuristic anomaly detector and AI pattern recognition feeds are idle. When automated rule engines flag high-velocity structuring or circular flows, triage tickets will queue here.
                      </p>
                      <div className="pt-2">
                        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-mono text-[#5B21B6] bg-[#F4F0FF] border border-purple-200 font-semibold">
                          <span className="h-1.5 w-1.5 rounded-full bg-[#7C3AED]" />
                          FastAPI /api/v1/alerts: Standing By
                        </span>
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                filteredAlerts.map((alert) => (
                  <tr
                    key={alert.alert_id}
                    className="border-b border-purple-50 hover:bg-[#FAF8FF] transition-colors"
                  >
                    <td className="py-3 px-4 font-mono font-bold text-[#1E1B4B]">
                      {alert.alert_id}
                    </td>
                    <td className="py-3 px-4 font-semibold text-purple-950">
                      {alert.pattern_type}
                    </td>
                    <td className="py-3 px-4 font-mono text-[#1E1B4B]">
                      {alert.primary_account}
                    </td>
                    <td className="py-3 px-4 font-black text-rose-600">
                      {alert.risk_score} / 100
                    </td>
                    <td className="py-3 px-4 text-slate-500">
                      {alert.detected_at}
                    </td>
                    <td className="py-3 px-4">
                      <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-[#7C3AED] border border-purple-200">
                        {alert.status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-purple-100 bg-[#FAF8FF] flex flex-col sm:flex-row sm:items-center justify-between text-xs text-purple-900/60 font-medium gap-2">
          <span>Active Severity Filter: {selectedSeverity}</span>
          <button
            onClick={onNavigateHome}
            className="text-[#7C3AED] hover:underline font-bold inline-flex items-center gap-1"
          >
            Overview Dashboard <ArrowRight className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
};
