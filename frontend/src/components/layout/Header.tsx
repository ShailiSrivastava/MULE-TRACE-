import React from 'react';
import {
  Menu,
  Search,
  Bell,
  Settings,
  ShieldCheck,
  LogOut,
} from 'lucide-react';
import { NavTabId } from '../../types/navigation';

interface HeaderProps {
  activeTab: NavTabId;
  onOpenSidebar: () => void;
  onSignOut?: () => void;
  userName?: string;
  userRole?: string;
}

const TAB_TITLES: Record<NavTabId, string> = {
  overview: 'Overview Dashboard',
  transactions: 'Transactions',
  graph: 'Network Graph',
  alerts: 'Suspicious Alerts',
  cases: 'Investigation Cases',
  risk: 'Risk Analysis',
  reports: 'Reports & Export',
};

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  onOpenSidebar,
  onSignOut,
  userName = 'Authenticated user',
  userRole = 'ANALYST',
}) => {
  const currentTitle = TAB_TITLES[activeTab] || 'Overview Dashboard';

  return (
    <header className="sticky top-0 z-30 h-16 bg-white/85 backdrop-blur-md border-b border-purple-200/70 px-4 md:px-8 flex items-center justify-between">
      {/* Left: Mobile Toggle & Breadcrumbs */}
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenSidebar}
          className="lg:hidden p-2 rounded-lg text-slate-600 hover:bg-purple-50 hover:text-[#1E1B4B]"
          aria-label="Open navigation menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        <div>
          <div className="flex items-center gap-1.5 text-xs text-purple-900/60 font-medium">
            <span>MuleTrace</span>
            <span>/</span>
            <span className="text-[#7C3AED] font-semibold">{currentTitle}</span>
          </div>
          <h2 className="text-base font-extrabold text-[#1E1B4B] tracking-tight hidden sm:block">
            {currentTitle}
          </h2>
        </div>
      </div>

      {/* Center: Search */}
      <div className="hidden md:flex items-center flex-1 max-w-md mx-6">
        <div className="relative w-full">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-purple-900/40" />
          <input
            type="text"
            placeholder="Search account, transaction hash, case ID..."
            className="w-full pl-9 pr-4 py-1.5 text-xs rounded-xl bg-purple-50/50 border border-purple-200/80 text-[#1E1B4B] placeholder:text-purple-900/40 focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30 focus:border-[#7C3AED] focus:bg-white transition-all"
          />
        </div>
      </div>

      {/* Right: Controls, Avatar & Sign Out */}
      <div className="flex items-center gap-3">
        {/* Notifications */}
        <button
          className="relative p-2 rounded-xl text-slate-500 hover:text-[#1E1B4B] hover:bg-purple-50 transition"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-[#7C3AED]" />
        </button>

        {/* Settings */}
        <button
          className="p-2 rounded-xl text-slate-500 hover:text-[#1E1B4B] hover:bg-purple-50 transition hidden sm:flex"
          aria-label="Settings"
        >
          <Settings className="h-4 w-4" />
        </button>

        {/* User Avatar */}
        <div className="flex items-center gap-2 pl-2 border-l border-purple-200/70">
          <div className="h-8 w-8 rounded-full bg-gradient-to-tr from-[#6D28D9] to-[#9333EA] text-white flex items-center justify-center font-bold text-xs shadow-md shadow-purple-600/30 ring-1 ring-purple-300">
                {userName.slice(0, 2).toUpperCase()}
          </div>
          <div className="hidden xl:block text-left">
            <div className="text-xs font-bold text-[#1E1B4B] leading-none">
              {userName}
            </div>
            <div className="text-[10px] text-purple-900/60 font-medium leading-none mt-1 flex items-center gap-1">
              <ShieldCheck className="h-3 w-3 text-[#7C3AED]" />
              {userRole}
            </div>
          </div>
        </div>

        {/* Sign Out Action Button */}
        {onSignOut && (
          <button
            onClick={onSignOut}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-purple-900/80 hover:text-rose-600 hover:bg-rose-50 border border-purple-200/80 hover:border-rose-200 transition shadow-sm"
            title="Sign out of investigator session"
          >
            <LogOut className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Sign Out</span>
          </button>
        )}
      </div>
    </header>
  );
};
