import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  FolderSearch,
  Plus,
  X,
  FolderPlus,
} from 'lucide-react';

export type CaseStatus =
  | 'All Cases'
  | 'Open'
  | 'In Review'
  | 'Escalated / SAR Filed'
  | 'Closed';

export type CasePriority = 'Low' | 'Medium' | 'High' | 'Critical';

export interface CaseItem {
  id: string;
  title: string;
  primaryAccountId: string;
  priority: CasePriority;
  status: 'Open' | 'In Review' | 'Escalated / SAR Filed' | 'Closed';
  notes?: string;
  createdAt: string;
}

export const caseSchema = z.object({
  title: z
    .string()
    .min(1, 'Case title is required')
    .min(3, 'Case title must be at least 3 characters'),
  primaryAccountId: z
    .string()
    .min(1, 'Primary account ID is required')
    .min(3, 'Primary account ID must be at least 3 characters'),
  priority: z.enum(['Low', 'Medium', 'High', 'Critical']),
  notes: z.string().optional(),
});

export type CaseFormValues = z.infer<typeof caseSchema>;

interface CasesViewProps {
  onNavigateHome: () => void;
}

export const CasesView: React.FC<CasesViewProps> = ({ onNavigateHome }) => {
  const [selectedStatus, setSelectedStatus] = useState<CaseStatus>('All Cases');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [cases, setCases] = useState<CaseItem[]>([]);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CaseFormValues>({
    resolver: zodResolver(caseSchema),
    defaultValues: {
      title: '',
      primaryAccountId: '',
      priority: 'High',
      notes: '',
    },
    mode: 'onBlur',
  });

  const onSubmit = (data: CaseFormValues) => {
    // Validated locally without hitting unconfirmed backend routes
    const newCase: CaseItem = {
      id: `CASE-${Date.now().toString().slice(-4)}`,
      title: data.title,
      primaryAccountId: data.primaryAccountId,
      priority: data.priority,
      status: 'Open',
      notes: data.notes || '',
      createdAt: 'Just now',
    };

    setCases((prev) => [newCase, ...prev]);
    setIsModalOpen(false);
    reset();
  };

  const filteredCases = cases.filter((c) => {
    if (selectedStatus === 'All Cases') return true;
    return c.status === selectedStatus;
  });

  return (
    <div className="space-y-6 antialiased">
      {/* View Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-[#1E1B4B] tracking-tight">
              Investigation Cases
            </h1>
            <span className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-purple-100 text-[#7C3AED] border border-purple-200">
              <span className="h-1.5 w-1.5 rounded-full bg-[#7C3AED]" />
              Dossier Manager
            </span>
          </div>
          <p className="text-sm text-purple-900/60 font-medium mt-1">
            Compliance and fraud analyst case management dossiers
          </p>
        </div>

        <div className="flex items-center gap-2.5 self-start sm:self-auto">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-mono text-[#5B21B6] bg-white border border-purple-200/80 font-semibold shadow-sm">
            <span className="h-2 w-2 rounded-full bg-[#7C3AED] animate-pulse" />
            Ready for FastAPI /api/v1/cases persistence models
          </div>
          <button
            onClick={onNavigateHome}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-[#6D28D9] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition shadow-sm"
          >
            &larr; Back to Overview
          </button>
        </div>
      </div>

      {/* Top Controls: Status Tabs & New Case Button */}
      <div className="bg-white rounded-2xl border border-purple-200/80 p-4 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Status Tabs */}
        <div className="flex flex-wrap items-center gap-1.5">
          {(
            [
              'All Cases',
              'Open',
              'In Review',
              'Escalated / SAR Filed',
              'Closed',
            ] as CaseStatus[]
          ).map((status) => (
            <button
              key={status}
              onClick={() => setSelectedStatus(status)}
              className={`px-3 py-1.5 text-xs font-bold rounded-xl transition ${
                selectedStatus === status
                  ? 'bg-[#7C3AED] text-white shadow-sm'
                  : 'bg-purple-50/50 text-purple-900/70 hover:bg-purple-100/70 hover:text-[#1E1B4B]'
              }`}
            >
              {status}
            </button>
          ))}
        </div>

        {/* New Investigation Case Button */}
        <button
          onClick={() => {
            reset();
            setIsModalOpen(true);
          }}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-xs font-bold bg-gradient-to-r from-[#6D28D9] to-[#7C3AED] hover:from-[#5B21B6] hover:to-[#6D28D9] text-white shadow-lg shadow-purple-600/25 transition hover:scale-[1.01] active:scale-[0.99] self-start md:self-auto"
        >
          <Plus className="h-4 w-4" />
          <span>New Investigation Case</span>
        </button>
      </div>

      {/* Cases Content Area: Dossier Cards or Empty State */}
      <div className="bg-white rounded-2xl border border-purple-200/80 shadow-sm overflow-hidden relative p-6">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#5B21B6] via-[#7C3AED] to-[#9333EA]" />

        {filteredCases.length === 0 ? (
          /* Clean Empty State */
          <div className="py-16 text-center max-w-md mx-auto flex flex-col items-center">
            <div className="h-16 w-16 rounded-2xl bg-[#F4F0FF] border border-purple-200 text-[#7C3AED] flex items-center justify-center mb-4 shadow-inner">
              <FolderSearch className="h-7 w-7" />
            </div>
            <h3 className="text-base font-extrabold text-[#1E1B4B]">
              No Investigation Dossiers Created Yet
            </h3>
            <p className="text-xs text-slate-500 mt-2 leading-relaxed">
              Create a new investigation case dossier or wait for automated rule escalations from the backend.
            </p>
            <div className="mt-5 flex items-center gap-3">
              <button
                onClick={() => {
                  reset();
                  setIsModalOpen(true);
                }}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-[#7C3AED] hover:bg-[#6D28D9] text-white shadow-sm transition"
              >
                <FolderPlus className="h-4 w-4" />
                <span>Create Case Dossier</span>
              </button>
            </div>
          </div>
        ) : (
          /* Active Dossiers Grid */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredCases.map((item) => (
              <div
                key={item.id}
                className="p-5 rounded-2xl bg-purple-50/30 border border-purple-200 hover:border-[#7C3AED] hover:shadow-md transition space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-mono font-bold text-[#5B21B6] bg-white px-2 py-0.5 rounded border border-purple-200">
                    {item.id}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                      item.priority === 'Critical'
                        ? 'bg-rose-100 text-rose-700 border border-rose-200'
                        : item.priority === 'High'
                        ? 'bg-orange-100 text-orange-700 border border-orange-200'
                        : item.priority === 'Medium'
                        ? 'bg-amber-100 text-amber-700 border border-amber-200'
                        : 'bg-purple-100 text-purple-700 border border-purple-200'
                    }`}
                  >
                    {item.priority} Priority
                  </span>
                </div>

                <div>
                  <h4 className="text-sm font-extrabold text-[#1E1B4B]">
                    {item.title}
                  </h4>
                  <div className="text-xs font-mono text-purple-900/60 font-medium mt-1">
                    Subject: {item.primaryAccountId}
                  </div>
                </div>

                {item.notes && (
                  <p className="text-xs text-slate-500 line-clamp-2">
                    {item.notes}
                  </p>
                )}

                <div className="pt-2 border-t border-purple-100 flex items-center justify-between text-[11px] text-purple-900/60">
                  <span>Status: {item.status}</span>
                  <span className="font-semibold">{item.createdAt}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* "New Investigation Case" Modal / Drawer Form */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl border border-purple-300 shadow-2xl max-w-md w-full overflow-hidden animate-in fade-in-50 zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="h-16 px-6 bg-gradient-to-r from-[#28144B] to-[#5B21B6] text-white flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <FolderPlus className="h-5 w-5 text-purple-200" />
                <h3 className="text-base font-bold text-white">
                  Create Investigation Case
                </h3>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1.5 rounded-lg text-purple-200 hover:text-white hover:bg-white/10"
                aria-label="Close modal"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Modal Form */}
            <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4" noValidate>
              {/* Case Title */}
              <div className="space-y-1.5">
                <label
                  htmlFor="case-title"
                  className="block text-xs font-bold text-[#1E1B4B] uppercase tracking-wider"
                >
                  Case Title
                </label>
                <input
                  id="case-title"
                  type="text"
                  placeholder="e.g. Circular Flow Cluster 48B"
                  {...register('title')}
                  className={`w-full px-3.5 py-2 text-xs rounded-xl border ${
                    errors.title
                      ? 'border-rose-400 bg-rose-50/40 text-rose-900'
                      : 'border-purple-200/80 bg-purple-50/30 text-[#1E1B4B] focus:border-[#7C3AED]'
                  } placeholder:text-purple-900/40 focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:bg-white transition`}
                />
                {errors.title && (
                  <p role="alert" className="text-[11px] font-semibold text-rose-600">
                    {errors.title.message}
                  </p>
                )}
              </div>

              {/* Primary Account ID */}
              <div className="space-y-1.5">
                <label
                  htmlFor="primary-account-id"
                  className="block text-xs font-bold text-[#1E1B4B] uppercase tracking-wider"
                >
                  Primary Account ID
                </label>
                <input
                  id="primary-account-id"
                  type="text"
                  placeholder="e.g. ACC-8821-MULE"
                  {...register('primaryAccountId')}
                  className={`w-full px-3.5 py-2 text-xs rounded-xl border ${
                    errors.primaryAccountId
                      ? 'border-rose-400 bg-rose-50/40 text-rose-900'
                      : 'border-purple-200/80 bg-purple-50/30 text-[#1E1B4B] focus:border-[#7C3AED]'
                  } placeholder:text-purple-900/40 focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:bg-white transition`}
                />
                {errors.primaryAccountId && (
                  <p role="alert" className="text-[11px] font-semibold text-rose-600">
                    {errors.primaryAccountId.message}
                  </p>
                )}
              </div>

              {/* Priority */}
              <div className="space-y-1.5">
                <label
                  htmlFor="case-priority"
                  className="block text-xs font-bold text-[#1E1B4B] uppercase tracking-wider"
                >
                  Priority
                </label>
                <select
                  id="case-priority"
                  {...register('priority')}
                  className="w-full px-3.5 py-2 text-xs font-bold text-[#1E1B4B] rounded-xl border border-purple-200/80 bg-purple-50/30 focus:border-[#7C3AED] focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:bg-white transition cursor-pointer"
                >
                  <option value="Low">Low</option>
                  <option value="Medium">Medium</option>
                  <option value="High">High</option>
                  <option value="Critical">Critical</option>
                </select>
              </div>

              {/* Analyst Notes */}
              <div className="space-y-1.5">
                <label
                  htmlFor="analyst-notes"
                  className="block text-xs font-bold text-[#1E1B4B] uppercase tracking-wider"
                >
                  Analyst Notes
                </label>
                <textarea
                  id="analyst-notes"
                  rows={3}
                  placeholder="Describe initial anomaly observations, layering hops, or linked counterparty accounts..."
                  {...register('notes')}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-purple-200/80 bg-purple-50/30 text-[#1E1B4B] placeholder:text-purple-900/40 focus:border-[#7C3AED] focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:bg-white transition resize-none"
                />
              </div>

              {/* Actions */}
              <div className="pt-2 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 rounded-xl text-xs font-bold text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#6D28D9] to-[#7C3AED] hover:from-[#5B21B6] hover:to-[#6D28D9] shadow-md transition"
                >
                  Save Dossier
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
