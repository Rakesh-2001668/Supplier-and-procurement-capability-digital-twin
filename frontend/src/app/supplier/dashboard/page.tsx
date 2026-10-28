'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Factory, Settings, FileText, CheckCircle2, Clock, AlertTriangle,
  Truck, DollarSign, TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight,
  ArrowRight,
  ShieldCheck, RefreshCw, Send, Check, Box, Calendar, ChevronRight,
  Layers, Wrench, Sparkles, Building2, MapPin, ExternalLink, X, AlertCircle
} from 'lucide-react';
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid
} from 'recharts';
import { apiClient, TEST_SUPPLIER_TENANT_ID } from '@/lib/apiClient';

interface TrajectoryDataPoint {
  month: string;
  revenue: number;
  profit: number;
  utilization: number;
  event: string | null;
  type: 'UPTURN' | 'DOWNTURN' | null;
}

interface ActionRequired {
  id: string;
  type: string;
  urgency: 'High' | 'Medium' | 'Low';
  title: string;
  counterparty: string;
  deadline: string;
  action_label: string;
  target_link: string;
  details: string;
}

interface ActiveOrderSummary {
  po_number: string;
  amount: number;
  status: string;
  customer: string;
  progress_pct: number;
  stage: string;
}

interface PendingRfqSummary {
  rfq_id: string;
  part_title: string;
  target_quantity: number;
  buyer_org: string;
  deadline: string;
  status: string;
}

