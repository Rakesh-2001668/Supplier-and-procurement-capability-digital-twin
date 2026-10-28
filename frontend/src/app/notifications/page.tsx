'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Bell, CheckCircle2, Clock, Filter, Search, ArrowRight,
  AlertTriangle, Truck, FileText, CreditCard, Box, Factory,
  ShieldAlert, RefreshCw, CheckCheck, Trash2, Radio,
  Building2, Sparkles, ExternalLink, ShieldCheck, ChevronRight
} from 'lucide-react';
import axios from 'axios';

interface NotificationItem {
  id: string;
  tenant_id: string;
  company_name: string;
  partner_company: string;
  title: string;
  message: string;
  category: string;
  priority: string;
  action_url: string;
  action_label: string;
  read: boolean;
  created_at: string;
  metadata?: any;
}

export default function NotificationCenterPage() {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [companyName, setCompanyName] = useState<string>('AlphaHelion Global');
  const [tenantId, setTenantId] = useState<string>('buyer-mock');
  const [isSupplier, setIsSupplier] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [priorityFilter, setPriorityFilter] = useState<string>('ALL');
  const [lastSynced, setLastSynced] = useState<Date>(new Date());
  const [syncing, setSyncing] = useState<boolean>(false);
  const [simulating, setSimulating] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Read persona/tenant from localStorage
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storedTenant = localStorage.getItem('tenant_id') || 'buyer-mock';
      const isSup = storedTenant === 'supplier-mock';
      setTenantId(storedTenant);
      setIsSupplier(isSup);
    }
  }, []);

  // Fetch notifications from backend
  const fetchNotifications = async (showSyncIndicator = false) => {
    if (showSyncIndicator) setSyncing(true);
    try {
      const storedTenant = typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || 'buyer-mock' : 'buyer-mock';
      const res = await axios.get(`http://localhost:8080/api/v1/notifications?tenant_id=${storedTenant}`);
      if (res.data && res.data.status === 'success') {
        setNotifications(res.data.notifications || []);
        setCompanyName(res.data.company_name || 'AlphaHelion Global');
        setLastSynced(new Date());
      }
    } catch (err) {
      console.error('Failed to fetch notifications:', err);
    } finally {
      setLoading(false);
      if (showSyncIndicator) {
        setTimeout(() => setSyncing(false), 400);
      }
    }
  };

  // Initial load and Live Sync Interval (every 5 seconds)
  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(() => {
      fetchNotifications(false);
    }, 5000);
    return () => clearInterval(interval);
  }, [tenantId]);

  // Mark single as read
  const handleMarkRead = async (id: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
      await axios.post(`http://localhost:8080/api/v1/notifications/${id}/read`);
    } catch (err) {
      console.error('Error marking as read:', err);
    }
  };

  // Mark single as unread
  const handleMarkUnread = async (id: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: false } : n));
      await axios.post(`http://localhost:8080/api/v1/notifications/${id}/unread`);
    } catch (err) {
      console.error('Error marking as unread:', err);
    }
  };

  // Mark all as read
  const handleMarkAllRead = async () => {
    try {
      setNotifications(prev => prev.map(n => ({ ...n, read: true })));
      await axios.post(`http://localhost:8080/api/v1/notifications/mark-all-read?tenant_id=${tenantId}`);
      showToast('All notifications marked as read');
    } catch (err) {
      console.error('Error marking all as read:', err);
    }
  };

  // Delete single notification
  const handleDelete = async (id: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      setNotifications(prev => prev.filter(n => n.id !== id));
      await axios.delete(`http://localhost:8080/api/v1/notifications/${id}`);
      showToast('Notification dismissed');
    } catch (err) {
      console.error('Error deleting notification:', err);
    }
  };

  // Clear all
  const handleClearAll = async () => {
    if (confirm('Are you sure you want to clear all notifications?')) {
      try {
        setNotifications([]);
        await axios.post(`http://localhost:8080/api/v1/notifications/clear?tenant_id=${tenantId}`);
        showToast('All notifications cleared');
      } catch (err) {
        console.error('Error clearing notifications:', err);
      }
    }
  };

  // Simulate live workflow event
  const handleSimulateEvent = async (eventType: string) => {
    setSimulating(true);
    try {
      const res = await axios.post(`http://localhost:8080/api/v1/notifications/simulate?tenant_id=${tenantId}&event_type=${eventType}`);
      if (res.data && res.data.notification) {
        setNotifications(prev => [res.data.notification, ...prev]);
        showToast(`⚡ Live event simulated: ${res.data.notification.title}`);
      }
    } catch (err) {
      console.error('Error simulating event:', err);
    } finally {
      setSimulating(false);
    }
  };

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  // Format relative time
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

  // Filtering
  const filteredNotifications = notifications.filter(n => {
    if (activeTab === 'UNREAD' && n.read) return false;
    if (activeTab === 'DISPATCH' && n.category !== 'DISPATCH' && n.category !== 'ORDER') return false;
    if (activeTab === 'RFQ' && n.category !== 'RFQ') return false;
    if (activeTab === 'FINANCE' && n.category !== 'INVOICE' && n.category !== 'PAYMENT') return false;
    if (activeTab === 'INVENTORY' && n.category !== 'INVENTORY' && n.category !== 'RISK' && n.category !== 'TWIN') return false;

    if (priorityFilter !== 'ALL' && n.priority !== priorityFilter) return false;

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchTitle = n.title.toLowerCase().includes(q);
      const matchMsg = n.message.toLowerCase().includes(q);
      const matchCompany = n.partner_company.toLowerCase().includes(q);
      return matchTitle || matchMsg || matchCompany;
    }
    return true;
  });

  const unreadCount = notifications.filter(n => !n.read).length;
  const criticalCount = notifications.filter(n => n.priority === 'CRITICAL' || n.priority === 'HIGH').length;

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'DISPATCH':
      case 'ORDER':
        return <Truck size={18} className="text-amber-500" />;
      case 'RFQ':
        return <FileText size={18} className="text-blue-500" />;
      case 'INVOICE':
      case 'PAYMENT':
        return <CreditCard size={18} className="text-emerald-500" />;
      case 'INVENTORY':
        return <Box size={18} className="text-purple-500" />;
      case 'RISK':
        return <AlertTriangle size={18} className="text-rose-500" />;
      case 'TWIN':
        return <Factory size={18} className="text-indigo-500" />;
      default:
        return <Bell size={18} className="text-gray-500" />;
    }
  };

  const getPriorityBadge = (priority: string) => {
    switch (priority) {
      case 'CRITICAL':
        return <span className="px-2 py-0.5 text-[11px] font-bold rounded bg-rose-100 text-rose-700 border border-rose-300">CRITICAL</span>;
      case 'HIGH':
        return <span className="px-2 py-0.5 text-[11px] font-bold rounded bg-amber-100 text-amber-800 border border-amber-300">HIGH</span>;
      case 'NORMAL':
        return <span className="px-2 py-0.5 text-[11px] font-bold rounded bg-blue-50 text-blue-700 border border-blue-200">NORMAL</span>;
      default:
        return <span className="px-2 py-0.5 text-[11px] font-bold rounded bg-gray-100 text-gray-600 border border-gray-200">INFO</span>;
    }
  };

  return (
    <div className="min-h-screen bg-slate-50/70 p-4 md:p-8 space-y-6">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0B2550] text-white px-4 py-3 rounded-xl shadow-xl flex items-center gap-3 border border-blue-800 animate-slide-up">
          <Sparkles size={18} className="text-amber-400 shrink-0" />
          <span className="text-sm font-semibold">{toastMessage}</span>
        </div>
      )}

      {/* Top Header & Live Sync Bar */}
      <div className="bg-white rounded-2xl p-6 shadow-sm border border-slate-200/80 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5 mb-1.5">
            <div className="p-2 bg-blue-50 text-[#0B2550] rounded-xl border border-blue-100">
              <Bell size={24} className="text-[#0B2550]" />
            </div>
            <div>
              <h1 className="text-2xl font-black text-[#0B2550] tracking-tight flex items-center gap-2">
                Notification Center
                <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-100 text-[#0B2550]">
                  Live Sync
                </span>
              </h1>
              <p className="text-xs text-slate-500 flex items-center gap-2 mt-0.5">
                <Building2 size={13} className="text-slate-400" />
                Company Context: <strong className="text-slate-800">{companyName}</strong> ({isSupplier ? 'Supplier Organization' : 'Enterprise Buyer HQ'})
              </p>
            </div>
          </div>
        </div>

        {/* Live Sync Status & Fast Actions */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Live Sync Pulse */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-emerald-50 border border-emerald-200/80 rounded-xl text-emerald-800 text-xs font-bold">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
            </span>
            <span>LIVE SYNC ACTIVE</span>
            <span className="text-[10px] text-emerald-600 font-normal">({formatTimeAgo(lastSynced.toISOString())})</span>
          </div>

          {/* Manual Refresh */}
          <button
            onClick={() => fetchNotifications(true)}
            disabled={syncing}
            className="p-2 text-slate-600 hover:text-[#0B2550] bg-slate-100 hover:bg-slate-200 rounded-xl transition-all flex items-center gap-1.5 text-xs font-semibold border border-slate-200"
            title="Force Live Sync Refresh"
          >
            <RefreshCw size={14} className={syncing ? 'animate-spin text-blue-600' : ''} />
            <span className="hidden sm:inline">Sync Now</span>
          </button>

          {/* Mark all as read */}
          <button
            onClick={handleMarkAllRead}
            disabled={unreadCount === 0}
            className="px-3 py-1.5 text-xs font-bold text-blue-700 bg-blue-50 hover:bg-blue-100 rounded-xl transition-all border border-blue-200 flex items-center gap-1.5 disabled:opacity-50"
          >
            <CheckCheck size={14} />
            <span>Mark All Read</span>
          </button>

          {/* Clear all */}
          <button
            onClick={handleClearAll}
            disabled={notifications.length === 0}
            className="px-3 py-1.5 text-xs font-bold text-slate-500 hover:text-rose-600 hover:bg-rose-50 rounded-xl transition-all border border-slate-200 flex items-center gap-1.5 disabled:opacity-50"
          >
            <Trash2 size={14} />
            <span>Clear</span>
          </button>
        </div>
      </div>

      {/* KPI Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
          <div>
            <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider">Total Alerts</p>
            <p className="text-2xl font-black text-slate-900 mt-1">{notifications.length}</p>
          </div>
          <div className="p-3 bg-blue-50 text-blue-600 rounded-xl">
            <Bell size={20} />
          </div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
          <div>
            <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider">Actions Required</p>
            <p className="text-2xl font-black text-amber-600 mt-1">{unreadCount}</p>
          </div>
          <div className="p-3 bg-amber-50 text-amber-600 rounded-xl">
            <Clock size={20} />
          </div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
          <div>
            <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider">High / Urgent</p>
            <p className="text-2xl font-black text-rose-600 mt-1">{criticalCount}</p>
          </div>
          <div className="p-3 bg-rose-50 text-rose-600 rounded-xl">
            <AlertTriangle size={20} />
          </div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
          <div>
            <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider">Live Polling</p>
            <p className="text-xs font-bold text-emerald-600 mt-1">Every 5 Seconds</p>
          </div>
          <div className="p-3 bg-emerald-50 text-emerald-600 rounded-xl">
            <Radio size={20} className="animate-pulse" />
          </div>
        </div>
      </div>

      {/* Live Event Simulator Bar (Instant Testing for the User) */}
      <div className="bg-gradient-to-r from-blue-900 to-[#0B2550] text-white p-4 rounded-2xl shadow-md border border-blue-800 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Sparkles size={20} className="text-amber-400 shrink-0" />
          <div>
            <h3 className="text-sm font-bold tracking-wide">Test Live Synchronization</h3>
            <p className="text-xs text-blue-200">
              Trigger a real-time workflow event across the platform to verify live sync updates.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {isSupplier ? (
            <>
              <button
                onClick={() => handleSimulateEvent('RFQ')}
                disabled={simulating}
                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold rounded-lg transition-all shadow-sm"
              >
                + Incoming RFQ
              </button>
              <button
                onClick={() => handleSimulateEvent('ORDER')}
                disabled={simulating}
                className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-xs font-bold rounded-lg transition-all shadow-sm"
              >
                + New PO Issued
              </button>
              <button
                onClick={() => handleSimulateEvent('PAYMENT')}
                disabled={simulating}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-lg transition-all shadow-sm"
              >
                + Wire Payment
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => handleSimulateEvent('DISPATCH')}
                disabled={simulating}
                className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-xs font-bold rounded-lg transition-all shadow-sm"
              >
                + Live Dispatch Shipped
              </button>
              <button
                onClick={() => handleSimulateEvent('RFQ')}
                disabled={simulating}
                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold rounded-lg transition-all shadow-sm"
              >
                + Quotation Received
              </button>
              <button
                onClick={() => handleSimulateEvent('INVOICE')}
                disabled={simulating}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-lg transition-all shadow-sm"
              >
                + Invoice 3-Way Match
              </button>
            </>
          )}
        </div>
      </div>

      {/* Main Workflow Notifications Container */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200/80 overflow-hidden">
        {/* Navigation Tabs & Search Toolbar */}
        <div className="p-4 border-b border-slate-100 flex flex-col md:flex-row md:items-center justify-between gap-3">
          {/* Tabs */}
          <div className="flex flex-wrap items-center gap-1.5">
            {[
              { id: 'ALL', label: 'All Alerts', count: notifications.length },
              { id: 'UNREAD', label: 'Unread Only', count: unreadCount },
              { id: 'DISPATCH', label: 'Orders & Dispatch', count: notifications.filter(n => n.category === 'DISPATCH' || n.category === 'ORDER').length },
              { id: 'RFQ', label: 'RFQs & Bids', count: notifications.filter(n => n.category === 'RFQ').length },
              { id: 'FINANCE', label: 'Invoices & Payments', count: notifications.filter(n => n.category === 'INVOICE' || n.category === 'PAYMENT').length },
              { id: 'INVENTORY', label: 'Inventory & Risk', count: notifications.filter(n => n.category === 'INVENTORY' || n.category === 'RISK' || n.category === 'TWIN').length },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3 py-1.5 text-xs font-bold rounded-xl transition-all flex items-center gap-1.5 ${
                  activeTab === tab.id
                    ? 'bg-[#0B2550] text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                <span>{tab.label}</span>
                <span className={`px-1.5 py-0.2 rounded-full text-[10px] ${
                  activeTab === tab.id ? 'bg-blue-800 text-white' : 'bg-slate-200 text-slate-700'
                }`}>
                  {tab.count}
                </span>
              </button>
            ))}
          </div>

          {/* Search & Priority Filter */}
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search notifications..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="pl-8 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#0B2550] w-48 sm:w-60"
              />
            </div>

            <select
              value={priorityFilter}
              onChange={e => setPriorityFilter(e.target.value)}
              className="py-1.5 px-2.5 text-xs bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#0B2550] text-slate-700 font-semibold"
            >
              <option value="ALL">All Priorities</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="NORMAL">Normal</option>
              <option value="INFO">Info</option>
            </select>
          </div>
        </div>

        {/* Notifications List */}
        <div className="divide-y divide-slate-100">
          {loading ? (
            <div className="p-12 text-center text-slate-400">
              <RefreshCw size={24} className="animate-spin mx-auto mb-2 text-blue-600" />
              <p className="text-sm font-semibold">Loading live notifications...</p>
            </div>
          ) : filteredNotifications.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              <CheckCircle2 size={36} className="mx-auto mb-2 text-emerald-500 opacity-60" />
              <p className="text-base font-bold text-slate-700">All caught up!</p>
              <p className="text-xs text-slate-400 mt-0.5">No notifications match your active filter.</p>
            </div>
          ) : (
            filteredNotifications.map(item => (
              <div
                key={item.id}
                className={`p-4 md:p-5 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4 ${
                  !item.read ? 'bg-blue-50/40 hover:bg-blue-50/70 border-l-4 border-l-[#0B2550]' : 'hover:bg-slate-50/80'
                }`}
              >
                {/* Left: Category Icon, Content & Metadata */}
                <div className="flex items-start gap-3.5 flex-1">
                  <div className={`p-2.5 rounded-xl border mt-0.5 shrink-0 ${
                    !item.read ? 'bg-white shadow-sm border-blue-200' : 'bg-slate-100 border-slate-200'
                  }`}>
                    {getCategoryIcon(item.category)}
                  </div>

                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-bold text-slate-900">{item.title}</span>
                      {getPriorityBadge(item.priority)}
                      {!item.read && (
                        <span className="px-2 py-0.5 text-[10px] font-black uppercase tracking-wider rounded-full bg-blue-600 text-white">
                          NEW
                        </span>
                      )}
                      <span className="text-[11px] text-slate-400 flex items-center gap-1">
                        <Clock size={11} />
                        {formatTimeAgo(item.created_at)}
                      </span>
                    </div>

                    <p className="text-xs text-slate-600 leading-relaxed max-w-2xl">
                      {item.message}
                    </p>

                    {/* Company Centric Attribution */}
                    <div className="flex flex-wrap items-center gap-3 pt-1 text-[11px] text-slate-500">
                      <span className="flex items-center gap-1 font-semibold text-slate-700">
                        <Building2 size={12} className="text-blue-500" />
                        Counterparty: <span className="text-blue-700">{item.partner_company}</span>
                      </span>
                      {item.metadata?.po_id && (
                        <span className="px-1.5 py-0.5 bg-slate-100 rounded font-mono text-[10px] text-slate-700">
                          PO: {item.metadata.po_id}
                        </span>
                      )}
                      {item.metadata?.rfq_id && (
                        <span className="px-1.5 py-0.5 bg-slate-100 rounded font-mono text-[10px] text-slate-700">
                          RFQ: {item.metadata.rfq_id}
                        </span>
                      )}
                      {item.metadata?.invoice_id && (
                        <span className="px-1.5 py-0.5 bg-slate-100 rounded font-mono text-[10px] text-slate-700">
                          INV: {item.metadata.invoice_id}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Right: Direct Workflow Action Buttons */}
                <div className="flex items-center gap-2 shrink-0 self-end md:self-center">
                  {/* Action Link directly to the workflow page */}
                  <Link
                    href={item.action_url}
                    onClick={() => handleMarkRead(item.id)}
                    className="px-3.5 py-2 text-xs font-bold text-white bg-[#0B2550] hover:bg-blue-900 rounded-xl transition-all shadow-sm flex items-center gap-1.5 hover:shadow-md"
                  >
                    <span>{item.action_label}</span>
                    <ArrowRight size={13} />
                  </Link>

                  {/* Read / Unread toggle */}
                  {!item.read ? (
                    <button
                      onClick={(e) => handleMarkRead(item.id, e)}
                      title="Mark as Read"
                      className="p-2 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-xl transition-all"
                    >
                      <CheckCircle2 size={16} />
                    </button>
                  ) : (
                    <button
                      onClick={(e) => handleMarkUnread(item.id, e)}
                      title="Mark as Unread"
                      className="p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-xl transition-all"
                    >
                      <Clock size={16} />
                    </button>
                  )}

                  {/* Dismiss */}
                  <button
                    onClick={(e) => handleDelete(item.id, e)}
                    title="Dismiss"
                    className="p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-xl transition-all"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
