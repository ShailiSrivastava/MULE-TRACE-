import React from 'react';
import {
  LayoutDashboard,
  ArrowLeftRight,
  Network,
  AlertTriangle,
  FolderSearch,
  ShieldAlert,
  FileSpreadsheet,
  X,
  Users,
} from 'lucide-react';
import { NavTabId } from '../../types/navigation';

interface SidebarProps {
  activeTab: NavTabId;
  onTabChange: (tab: NavTabId) => void;
  isOpen: boolean;
  onClose: () => void;
}

interface NavItemDef {
  id: NavTabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
}

const NAV_ITEMS: NavItemDef[] = [
  { id: 'overview', label: 'Overview Dashboard', icon: LayoutDashboard },
  { id: 'transactions', label: 'Transactions', icon: ArrowLeftRight },
  { id: 'graph', label: 'Network Graph', icon: Network },
  { id: 'alerts', label: 'Suspicious Alerts', icon: AlertTriangle, badge: 'Live' },
  { id: 'cases', label: 'Investigation Cases', icon: FolderSearch },
  { id: 'risk', label: 'Risk Analysis', icon: ShieldAlert },
  { id: 'reports', label: 'Reports & Export', icon: FileSpreadsheet },
];

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onTabChange,
  isOpen,
  onClose,
}) => {
  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-slate-950/60 backdrop-blur-sm z-40 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar Container: Rich Royal Plum-to-Indigo Vertical Gradient */}
      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 w-72 bg-gradient-to-b from-[#1E1035] via-[#28144B] to-[#1A0D30] border-r border-purple-900/40 text-white flex flex-col transition-transform duration-200 ease-in-out shadow-2xl lg:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand Header with Emblem */}
        <div className="h-16 px-6 border-b border-purple-900/40 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-[#7C3AED] via-[#9333EA] to-[#C084FC] flex items-center justify-center text-white shadow-lg shadow-purple-600/40 ring-1 ring-purple-300/30">
              <Network className="h-5 w-5" />
            </div>
            <div>
              <span className="text-lg font-black tracking-tight text-white block leading-tight">
                MuleTrace
              </span>
              <span className="block text-[10px] font-bold uppercase tracking-wider text-purple-300">
                Financial Intelligence
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="lg:hidden p-1.5 rounded-lg text-purple-300 hover:text-white hover:bg-white/10"
            aria-label="Close sidebar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Navigation Items */}
        <div className="flex-1 py-6 px-3.5 overflow-y-auto space-y-1.5">
          <div className="px-3 pb-2 text-[11px] font-bold uppercase tracking-wider text-purple-300/60">
            Intelligence Modules
          </div>

          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  onTabChange(item.id);
                  onClose();
                }}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all ${
                  isActive
                    ? 'bg-gradient-to-r from-[#7C3AED] to-[#9333EA] text-white font-semibold shadow-lg shadow-purple-600/30 border border-purple-400/30'
                    : 'text-purple-200/80 hover:bg-white/10 hover:text-white'
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon
                    className={`h-4 w-4 ${
                      isActive ? 'text-white' : 'text-purple-300/70'
                    }`}
                  />
                  <span>{item.label}</span>
                </div>
                {item.badge ? (
                  <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-purple-500/30 text-purple-200 border border-purple-400/30 shadow-sm">
                    {item.badge}
                  </span>
                ) : isActive ? (
                  <span className="h-2 w-2 rounded-full bg-white shadow-[0_0_8px_#FFFFFF]" />
                ) : null}
              </button>
            );
          })}
        </div>

        {/* Footer / Team Collaboration Indicator */}
        <div className="p-4 border-t border-purple-900/40 bg-black/20">
          <div className="flex items-center gap-2.5 p-2.5 rounded-xl bg-white/5 border border-purple-500/20 backdrop-blur-sm">
            <div className="h-8 w-8 rounded-lg bg-purple-600/30 border border-purple-400/30 flex items-center justify-center text-purple-200 shadow-sm">
              <Users className="h-4 w-4" />
            </div>
            <div className="overflow-hidden">
              <div className="text-xs font-bold text-white truncate">
                Shaili &amp; Raj
              </div>
              <div className="text-[10px] text-purple-300/70 truncate">
                Financial Crime Squad
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
};
