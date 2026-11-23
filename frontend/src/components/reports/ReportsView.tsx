import React, { useState } from 'react';
import {
  FileText,
  Download,
  Calendar,
  FileSpreadsheet,
  FileJson,
  File,
} from 'lucide-react';

interface ReportsViewProps {
  onNavigateHome: () => void;
}

type ReportFormat = 'CSV' | 'JSON' | 'PDF Summary';

const templates = [
  'Suspicious Activity Report (SAR) Summary',
  'Transaction Ledger Audit Export',
  'Mule Network Topology Snapshot',
];

export const ReportsView: React.FC<ReportsViewProps> = ({ onNavigateHome }) => {
  const [selectedTemplate, setSelectedTemplate] = useState<string>(templates[0]);
  const [format, setFormat] = useState<ReportFormat>('CSV');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const handleGenerate = () => {
    const header = `${selectedTemplate}\nFormat: ${format}\nRange: ${startDate || 'N/A'} to ${endDate || 'N/A'}\n`;
    const blob = new Blob([header], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${selectedTemplate.replace(/\s+/g, '_').toLowerCase()}.${format === 'PDF Summary' ? 'txt' : format.toLowerCase()}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const formatIcon = (f: ReportFormat) => {
    if (f === 'CSV') return <FileSpreadsheet className="h-4 w-4" />;
    if (f === 'JSON') return <FileJson className="h-4 w-4" />;
    return <File className="h-4 w-4" />;
  };

  return (
    <div className="space-y-6 antialiased">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <h1 className="text-2xl font-black text-[#1E1B4B] tracking-tight">Reports & Export</h1>
          <p className="text-sm text-purple-900/60 font-medium mt-1">
            Regulatory and compliance export center
          </p>
        </div>
        <button
          onClick={onNavigateHome}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-[#6D28D9] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition shadow-sm self-start sm:self-auto"
        >
          &larr; Back to Overview
        </button>
      </div>

      <div className="bg-white rounded-2xl border border-purple-200/80 shadow-sm p-6 space-y-4">
        <h3 className="text-sm font-extrabold text-[#1E1B4B]">Report Templates</h3>
        <div className="flex flex-wrap gap-2">
          {templates.map((t) => (
            <button
              key={t}
              onClick={() => setSelectedTemplate(t)}
              className={`px-3 py-1.5 text-xs font-bold rounded-xl transition ${
                selectedTemplate === t
                  ? 'bg-[#7C3AED] text-white shadow-sm'
                  : 'bg-purple-50/60 text-purple-900/70 hover:bg-purple-100 hover:text-[#1E1B4B]'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <label className="block text-xs font-bold text-[#1E1B4B] uppercase tracking-wider">Start Date</label>
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-purple-900/40" />
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-purple-200/80 bg-purple-50/30 text-[#1E1B4B] focus:border-[#7C3AED] focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:bg-white transition"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="block text-xs font-bold text-[#1E1B4B] uppercase tracking-wider">End Date</label>
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-purple-900/40" />
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-purple-200/80 bg-purple-50/30 text-[#1E1B4B] focus:border-[#7C3AED] focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:bg-white transition"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="block text-xs font-bold text-[#1E1B4B] uppercase tracking-wider">Format</label>
            <div className="flex gap-2">
              {(['CSV', 'JSON', 'PDF Summary'] as ReportFormat[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setFormat(f)}
                  className={`flex items-center gap-1.5 px-3 py-2 text-xs font-bold rounded-xl transition ${
                    format === f
                      ? 'bg-[#7C3AED] text-white shadow-sm'
                      : 'bg-purple-50/60 text-purple-900/70 hover:bg-purple-100 hover:text-[#1E1B4B]'
                  }`}
                >
                  {formatIcon(f)}
                  {f}
                </button>
              ))}
            </div>
          </div>
        </div>

        <button
          onClick={handleGenerate}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#6D28D9] to-[#7C3AED] hover:from-[#5B21B6] hover:to-[#6D28D9] shadow-md transition"
        >
          <Download className="h-4 w-4" />
          Generate Local Export Preview
        </button>
      </div>

      <div className="bg-white rounded-2xl border border-purple-200/80 shadow-sm overflow-hidden relative">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#5B21B6] via-[#7C3AED] to-[#9333EA]" />
        <div className="p-6 text-center max-w-md mx-auto space-y-3">
          <div className="h-16 w-16 rounded-2xl bg-[#F4F0FF] border border-purple-200 text-[#7C3AED] flex items-center justify-center mx-auto shadow-inner">
            <FileText className="h-7 w-7" />
          </div>
          <h3 className="text-base font-extrabold text-[#1E1B4B]">
            No Regulatory Reports Generated Yet
          </h3>
          <p className="text-xs text-slate-500 leading-relaxed">
            Generated export previews will appear in history here.
          </p>
        </div>
      </div>
    </div>
  );
};