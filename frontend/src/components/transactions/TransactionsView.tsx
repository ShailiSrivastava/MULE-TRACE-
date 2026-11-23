import React, { useState, useRef } from 'react';
import {
  ArrowLeftRight,
  Search,
  Filter,
  UploadCloud,
  FileSpreadsheet,
  X,
  Database,
  ArrowRight,
  CheckCircle2,
  AlertCircle,
  FileText,
  Trash2,
  ChevronDown,
} from 'lucide-react';

export interface Transaction {
  transaction_id: string;
  timestamp: string;
  source_account: string;
  destination_account: string;
  amount: number;
  currency: string;
  channel: string;
  risk_status: 'Flagged' | 'Under Review' | 'Cleared';
}

interface TransactionsViewProps {
  onNavigateHome: () => void;
}

const EXPECTED_CSV_COLUMNS = [
  'transaction_id',
  'source_account',
  'destination_account',
  'amount',
  'currency',
  'timestamp',
  'channel',
];

export const TransactionsView: React.FC<TransactionsViewProps> = ({
  onNavigateHome,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [isDropzoneOpen, setIsDropzoneOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // By default, no transactions are loaded yet (connecting to real FastAPI endpoint)
  const transactions: Transaction[] = [];

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (file.name.endsWith('.csv')) {
        setSelectedFile(file);
      }
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (file.name.endsWith('.csv')) {
        setSelectedFile(file);
      }
    }
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  return (
    <div className="space-y-6 antialiased">
      {/* View Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-[#1E1B4B] tracking-tight">
              Transactions Monitor
            </h1>
            <span className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-purple-100 text-[#7C3AED] border border-purple-200">
              <span className="h-1.5 w-1.5 rounded-full bg-[#7C3AED]" />
              Audit Ledger
            </span>
          </div>
          <p className="text-sm text-purple-900/60 font-medium mt-1">
            High-throughput financial ledger and transaction audit trail
          </p>
        </div>

        <div className="flex items-center gap-2.5 self-start sm:self-auto">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-mono text-[#5B21B6] bg-white border border-purple-200/80 font-semibold shadow-sm">
            <span className="h-2 w-2 rounded-full bg-[#7C3AED] animate-pulse" />
            Ready for FastAPI /api/v1/transactions endpoints
          </div>
          <button
            onClick={onNavigateHome}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-[#6D28D9] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition shadow-sm"
          >
            &larr; Back to Overview
          </button>
        </div>
      </div>

      {/* Top Toolbar: Search, Filter, and CSV Upload Toggle */}
      <div className="bg-white rounded-2xl border border-purple-200/80 p-4 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Search Input */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-purple-900/40" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search by Account ID or Transaction ID..."
            className="w-full pl-10 pr-9 py-2 text-xs rounded-xl bg-purple-50/40 border border-purple-200/80 text-[#1E1B4B] placeholder:text-purple-900/40 focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:border-[#7C3AED] focus:bg-white transition"
          />
          {searchTerm && (
            <button
              onClick={() => setSearchTerm('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-purple-900/40 hover:text-purple-900 p-0.5"
              aria-label="Clear search"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Filter Dropdown & CSV Batch Button */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Status Filter */}
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-[#7C3AED]" />
            <div className="relative">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Filter by Risk Status"
                className="appearance-none pl-3 pr-8 py-2 text-xs font-bold text-[#1E1B4B] bg-purple-50/40 hover:bg-purple-50 border border-purple-200/80 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:border-[#7C3AED] transition cursor-pointer"
              >
                <option value="All">All Statuses</option>
                <option value="Flagged">Flagged</option>
                <option value="Under Review">Under Review</option>
                <option value="Cleared">Cleared</option>
              </select>
              <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-purple-900/40 pointer-events-none" />
            </div>
          </div>

          {/* Upload CSV Batch Button */}
          <button
            onClick={() => setIsDropzoneOpen((prev) => !prev)}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition shadow-sm ${
              isDropzoneOpen
                ? 'bg-purple-100 text-[#5B21B6] border border-purple-300'
                : 'bg-gradient-to-r from-[#6D28D9] to-[#7C3AED] hover:from-[#5B21B6] hover:to-[#6D28D9] text-white shadow-purple-600/25'
            }`}
          >
            <UploadCloud className="h-4 w-4" />
            <span>{isDropzoneOpen ? 'Close CSV Panel' : 'Upload CSV Batch'}</span>
          </button>
        </div>
      </div>

      {/* Collapsible CSV Upload Dropzone */}
      {isDropzoneOpen && (
        <div className="bg-white rounded-2xl border border-purple-200/90 p-6 shadow-md space-y-5 animate-in fade-in-50 duration-200">
          <div className="flex items-center justify-between pb-3 border-b border-purple-100">
            <div className="flex items-center gap-2.5">
              <div className="h-8 w-8 rounded-xl bg-purple-50 text-[#7C3AED] flex items-center justify-center">
                <FileSpreadsheet className="h-4 w-4" />
              </div>
              <div>
                <h3 className="text-sm font-extrabold text-[#1E1B4B]">
                  Batch Transaction Ingestion (CSV)
                </h3>
                <p className="text-xs text-purple-900/60 font-medium">
                  Staging zone for multi-record financial event files
                </p>
              </div>
            </div>
            <button
              onClick={() => setIsDropzoneOpen(false)}
              className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100"
              aria-label="Close dropzone"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Hidden File Input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleFileChange}
            className="hidden"
            id="csv-file-upload"
          />

          {!selectedFile ? (
            /* Empty Drop Area */
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all ${
                isDragging
                  ? 'border-[#7C3AED] bg-purple-50/70 scale-[1.01]'
                  : 'border-purple-200/80 bg-purple-50/20 hover:bg-purple-50/50 hover:border-[#7C3AED]'
              }`}
            >
              <div className="h-12 w-12 rounded-2xl bg-white border border-purple-200 text-[#7C3AED] flex items-center justify-center mx-auto mb-3 shadow-sm">
                <UploadCloud className="h-6 w-6" />
              </div>
              <p className="text-xs font-bold text-[#1E1B4B]">
                Click to browse or drag and drop a .csv batch file
              </p>
              <p className="text-[11px] text-purple-900/60 font-medium mt-1">
                Accepted format: Standard comma-separated transaction records (UTF-8)
              </p>
            </div>
          ) : (
            /* Selected File Preview Card */
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-purple-50/50 border border-purple-200 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-xl bg-white border border-purple-200 text-[#7C3AED] flex items-center justify-center shadow-sm">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="text-xs font-bold text-[#1E1B4B]">
                      {selectedFile.name}
                    </div>
                    <div className="text-[10px] text-purple-900/60 font-medium mt-0.5">
                      Size: {formatFileSize(selectedFile.size)} &bull; Ready for review
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                    <CheckCircle2 className="h-3 w-3" />
                    CSV Validated
                  </span>
                  <button
                    onClick={handleRemoveFile}
                    className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition"
                    title="Remove file"
                    aria-label="Remove file"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {/* Expected Column Headers Preview Box */}
              <div className="p-4 rounded-xl bg-white border border-purple-200/80 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-[#1E1B4B] flex items-center gap-1.5">
                    <Database className="h-3.5 w-3.5 text-[#7C3AED]" />
                    Expected CSV Column Headers Schema
                  </span>
                  <span className="text-[10px] font-semibold text-purple-900/60">
                    7 Standard Attributes
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {EXPECTED_CSV_COLUMNS.map((col) => (
                    <span
                      key={col}
                      className="px-2.5 py-1 rounded-lg text-[11px] font-mono text-[#5B21B6] bg-purple-50 border border-purple-200/70 font-semibold"
                    >
                      {col}
                    </span>
                  ))}
                </div>
              </div>

              {/* Notice */}
              <div className="flex items-center justify-between pt-1">
                <span className="text-[11px] text-purple-900/60 font-medium flex items-center gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5 text-[#7C3AED]" />
                  Staged locally. Ready for FastAPI batch ingestion endpoint (no network call executed).
                </span>
                <button
                  type="button"
                  onClick={() => alert(`Staged file: ${selectedFile.name} ready for backend upload endpoint.`)}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-[#7C3AED] hover:bg-[#6D28D9] text-white shadow-sm transition"
                >
                  Confirm Ingestion
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Responsive Transaction Ledger Table & Empty State */}
      <div className="bg-white rounded-2xl border border-purple-200/80 shadow-sm overflow-hidden relative">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#6D28D9] via-[#7C3AED] to-[#9333EA]" />

        {/* Table Container */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-purple-100 bg-[#FAF8FF] text-purple-900/70 font-bold uppercase tracking-wider text-[10px]">
                <th className="py-3.5 px-4 font-bold">Transaction ID</th>
                <th className="py-3.5 px-4 font-bold">Timestamp</th>
                <th className="py-3.5 px-4 font-bold">Source Account</th>
                <th className="py-3.5 px-4 font-bold">Destination Account</th>
                <th className="py-3.5 px-4 font-bold">Amount</th>
                <th className="py-3.5 px-4 font-bold">Channel</th>
                <th className="py-3.5 px-4 font-bold">Risk Status</th>
              </tr>
            </thead>
            <tbody>
              {transactions.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-16 px-4 text-center">
                    <div className="flex flex-col items-center justify-center max-w-md mx-auto space-y-3">
                      <div className="h-16 w-16 rounded-2xl bg-[#F4F0FF] border border-purple-200 text-[#7C3AED] flex items-center justify-center shadow-inner">
                        <ArrowLeftRight className="h-7 w-7" />
                      </div>
                      <h3 className="text-base font-extrabold text-[#1E1B4B]">
                        No Transactions Loaded Yet
                      </h3>
                      <p className="text-xs text-slate-500 leading-relaxed">
                        The transaction ledger is ready. Once backend ingestion triggers transaction events or a CSV batch is uploaded, ledger records will stream into this table.
                      </p>
                      <div className="pt-2">
                        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-mono text-[#5B21B6] bg-[#F4F0FF] border border-purple-200 font-semibold">
                          <span className="h-1.5 w-1.5 rounded-full bg-[#7C3AED]" />
                          FastAPI /api/v1/transactions: Standing By
                        </span>
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                transactions.map((tx) => (
                  <tr
                    key={tx.transaction_id}
                    className="border-b border-purple-50 hover:bg-[#FAF8FF] transition-colors"
                  >
                    <td className="py-3 px-4 font-mono font-bold text-[#1E1B4B]">
                      {tx.transaction_id}
                    </td>
                    <td className="py-3 px-4 text-slate-500">{tx.timestamp}</td>
                    <td className="py-3 px-4 font-mono text-[#1E1B4B]">
                      {tx.source_account}
                    </td>
                    <td className="py-3 px-4 font-mono text-[#1E1B4B]">
                      {tx.destination_account}
                    </td>
                    <td className="py-3 px-4 font-black text-[#1E1B4B]">
                      ${tx.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className="py-3 px-4 text-slate-600">{tx.channel}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold ${
                          tx.risk_status === 'Flagged'
                            ? 'bg-rose-100 text-rose-700 border border-rose-200'
                            : tx.risk_status === 'Under Review'
                            ? 'bg-amber-100 text-amber-700 border border-amber-200'
                            : 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                        }`}
                      >
                        {tx.risk_status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Ledger Footer Status */}
        <div className="p-4 border-t border-purple-100 bg-[#FAF8FF] flex flex-col sm:flex-row sm:items-center justify-between text-xs text-purple-900/60 font-medium gap-2">
          <span>Displaying 0 of 0 recorded financial events</span>
          <div className="flex items-center gap-3">
            <span>Filter: {statusFilter}</span>
            <span>&bull;</span>
            <button
              onClick={onNavigateHome}
              className="text-[#7C3AED] hover:underline font-bold inline-flex items-center gap-1"
            >
              Return to Overview <ArrowRight className="h-3 w-3" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
