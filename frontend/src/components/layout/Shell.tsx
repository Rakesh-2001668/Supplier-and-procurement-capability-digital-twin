'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { 
  Building2, LineChart, ShieldAlert, Globe, Factory,
  FileText, CreditCard, Box, Settings, Users, Truck,
  Menu, Bell, Search, LayoutDashboard, AlertTriangle,
  RefreshCw, CheckCheck, Sparkles, ArrowRight, Clock,
  ArrowLeftRight, Code, Activity, Navigation, Leaf, ShieldCheck, Shield, Bot, TrendingUp, ShoppingCart,
  Target, DollarSign, Scale, Layers, BarChart3, Sliders, Workflow, Receipt
} from 'lucide-react';
import axios from 'axios';
import IndustrySwitcher from '@/components/layout/IndustrySwitcher';

const buyerNavigation = [
  { name: 'Command Centre', href: '/command-centre', icon: Activity },
  { name: 'Unified Approvals & SoD', href: '/approvals', icon: ShieldCheck },
  { name: 'BPMN Swimlane Flows', href: '/bpmn-flows', icon: Workflow },
  { name: 'Specialist Workbenches', href: '/workbenches', icon: Sliders },
  { name: 'Industry Templates', href: '/industry-templates', icon: Building2 },
  { name: 'Buyer Dashboard', href: '/buyer/dashboard', icon: LayoutDashboard },
  { name: 'Spend Cube', href: '/spend/cube', icon: BarChart3 },
  { name: 'Strategic Sourcing', href: '/sourcing', icon: Target },
  { name: 'Buy-Side Agreements', href: '/contracts/agreements', icon: Scale },
  { name: 'Savings Realisation', href: '/savings', icon: DollarSign },
  { name: 'P2P Cockpit', href: '/p2p', icon: ShoppingCart },
  { name: 'MRP Workbench', href: '/mrp/planner-workbench', icon: Layers },
  { name: 'MDM Governance', href: '/mdm/requests', icon: ShieldCheck },
  { name: 'MDM Duplicate Shield', href: '/mdm/studio', icon: ShieldCheck },
  { name: 'AI Agents Fleet', href: '/command-centre/ai-agents', icon: Bot },
  { name: 'AI Copilot', href: '/copilot', icon: Bot },
  { name: 'Supplier Network', href: '/network', icon: Globe },
  { name: 'Discovery', href: '/buyer/discovery', icon: Search },
  { name: 'Generative DFSC', href: '/dfsc', icon: Sparkles },
  { name: 'Monte Carlo Sim', href: '/simulation', icon: LineChart },
  { name: 'Evidence Vault', href: '/evidence', icon: ShieldCheck },
  { name: 'Development & CAPA', href: '/development', icon: TrendingUp },
  { name: 'Smart Contracts', href: '/contracts', icon: Code },
  { name: 'Risk Command', href: '/risk', icon: ShieldAlert },
  { name: 'RFQs & Orders', href: '/rfqs', icon: FileText },
  { name: 'Invoices', href: '/invoices', icon: FileText },
  { name: '3-Way Match & Disputes', href: '/invoices/3-way-match', icon: Receipt },
  { name: 'Payments', href: '/finance/payments', icon: CreditCard },
  { name: 'Inventory', href: '/inventory', icon: Box },
  { name: 'Admin & RBAC', href: '/admin', icon: Shield },
  { name: 'Governance & SoD', href: '/admin/governance', icon: ShieldAlert },
  { name: 'Notifications', href: '/notifications', icon: Bell },
];

