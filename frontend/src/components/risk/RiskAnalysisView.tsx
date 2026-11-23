import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import {
  ShieldAlert,
  Activity,
  TrendingUp,
  BrainCircuit,
} from 'lucide-react';

interface RiskAnalysisViewProps {
  onNavigateHome: () => void;
}

const scoreDistribution = [
  { range: '0-20', count: 0 },
  { range: '21-40', count: 0 },
  { range: '41-60', count: 0 },
  { range: '61-80', count: 0 },
  { range: '81-100', count: 0 },
];

export const RiskAnalysisView: React.FC<RiskAnalysisViewProps> = ({ onNavigateHome }) => {
  return (
    <div className="space-y-6 antialiased">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <h1 className="text-2xl font-black text-[#1E1B4B] tracking-tight">Risk Analysis</h1>
          <p className="text-sm text-purple-900/60 font-medium mt-1">
            Behavioral analytics and portfolio risk scoring
          </p>
        </div>
        <button
          onClick={onNavigateHome}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-[#6D28D9] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition shadow-sm self-start sm:self-auto"
        >
          &larr; Back to Overview
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Average Portfolio Risk Score', value: '—', icon: TrendingUp },
          { label: 'High-Velocity Accounts', value: '0', icon: Activity },
          { label: 'Structuring Flags', value: '0', icon: ShieldAlert },
          { label: 'Model Confidence', value: '—', icon: BrainCircuit },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="bg-white rounded-2xl p-4 border border-purple-200 shadow-sm relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-1 bg-[#7C3AED]" />
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-purple-700 uppercase tracking-wider">{card.label}</span>
                <div className="h-8 w-8 rounded-xl bg-purple-50 text-[#7C3AED] flex items-center justify-center">
                  <Icon className="h-4 w-4" />
                </div>
              </div>
              <div className="mt-2 text-2xl font-black text-[#1E1B4B]">{card.value}</div>
            </div>
          );
        })}
      </div>

      <div className="bg-white rounded-2xl border border-purple-200/80 shadow-sm p-6">
        <h3 className="text-sm font-extrabold text-[#1E1B4B] mb-4">Risk Score Distribution</h3>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={scoreDistribution}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="range" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="#7C3AED" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-purple-200/80 shadow-sm overflow-hidden relative">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#5B21B6] via-[#7C3AED] to-[#9333EA]" />
        <div className="p-6 text-center max-w-md mx-auto space-y-3">
          <div className="h-16 w-16 rounded-2xl bg-[#F4F0FF] border border-purple-200 text-[#7C3AED] flex items-center justify-center mx-auto shadow-inner">
            <ShieldAlert className="h-7 w-7" />
          </div>
          <h3 className="text-base font-extrabold text-[#1E1B4B]">
            No Risk Scores Computed Yet — Connect backend scoring engine or ingest transactions to analyze account risk
          </h3>
          <p className="text-xs text-slate-500 leading-relaxed">
            Risk scores will populate once transaction data is ingested and the scoring engine runs.
          </p>
        </div>
      </div>
    </div>
  );
};