export default function SupplierDashboardPage() {
  const queryClient = useQueryClient();
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('12M');
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [modalAction, setModalAction] = useState<ActionRequired | null>(null);

  // Fetch company-centric supplier dashboard data from backend
  const { data: dashboard, isLoading, refetch } = useQuery({
    queryKey: ['supplier-dashboard-overview', TEST_SUPPLIER_TENANT_ID],
    queryFn: async () => {
      try {
        const res = await apiClient.get(`/api/v1/supplier/dashboard-overview?tenant_id=${TEST_SUPPLIER_TENANT_ID}`);
        return res.data;
      } catch (err) {
        return null;
      }
    }
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleExecuteAction = (act: ActionRequired) => {
    showToast(`Action executed: ${act.title}`);
    setModalAction(null);
  };

  const firm = dashboard?.firm_profile || {
    company_name: "ABC Manufacturing Ltd",
    legal_entity: "ABC Manufacturing & Industrial Technologies Ltd",
    digital_twin_id: "TWIN-ABC-MFG-001",
    tier: "Tier 1 Qualified Production Partner",
    location: "Precision Industrial Corridor, Phase II",
    facility_type: "AS9100D Certified 5-Axis Precision Machining Facility",
    verified_twin_score: 96
  };

  const financials = dashboard?.financials || {
    revenue_ytd: 485200.0,
    gross_profit: 162400.0,
    gross_profit_margin_pct: 33.5,
    operating_cogs: 322800.0,
    scrap_and_tooling_loss: 8200.0,
    active_wip_revenue: 88500.0,
    rfq_pipeline_value: 128500.0,
    on_time_payment_rate: 98.2
  };

  const factory = dashboard?.factory_progress || {
    active_jobs_count: 4,
    overall_batch_progress_pct: 78.4,
    overall_equipment_effectiveness_oee: 88.4,
    on_time_delivery_otif: 97.8,
    defect_ppm: 65,
    active_cnc_spindles: 12,
    spindle_utilization_pct: 84.5
  };

  // Trajectory custom tooltip
  const CustomTrajectoryTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload as TrajectoryDataPoint;
      return (
        <div className="bg-slate-900 text-white p-3.5 rounded-xl shadow-xl border border-slate-700 text-xs space-y-1.5 max-w-xs z-50">
          <div className="flex items-center justify-between border-b border-slate-800 pb-1 font-bold">
            <span className="text-blue-300">{data.month}</span>
            <span className="text-purple-300">OEE: {data.utilization}%</span>
          </div>
          <div className="flex justify-between text-slate-300">
            <span>Invoiced Revenue:</span>
            <span className="font-bold text-white">${data.revenue.toLocaleString()}</span>
          </div>
          <div className="flex justify-between text-slate-300">
            <span>Gross Profit:</span>
            <span className="font-bold text-emerald-400">+${data.profit.toLocaleString()}</span>
          </div>
          {data.event && (
            <div className={`mt-2 pt-1.5 border-t border-slate-800 font-semibold flex items-start gap-1.5 ${
              data.type === 'UPTURN' ? 'text-emerald-400' : 'text-red-400'
            }`}>
              {data.type === 'UPTURN' ? <TrendingUp className="w-3.5 h-3.5 shrink-0 mt-0.5" /> : <TrendingDown className="w-3.5 h-3.5 shrink-0 mt-0.5" />}
              <span>{data.event}</span>
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="space-y-6 pb-16 max-w-[1600px] mx-auto">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 border border-blue-400/30 animate-in fade-in slide-in-from-top-4">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-bold">{toastMessage}</span>
        </div>
      )}

      {/* HEADER: DEDICATED COMPANY-CENTRIC SUPPLIER COCKPIT */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Supplier Operations</span>
            <span className="text-slate-300">/</span>
            <span className="text-purple-600 font-bold">Supplier Command Center</span>
            <span className="text-slate-300">/</span>
            <span>{firm.company_name} Dashboard</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <Factory className="w-8 h-8 text-purple-600" />
            <span>Supplier Dashboard: {firm.company_name}</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Company-centric operational overview: tracking pending RFQs, active POs in fabrication, P&L margins, factory utilization, and historical growth trajectory.
          </p>
        </div>

        {/* Global Controls */}
        <div className="flex items-center flex-wrap gap-2.5">
          <button
            onClick={() => {
              refetch();
              showToast(`Synchronized live factory telemetry for ${firm.company_name}.`);
            }}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <RefreshCw className="w-4 h-4 text-slate-500" />
            <span>Sync Shop-Floor IoT</span>
          </button>

          <Link
            href="/supplier/rfqs"
            className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95"
          >
            <Send className="w-4 h-4" />
            <span>Review Incoming RFQs</span>
          </Link>
        </div>
      </div>

      {/* COMPANY HERO CARD FOR THE SUPPLIER FIRM */}
      <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm relative overflow-hidden">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          <div className="space-y-2 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="px-2.5 py-1 rounded-md text-xs font-black bg-purple-100 text-purple-800 flex items-center gap-1">
                <Factory className="w-3.5 h-3.5" /> {firm.tier}
              </span>
              <span className="px-2.5 py-1 rounded-md text-xs font-bold bg-slate-100 text-slate-600 flex items-center gap-1">
                <MapPin className="w-3.5 h-3.5 text-slate-400" />
                {firm.location}
              </span>
              <span className="text-xs font-bold text-slate-400">
                Digital Twin: <code className="text-slate-600 font-mono font-bold">{firm.digital_twin_id}</code>
              </span>
            </div>

            <h2 className="text-2xl font-black text-[#0B2550] tracking-tight flex items-center gap-2">
              <span>{firm.company_name}</span>
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" title="Factory Telemetry Online" />
            </h2>
            <p className="text-xs text-slate-500 font-medium">
              {firm.legal_entity} • {firm.facility_type}
            </p>
          </div>

          {/* Quick Twin Performance Metrics */}
          <div className="flex items-center gap-4 bg-slate-50 p-4 rounded-xl border border-slate-100 shrink-0">
            <div className="text-center px-3 border-r border-slate-200">
              <span className="text-[10px] font-black uppercase text-slate-400 block tracking-wider">
                Twin Trust Score
              </span>
              <span className="text-3xl font-black text-emerald-600 block mt-0.5">
                {firm.verified_twin_score}%
              </span>
              <span className="text-[10px] font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded mt-1 inline-block">
                AS9100 Verified
              </span>
            </div>

            <div className="text-center px-3 border-r border-slate-200">
              <span className="text-[10px] font-black uppercase text-slate-400 block tracking-wider">
                On-Time Delivery (OTIF)
              </span>
              <span className="text-2xl font-black text-[#0B2550] block mt-0.5">
                {factory.on_time_delivery_otif}%
              </span>
              <span className="text-[10px] text-slate-400 font-bold mt-1 block">
                Defect: {factory.defect_ppm} PPM
              </span>
            </div>

            <div className="text-center px-3">
              <span className="text-[10px] font-black uppercase text-slate-400 block tracking-wider">
                Active Spindles
              </span>
              <span className="text-2xl font-black text-purple-700 block mt-0.5">
                {factory.active_cnc_spindles} CNCs
              </span>
              <span className="text-[10px] text-purple-600 font-bold mt-1 block">
                {factory.spindle_utilization_pct}% Utilization
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 5 EXECUTIVE FINANCIAL & WORKS OVERVIEW KPI CARDS */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* Card 1: Invoiced Revenue (YTD) */}
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Revenue (YTD)</span>
            <DollarSign className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="text-2xl font-black text-[#0B2550]">
            ${(financials.revenue_ytd / 1000).toFixed(1)}k
          </div>
          <div className="text-[11px] text-slate-500 flex justify-between pt-1 border-t border-slate-100">
            <span>Invoiced & Settled</span>
            <span className="text-emerald-600 font-bold">+18.4% YoY</span>
          </div>
        </div>

        {/* Card 2: Realized Gross Profit & Margin */}
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Gross Profit</span>
            <span className="text-[10px] px-2 py-0.5 rounded font-black bg-emerald-50 text-emerald-700">
              {financials.gross_profit_margin_pct}% Margin
            </span>
          </div>
          <div className="text-2xl font-black text-emerald-600">
            +${(financials.gross_profit / 1000).toFixed(1)}k
          </div>
          <div className="text-[11px] text-slate-500 flex justify-between pt-1 border-t border-slate-100">
            <span>Operating COGS</span>
            <span className="font-bold text-slate-700">${(financials.operating_cogs / 1000).toFixed(1)}k</span>
          </div>
        </div>

        {/* Card 3: Scrap & Tooling Variance Loss */}
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Scrap & Tooling Loss</span>
            <TrendingDown className="w-4 h-4 text-amber-500" />
          </div>
          <div className="text-2xl font-black text-amber-600">
            -${(financials.scrap_and_tooling_loss / 1000).toFixed(1)}k
          </div>
          <div className="text-[11px] text-slate-500 flex justify-between pt-1 border-t border-slate-100">
            <span>Variance Rate</span>
            <span className="font-bold text-slate-700">1.7% of COGS</span>
          </div>
        </div>

        {/* Card 4: Active WIP Revenue */}
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Active WIP Orders</span>
            <Box className="w-4 h-4 text-blue-500" />
          </div>
          <div className="text-2xl font-black text-blue-600">
            ${(financials.active_wip_revenue / 1000).toFixed(1)}k
          </div>
          <div className="text-[11px] text-slate-500 flex justify-between pt-1 border-t border-slate-100">
            <span>Shop-Floor Progress</span>
            <span className="font-bold text-blue-600">{factory.overall_batch_progress_pct}% Complete</span>
          </div>
        </div>

        {/* Card 5: RFQ Bidding Pipeline */}
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>RFQ Pipeline</span>
            <FileText className="w-4 h-4 text-purple-500" />
          </div>
          <div className="text-2xl font-black text-purple-700">
            ${(financials.rfq_pipeline_value / 1000).toFixed(1)}k
          </div>
          <div className="text-[11px] text-slate-500 flex justify-between pt-1 border-t border-slate-100">
            <span>Bids Under Review</span>
            <span className="font-bold text-purple-600">3 Open RFQs</span>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* ACTION REQUIRED QUEUE: PENDING RFQS & PO DISPATCH MILESTONES */}
      {/* ========================================================================= */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-amber-600" />
              <h3 className="text-base font-black text-[#0B2550]">
                Action Required Queue: Critical RFQs & Purchase Order Tasks
              </h3>
            </div>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              Urgent quotation deadlines, shipment ASN dispatches, and invoice generation awaiting firm action.
            </p>
          </div>
          <span className="text-xs font-bold text-amber-700 bg-amber-50 px-2.5 py-1 rounded-lg">
            {dashboard?.actions_required?.length || 4} Tasks Pending Action
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {dashboard?.actions_required?.map((act: ActionRequired) => (
            <div
              key={act.id}
              className={`p-4 rounded-xl border transition-all flex flex-col justify-between space-y-3 ${
                act.urgency === 'High' 
                  ? 'bg-amber-50/40 border-amber-200 hover:border-amber-300' 
                  : 'bg-slate-50/60 border-slate-200 hover:border-blue-300'
              }`}
            >
              <div className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${
                    act.urgency === 'High' ? 'bg-amber-100 text-amber-800' : 'bg-slate-200 text-slate-700'
                  }`}>
                    {act.urgency} Urgency
                  </span>
                  <span className="text-xs font-bold text-slate-500 flex items-center gap-1">
                    <Clock className="w-3 h-3 text-slate-400" />
                    {act.deadline}
                  </span>
                </div>

                <h4 className="text-sm font-black text-[#0B2550] pt-1">
                  {act.title}
                </h4>
                <p className="text-xs text-slate-600 leading-snug">
                  Customer: <span className="font-bold text-slate-800">{act.counterparty}</span> • {act.details}
                </p>
              </div>

              <div className="pt-2 border-t border-slate-200/60 flex items-center justify-between">
                <span className="text-[11px] font-mono text-slate-400 font-bold">{act.id}</span>
                <button
                  onClick={() => handleExecuteAction(act)}
                  className="px-3.5 py-1.5 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-lg shadow-sm transition-all flex items-center gap-1 active:scale-95"
                >
                  <span>{act.action_label}</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* CORE VISUALIZATION: 12-MONTH HISTORICAL "UPS & DOWNS" OF THE SUPPLIER FIRM */}
      <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-purple-600" />
              <h3 className="text-lg font-black text-[#0B2550]">
                {firm.company_name}: 12-Month "Ups & Downs" Volatility & Profitability Trajectory
              </h3>
            </div>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              Monthly billed revenue, realized gross profit, and factory capacity utilization swings (surges vs. maintenance dips).
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-xs font-bold text-slate-500 border border-slate-200 rounded-lg px-2.5 py-1">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-purple-600" /> Monthly Revenue
              </span>
              <span className="flex items-center gap-1.5 ml-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" /> Gross Profit
              </span>
            </div>

            <div className="flex bg-slate-100 p-0.5 rounded-lg text-xs font-bold text-slate-600">
              {['6M', '12M', 'YTD'].map((t) => (
                <button
                  key={t}
                  onClick={() => setSelectedTimeframe(t)}
                  className={`px-3 py-1 rounded-md transition-all ${
                    selectedTimeframe === t ? 'bg-white text-purple-600 shadow-sm' : 'hover:text-slate-900'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Recharts Trajectory Graph */}
        <div className="h-80 w-full pt-4">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={dashboard?.ups_and_downs || []} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
              <defs>
                <linearGradient id="supRevGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#9333ea" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#9333ea" stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="supProfitGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
              <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11, fontWeight: 600 }} />
              <YAxis axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11, fontWeight: 600 }} />
              <Tooltip content={<CustomTrajectoryTooltip />} />
              <Area type="monotone" dataKey="revenue" stroke="#9333ea" strokeWidth={2.5} fill="url(#supRevGrad)" name="Revenue ($)" />
              <Area type="monotone" dataKey="profit" stroke="#10b981" strokeWidth={2.5} fill="url(#supProfitGrad)" name="Profit ($)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="flex items-center justify-between text-xs text-slate-400 font-medium px-2 pt-2 border-t border-slate-100">
          <span>Historical markers capture operational downtime (spindle bearing replacement) vs. breakthroughs (robotic automation cell launch).</span>
          <span className="font-bold text-slate-600">Overall OEE Health: 88.4%</span>
        </div>
      </div>

      {/* TWO-COLUMN LOWER SECTION: ACTIVE PURCHASE ORDERS & PENDING RFQS */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column: Active Purchase Orders in Production */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-black text-[#0B2550] flex items-center gap-2">
                  <Box className="w-5 h-5 text-purple-600" />
                  <span>Active Purchase Orders in Production</span>
                </h3>
                <p className="text-xs text-slate-500 font-medium mt-0.5">
                  Orders currently undergoing 5-axis milling, CMM metrology inspection, and packaging.
                </p>
              </div>

              <Link
                href="/supplier/orders"
                className="text-xs font-bold text-purple-600 hover:underline flex items-center gap-1"
              >
                <span>All Orders</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </Link>
            </div>

            <div className="space-y-3">
              {dashboard?.active_orders_summary?.map((po: ActiveOrderSummary) => (
                <div key={po.po_number} className="p-3.5 rounded-xl border border-slate-100 bg-slate-50/50 space-y-2">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-black text-sm text-[#0B2550]">{po.po_number}</span>
                        <span className="text-xs font-bold text-slate-500">• {po.customer}</span>
                      </div>
                      <p className="text-xs text-slate-600 mt-0.5">{po.stage}</p>
                    </div>

                    <div className="text-right">
                      <span className="text-sm font-black text-[#0B2550] block">
                        ${po.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                      </span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${
                        po.status === 'ISSUED' ? 'bg-blue-100 text-blue-800' :
                        po.status === 'INVOICED' ? 'bg-emerald-100 text-emerald-800' :
                        'bg-purple-100 text-purple-800'
                      }`}>
                        {po.status}
                      </span>
                    </div>
                  </div>

                  <div className="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden">
                    <div className="bg-purple-600 h-1.5 rounded-full" style={{ width: `${po.progress_pct}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>Committed Delivery Accuracy: 97.8% OTIF</span>
            <Link href="/supplier/orders" className="font-bold text-purple-600 hover:underline">
              Manage Order Shipments & ASNs
            </Link>
          </div>
        </div>

        {/* Right Column: Pending Incoming RFQs & Bids */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-black text-[#0B2550] flex items-center gap-2">
                  <FileText className="w-5 h-5 text-blue-600" />
                  <span>Incoming RFQs & Bidding Opportunities</span>
                </h3>
                <p className="text-xs text-slate-500 font-medium mt-0.5">
                  Procurement quote requests matched against {firm.company_name}'s capability twin.
                </p>
              </div>

              <Link
                href="/supplier/rfqs"
                className="text-xs font-bold text-blue-600 hover:underline flex items-center gap-1"
              >
                <span>All RFQs</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </Link>
            </div>

            <div className="space-y-3">
              {dashboard?.pending_rfqs_summary?.map((rfq: PendingRfqSummary) => (
                <div key={rfq.rfq_id} className="p-3.5 rounded-xl border border-slate-100 bg-slate-50/50 flex items-center justify-between gap-3">
                  <div className="space-y-1 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-black text-sm text-[#0B2550]">{rfq.rfq_id}</span>
                      <span className="text-xs font-bold text-slate-500">• {rfq.buyer_org}</span>
                    </div>
                    <p className="text-xs text-slate-700 font-medium">{rfq.part_title}</p>
                    <p className="text-[11px] text-slate-400">
                      Quantity: <span className="font-bold text-slate-600">{rfq.target_quantity} pcs</span> • Deadline: <span className="font-bold text-red-600">{rfq.deadline}</span>
                    </p>
                  </div>

                  <Link
                    href={`/supplier/rfqs/bid?rfq_id=${rfq.rfq_id}`}
                    className="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs rounded-lg shadow-sm transition-all shrink-0 active:scale-95"
                  >
                    Submit Bid
                  </Link>
                </div>
              ))}
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>Average Win Rate: 42% on Matched RFQs</span>
            <Link href="/supplier/rfqs" className="font-bold text-blue-600 hover:underline">
              View RFQ Bidding Center
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