const supplierNavigation = [
  { name: 'Supplier Dashboard', href: '/supplier/dashboard', icon: LayoutDashboard },
  { name: 'P2P Orders & Invoices', href: '/p2p', icon: ShoppingCart },
  { name: 'AI Copilot', href: '/copilot', icon: Bot },
  { name: 'My Digital Twin', href: '/supplier/profile', icon: Factory },
  { name: 'Machine Telemetry', href: '/supplier/telemetry', icon: Activity },
  { name: 'Development & CAPA', href: '/development', icon: TrendingUp },
  { name: 'Transit Monitor', href: '/supplier/transit', icon: Navigation },
  { name: 'ESG Compliance', href: '/supplier/esg-reporting', icon: Leaf },
  { name: 'Incoming RFQs', href: '/supplier/rfqs', icon: FileText },
  { name: 'Active Orders', href: '/supplier/orders', icon: Truck },
  { name: 'Invoices Sent', href: '/supplier/invoices', icon: FileText },
  { name: 'Smart Contracts', href: '/supplier/smart-contracts', icon: Code },
  { name: 'Payments Received', href: '/supplier/payments', icon: CreditCard },
  { name: 'Inventory', href: '/supplier/inventory', icon: Box },
  { name: 'Notifications', href: '/notifications', icon: Bell },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [isSupplierUser, setIsSupplierUser] = useState(false);

  // Live Notifications State
  const [notifications, setNotifications] = useState<any[]>([]);
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [companyName, setCompanyName] = useState<string>('AlphaHelion Global');
  const [tenantId, setTenantId] = useState<string>('buyer-mock');

  // Sync role with localStorage for shared routes like /inventory
  useEffect(() => {
    const savedRole = localStorage.getItem('app_role');
    const storedTenant = localStorage.getItem('tenant_id') || 'buyer-mock';
    setTenantId(storedTenant);

    if (pathname?.startsWith('/supplier')) {
      localStorage.setItem('app_role', 'supplier');
      localStorage.setItem('tenant_id', 'supplier-mock');
      setIsSupplierUser(true);
    } else if (pathname?.startsWith('/buyer')) {
      localStorage.setItem('app_role', 'buyer');
      localStorage.setItem('tenant_id', 'buyer-mock');
      setIsSupplierUser(false);
    } else if (savedRole === 'supplier' || storedTenant === 'supplier-mock') {
      setIsSupplierUser(true);
    } else {
      setIsSupplierUser(false);
    }
  }, [pathname]);

  const isSupplier = pathname?.startsWith('/supplier') || isSupplierUser;

  // Switch Persona Handler
  const handleSwitchPersona = (target: 'buyer' | 'supplier') => {
    if (target === 'buyer') {
      localStorage.setItem('tenant_id', 'buyer-mock');
      localStorage.setItem('app_role', 'buyer');
      setIsSupplierUser(false);
      window.location.href = '/buyer/dashboard';
    } else {
      localStorage.setItem('tenant_id', 'supplier-mock');
      localStorage.setItem('app_role', 'supplier');
      setIsSupplierUser(true);
      window.location.href = '/supplier/dashboard';
    }
  };

  // Live Sync Poller for Header Notifications (every 5 seconds)
  useEffect(() => {
    if (pathname?.startsWith('/pic')) return; // the PIC workspace has its own shell and live stream
    const fetchLiveNotifications = async () => {
      try {
        const storedTenant = typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || (isSupplier ? 'supplier-mock' : 'buyer-mock') : 'buyer-mock';
        const res = await axios.get(`http://localhost:8080/api/v1/notifications?tenant_id=${storedTenant}`);
        if (res.data && res.data.status === 'success') {
          setNotifications(res.data.notifications || []);
          setUnreadCount(res.data.unread_count || 0);
          setCompanyName(res.data.company_name || (isSupplier ? 'Apex Precision Tooling' : 'AlphaHelion Global'));
        }
      } catch (err) {
        // Fallback silently if offline
      }
    };

    fetchLiveNotifications();
    const interval = setInterval(fetchLiveNotifications, 5000);
    return () => clearInterval(interval);
  }, [isSupplier, tenantId, pathname]);

  // Mark all notifications as read
  const handleMarkAllRead = async () => {
    try {
      const storedTenant = typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || (isSupplier ? 'supplier-mock' : 'buyer-mock') : 'buyer-mock';
      await axios.post(`http://localhost:8080/api/v1/notifications/mark-all-read?tenant_id=${storedTenant}`);
      setNotifications(prev => prev.map(n => ({ ...n, read: true })));
      setUnreadCount(0);
    } catch (err) {
      console.error('Error marking all as read:', err);
    }
  };

  // Click on a notification item: mark as read and navigate
  const handleNotificationClick = async (notif: any) => {
    try {
      if (!notif.read) {
        await axios.post(`http://localhost:8080/api/v1/notifications/${notif.id}/read`);
        setNotifications(prev => prev.map(n => n.id === notif.id ? { ...n, read: true } : n));
        setUnreadCount(prev => Math.max(0, prev - 1));
      }
    } catch (err) {
      console.error('Error marking read:', err);
    }
    setNotifOpen(false);
    if (notif.action_url) {
      router.push(notif.action_url);
    }
  };

  // Helper for category icon
  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'DISPATCH':
      case 'ORDER':
        return <Truck size={14} className="text-amber-500 shrink-0" />;
      case 'RFQ':
        return <FileText size={14} className="text-blue-500 shrink-0" />;
      case 'INVOICE':
      case 'PAYMENT':
        return <CreditCard size={14} className="text-emerald-500 shrink-0" />;
      case 'INVENTORY':
        return <Box size={14} className="text-purple-500 shrink-0" />;
      case 'RISK':
        return <AlertTriangle size={14} className="text-rose-500 shrink-0" />;
      case 'TWIN':
        return <Factory size={14} className="text-indigo-500 shrink-0" />;
      default:
        return <Bell size={14} className="text-slate-400 shrink-0" />;
    }
  };

  // Helper for relative time
  const formatTimeAgo = (isoString: string) => {
    try {
      const diff = Math.floor((new Date().getTime() - new Date(isoString).getTime()) / 1000);
      if (diff < 60) return 'Just now';
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    } catch {
      return 'Recently';
    }
  };

  // Determine which navigation to use based on URL route.
  // The PIC workspace (/pic) renders its own shell.
  const isAuthPage = pathname === '/login' || pathname === '/register' || pathname === '/' || !!pathname?.startsWith('/pic');
  const navigation = isSupplier ? supplierNavigation : buyerNavigation;

  if (isAuthPage) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col md:flex-row">
      {/* Mobile Header */}
      <div className="md:hidden bg-[#0B2550] text-white p-3 px-4 flex justify-between items-center z-20 border-b border-blue-800/60 shadow-sm">
        <div className="flex items-center gap-2.5">
          <div className="bg-white rounded-xl py-1 px-3 shadow-sm inline-flex items-center">
            <img
              src="/alphahelion-logo.png"
              alt="AlphaHelion Global"
              className="h-8 w-auto object-contain"
            />
          </div>
          <span className="font-bold text-xs uppercase tracking-wider text-blue-200">
            {isSupplier ? 'Supplier' : 'Buyer'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Mobile Persona Switcher Button */}
          <button
            onClick={() => handleSwitchPersona(isSupplier ? 'buyer' : 'supplier')}
            className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold rounded-lg bg-blue-800/80 hover:bg-blue-700 text-blue-100 border border-blue-600/60 transition-all shadow-xs"
            title={isSupplier ? 'Switch to Buyer Portal' : 'Switch to Supplier Portal'}
          >
            <ArrowLeftRight size={12} className="text-blue-300" />
            <span>{isSupplier ? 'To Buyer' : 'To Supplier'}</span>
          </button>

          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-1 text-blue-200 hover:text-white">
            <Menu size={22} />
          </button>
        </div>
      </div>

      {/* Sidebar Navigation */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-64 bg-[#0B2550] text-white transform transition-transform duration-200 ease-in-out md:translate-x-0 md:static md:inset-0 flex flex-col ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-0 hidden md:flex'
        }`}
      >
        {/* AlphaHelion Global Logo & Portal Info */}
        <div className="p-4 border-b border-blue-900/60">
          <Link
            href={isSupplier ? "/supplier/dashboard" : "/buyer/dashboard"}
            className="block bg-white rounded-xl p-2.5 shadow-sm mb-3 text-center hover:opacity-95 transition-opacity"
          >
            <img
              src="/alphahelion-logo.png"
              alt="AlphaHelion Global"
              className="h-10 w-auto object-contain mx-auto"
            />
          </Link>
          <div className="flex items-center justify-between text-xs text-blue-200/90 px-1 font-semibold">
            <span>{isSupplier ? 'Supplier Portal' : 'Buyer Portal'}</span>
            <span className={`text-[10px] font-black px-2 py-0.5 rounded-full uppercase tracking-wider ${
              isSupplier ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-blue-500/20 text-blue-200 border border-blue-400/30'
            }`}>
              {isSupplier ? 'Apex Tooling' : 'AlphaHelion'}
            </span>
          </div>
        </div>

        {/* Navigation Items */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {navigation.map((item) => {
            const isActive = pathname === item.href;
            const Icon = item.icon;
            const isNotifItem = item.name === 'Notifications';
            return (
              <Link
                key={item.name}
                href={item.href}
                className={`flex items-center justify-between px-3 py-2.5 text-sm font-medium rounded-xl transition-all ${
                  isActive
                    ? 'bg-blue-600 text-white font-semibold shadow-sm'
                    : 'text-blue-100 hover:bg-blue-900/50 hover:text-white'
                }`}
                onClick={() => setSidebarOpen(false)}
              >
                <div className="flex items-center">
                  <Icon size={18} className="mr-3 text-blue-300" />
                  {item.name}
                </div>
                {isNotifItem && unreadCount > 0 && (
                  <span className="px-2 py-0.5 text-[10px] font-black rounded-full bg-rose-500 text-white animate-pulse">
                    {unreadCount}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {/* Sidebar Bottom Persona Quick Switcher */}
        <div className="p-4 border-t border-blue-900/60 bg-blue-950/50 space-y-2">
          <p className="text-[10px] font-bold text-blue-300 uppercase tracking-wider px-1">
            Active Persona Switcher
          </p>
          <div className="grid grid-cols-2 gap-1.5 bg-blue-900/60 p-1 rounded-xl border border-blue-800/80">
            <button
              onClick={() => handleSwitchPersona('buyer')}
              className={`py-1.5 px-2 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1 ${
                !isSupplier
                  ? 'bg-white text-[#0B2550] shadow-sm font-extrabold'
                  : 'text-blue-200 hover:text-white hover:bg-blue-800/50'
              }`}
            >
              <span>🏢 Buyer</span>
            </button>
            <button
              onClick={() => handleSwitchPersona('supplier')}
              className={`py-1.5 px-2 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1 ${
                isSupplier
                  ? 'bg-amber-500 text-slate-900 shadow-sm font-extrabold'
                  : 'text-blue-200 hover:text-white hover:bg-blue-800/50'
              }`}
            >
              <span>🏭 Supplier</span>
            </button>
          </div>
          <button
            onClick={() => handleSwitchPersona(isSupplier ? 'buyer' : 'supplier')}
            className="flex items-center justify-center gap-1.5 w-full py-2 px-3 bg-blue-800/60 hover:bg-blue-700/80 text-blue-100 text-xs font-bold rounded-xl border border-blue-600/50 transition-all text-center shadow-xs"
          >
            <ArrowLeftRight size={13} className="text-blue-300" />
            <span>Switch to {isSupplier ? "Buyer Portal" : "Supplier Portal"}</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Desktop Top Header Bar */}
        <header className="bg-white border-b border-gray-200 h-16 flex items-center justify-between px-6 z-10 sticky top-0 shadow-xs">
          {/* Breadcrumb & Section Title */}
          <div className="flex items-center space-x-4">
            <h2 className="text-lg font-bold text-gray-800 capitalize tracking-tight flex items-center gap-2">
              {pathname?.split('/')[1] || 'Dashboard'}
              <span className="text-xs font-semibold text-gray-400 font-normal">
                / {companyName}
              </span>
            </h2>
          </div>

          {/* Right Header Actions: Industry Switcher, Persona Switcher, Notifications, Profile */}
          <div className="flex items-center space-x-3">
            {/* === TOP-LEVEL INDUSTRY PACK SWITCHER (Blueprint Section 23) === */}
            <IndustrySwitcher />

            {/* === PROMINENT DEMO PERSONA SWITCHER (Always Visible in Header) === */}
            <div className="flex items-center bg-slate-100/90 rounded-xl p-1 border border-slate-200/90 shadow-inner">
              <button
                onClick={() => handleSwitchPersona('buyer')}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                  !isSupplier
                    ? 'bg-white text-[#0B2550] shadow-sm ring-1 ring-slate-200/60 font-extrabold'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-white/60'
                }`}
                title="Switch to Buyer Portal (AlphaHelion Global)"
              >
                <span>🏢</span>
                <span>Buyer Portal</span>
                {!isSupplier && (
                  <span className="h-1.5 w-1.5 rounded-full bg-blue-600"></span>
                )}
              </button>

              <button
                onClick={() => handleSwitchPersona('supplier')}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                  isSupplier
                    ? 'bg-[#0B2550] text-white shadow-sm ring-1 ring-blue-900 font-extrabold'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-white/60'
                }`}
                title="Switch to Supplier Portal (Apex Precision Tooling)"
              >
                <span>🏭</span>
                <span>Supplier Portal</span>
                {isSupplier && (
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400"></span>
                )}
              </button>
            </div>

            {/* Live Notifications Bell & Rich Dropdown */}
            <div className="relative">
              <button
                onClick={() => { setNotifOpen(!notifOpen); setProfileOpen(false); }}
                className="text-gray-500 hover:text-[#0B2550] relative p-2 rounded-xl hover:bg-slate-100 transition-all border border-transparent hover:border-slate-200"
                title="Live Notification Center"
              >
                <Bell size={20} />
                {unreadCount > 0 ? (
                  <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-rose-600 text-white font-black text-[10px] flex items-center justify-center shadow-md animate-pulse">
                    {unreadCount > 9 ? '9+' : unreadCount}
                  </span>
                ) : (
                  <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-emerald-500"></span>
                )}
              </button>

              {/* Notification Dropdown Panel */}
              {notifOpen && (
                <div className="absolute right-0 mt-2 w-96 bg-white rounded-2xl shadow-2xl py-2 border border-slate-200 z-50 animate-in fade-in slide-in-from-top-2 duration-150">
                  {/* Dropdown Header */}
                  <div className="px-4 py-2.5 border-b border-slate-100 flex justify-between items-center">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-extrabold text-[#0B2550] text-sm">Notifications</span>
                        <span className="px-1.5 py-0.5 text-[9px] font-black rounded-md bg-emerald-100 text-emerald-800 flex items-center gap-1">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                          LIVE
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 truncate max-w-[200px]">
                        {companyName}
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      {unreadCount > 0 && (
                        <button
                          onClick={handleMarkAllRead}
                          className="text-xs font-bold text-blue-600 hover:text-blue-800 hover:underline"
                        >
                          Mark all read
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Notification Items List */}
                  <div className="max-h-80 overflow-y-auto divide-y divide-slate-100">
                    {notifications.length === 0 ? (
                      <div className="p-6 text-center text-slate-400">
                        <p className="text-xs font-semibold">No notifications right now.</p>
                      </div>
                    ) : (
                      notifications.slice(0, 6).map((item) => (
                        <div
                          key={item.id}
                          onClick={() => handleNotificationClick(item)}
                          className={`px-4 py-3 hover:bg-slate-50 cursor-pointer transition-all flex items-start gap-3 ${
                            !item.read ? 'bg-blue-50/40 border-l-3 border-l-blue-600' : ''
                          }`}
                        >
                          <div className="p-2 rounded-xl bg-slate-100 border border-slate-200 mt-0.5">
                            {getCategoryIcon(item.category)}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-1 mb-0.5">
                              <p className={`text-xs truncate ${!item.read ? 'font-bold text-slate-900' : 'font-semibold text-slate-700'}`}>
                                {item.title}
                              </p>
                              <span className="text-[10px] text-slate-400 shrink-0">
                                {formatTimeAgo(item.created_at)}
                              </span>
                            </div>
                            <p className="text-[11px] text-slate-500 line-clamp-2 leading-relaxed">
                              {item.message}
                            </p>
                            <div className="flex items-center justify-between pt-1">
                              <span className="text-[10px] text-blue-600 font-semibold truncate">
                                {item.partner_company}
                              </span>
                              <span className="text-[10px] text-[#0B2550] font-bold flex items-center gap-0.5 hover:underline">
                                {item.action_label} &rarr;
                              </span>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>

                  {/* Dropdown Footer */}
                  <div className="p-2 border-t border-slate-100 bg-slate-50/80 rounded-b-2xl flex items-center justify-between">
                    <Link
                      href="/notifications"
                      onClick={() => setNotifOpen(false)}
                      className="w-full text-center text-xs text-blue-700 hover:text-blue-900 font-bold py-1.5 rounded-xl hover:bg-blue-50 transition-all flex items-center justify-center gap-1.5"
                    >
                      <span>Open Full Notification Center</span>
                      <ArrowRight size={13} />
                    </Link>
                  </div>
                </div>
              )}
            </div>

            {/* Profile Dropdown */}
            <div className="relative">
              <button
                onClick={() => { setProfileOpen(!profileOpen); setNotifOpen(false); }}
                className="h-9 w-9 rounded-full bg-blue-100 text-[#0B2550] flex items-center justify-center font-bold text-sm border border-blue-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#0B2550] shadow-xs"
              >
                {isSupplier ? 'S' : 'B'}
              </button>

              {profileOpen && (
                <div className="absolute right-0 mt-2 w-60 bg-white rounded-2xl shadow-xl py-2 border border-gray-200 z-50">
                  <div className="px-4 py-2.5 border-b border-gray-100">
                    <p className="text-sm font-bold text-gray-900">{isSupplier ? 'Apex Tooling Inc.' : 'AlphaHelion Global'}</p>
                    <p className="text-xs text-gray-500 truncate">{isSupplier ? 'supplier@apex.com' : 'buyer@alphahelion.com'}</p>
                  </div>

                  <div className="p-2 border-b border-gray-100 bg-slate-50/60">
                    <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider px-2 mb-1">Switch Persona</p>
                    <button
                      onClick={() => { handleSwitchPersona('buyer'); setProfileOpen(false); }}
                      className={`w-full text-left px-3 py-1.5 text-xs font-semibold rounded-lg flex items-center justify-between ${
                        !isSupplier ? 'bg-blue-100 text-blue-900 font-bold' : 'text-gray-700 hover:bg-gray-100'
                      }`}
                    >
                      <span>🏢 Buyer Portal (AlphaHelion)</span>
                      {!isSupplier && <span className="text-[10px] text-blue-700 font-black">ACTIVE</span>}
                    </button>
                    <button
                      onClick={() => { handleSwitchPersona('supplier'); setProfileOpen(false); }}
                      className={`w-full text-left px-3 py-1.5 text-xs font-semibold rounded-lg flex items-center justify-between mt-1 ${
                        isSupplier ? 'bg-amber-100 text-amber-900 font-bold' : 'text-gray-700 hover:bg-gray-100'
                      }`}
                    >
                      <span>🏭 Supplier Portal (Apex)</span>
                      {isSupplier && <span className="text-[10px] text-amber-700 font-black">ACTIVE</span>}
                    </button>
                  </div>

                  <Link href={isSupplier ? "/supplier/profile" : "/network"} className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100">
                    {isSupplier ? "Company Profile" : "Organization Settings"}
                  </Link>
                  <Link href="/notifications" className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 flex items-center justify-between">
                    <span>Notification Center</span>
                    {unreadCount > 0 && (
                      <span className="px-1.5 py-0.2 rounded-full bg-rose-500 text-white text-[10px] font-bold">
                        {unreadCount}
                      </span>
                    )}
                  </Link>
                  <div className="border-t border-gray-100"></div>
                  <Link href="/login" className="block px-4 py-2 text-sm text-red-600 hover:bg-gray-100 font-medium">
                    Sign out
                  </Link>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
