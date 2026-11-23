import { useState } from 'react';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { OverviewDashboard } from './components/dashboard/OverviewDashboard';
import { TransactionsView } from './components/transactions/TransactionsView';
import { PlaceholderView } from './components/views/PlaceholderView';
import { LoginView } from './components/auth/LoginView';
import { NavTabId } from './types/navigation';

export interface AppProps {
  initialAuthenticated?: boolean;
}

export default function App({ initialAuthenticated = false }: AppProps = {}) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(initialAuthenticated);
  const [activeTab, setActiveTab] = useState<NavTabId>('overview');
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [apiStatus, setApiStatus] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const handleAuthenticated = () => {
    setIsAuthenticated(true);
  };

  const handleSignOut = () => {
    setIsAuthenticated(false);
    setActiveTab('overview');
  };

  const handleCheckHealth = async () => {
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
      setApiStatus(`Unable to connect (FastAPI not detected on ${baseUrl})`);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isAuthenticated) {
    return <LoginView onAuthenticated={handleAuthenticated} />;
  }

  return (
    <div className="min-h-screen bg-[#F4F0FF] text-[#1E1B4B] flex flex-col antialiased">
      {/* Sidebar Navigation */}
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onSignOut={handleSignOut}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 lg:pl-72 transition-all">
        {/* Frosted Top Header */}
        <Header
          activeTab={activeTab}
          onOpenSidebar={() => setIsSidebarOpen(true)}
          onSignOut={handleSignOut}
        />

        {/* Dynamic Page Views */}
        <main className="flex-1 p-4 md:p-8 max-w-7xl w-full mx-auto">
          {activeTab === 'overview' ? (
            <OverviewDashboard
              apiStatus={apiStatus}
              isLoading={isLoading}
              onCheckHealth={handleCheckHealth}
              onNavigateToTab={(tab) => setActiveTab(tab)}
            />
          ) : activeTab === 'transactions' ? (
            <TransactionsView
              onNavigateHome={() => setActiveTab('overview')}
            />
          ) : (
            <PlaceholderView
              tab={activeTab}
              onNavigateHome={() => setActiveTab('overview')}
            />
          )}
        </main>
      </div>
    </div>
  );
}
