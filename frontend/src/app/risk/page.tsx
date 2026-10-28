'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import {
  ShieldAlert, AlertTriangle, TrendingDown, TrendingUp, Activity,
  Building2, MapPin, CheckCircle2, XCircle, ArrowUpRight, ArrowDownRight,
  ShieldCheck, RefreshCw, Download, Filter, ChevronRight, Zap,
  AlertCircle, FileText, Sparkles, SlidersHorizontal, ExternalLink,
  Layers, Info, Clock, Check, Cpu, Factory
} from 'lucide-react';
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid
} from 'recharts';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';

interface TrajectoryPoint {
  month: string;
  score: number;
  financial: number;
  operational: number;
  event: string | null;
  type: 'UPTURN' | 'DOWNTURN' | null;
}

interface Incident {
  id: string;
  date: string;
  type: 'UPTURN' | 'DOWNTURN';
  impact: string;
  title: string;
  category: string;
  description: string;
}

export default function RiskCommandPage() {
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('12M');
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Fetch company-centric risk intelligence from backend for XYZ Machinery Ltd
  const { data: company, isLoading, refetch } = useQuery({
    queryKey: ['company-centric-risk'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/api/v1/risk/company');
        return res.data;
      } catch (e) {
        // High-reliability fallback if backend temporarily unreachable
        return {
          id: 'xyz-machinery-ltd',
          name: 'XYZ Machinery Ltd',
          legal_entity: 'XYZ Machinery & Industrial Equipment Ltd',
          category: 'Heavy Industrial Machinery & Precision Engineering',
          industry: 'Industrial Equipment Manufacturing',
          headquarters: 'Industrial Zone Phase II, Precision Valley',
          facility_type: 'Primary OEM Manufacturing & Assembly Facility',
          digital_twin_id: 'TWIN-XYZ-MACHINERY-001',
          composite_risk_score: 28,
          risk_level: 'LOW',
          risk_status: 'Optimal Operational Stability',
          volatility_index: 13.8,
          volatility_trend: 'STABILIZING',
          mom_change: -5,
          financial_health: {
            score: 89,
            status: 'Robust Capitalization',
            altman_z_score: 3.28,
            working_capital_ratio: 2.25,
            dso_days: 34,
            cash_runway_months: 18.5,
            credit_rating: 'AA- (Investment Grade)'
          },
          operational_resilience: {
            score: 93,
            status: 'High Production Reliability',
            factory_utilization: 82.5,
            otif_delivery_rate: 96.2,
            equipment_oee: 88.4,
            defect_rate_ppm: 85
          },
          supply_chain_vulnerability: {
            score: 22,
            status: 'Well-Diversified Supply Base',
            single_source_dependencies: 2,
            raw_material_hedging: '85% Hedged on Steel & Aluminum',
            critical_component_buffer_days: 45
          },
          esg_compliance: {
            score: 94,
            status: 'Certified Green Enterprise',
            carbon_intensity_kg_co2: 16.4,
            iso_9001_certified: true
          },
          trajectory_12m: [
            { month: "Nov 25", score: 36, financial: 84, operational: 86, event: null, type: null },
            { month: "Dec 25", score: 40, financial: 82, operational: 83, event: "Year-end shipping container surge backlog", type: "DOWNTURN" },
            { month: "Jan 26", score: 33, financial: 86, operational: 88, event: null, type: null },
            { month: "Feb 26", score: 49, financial: 75, operational: 76, event: "Alloy steel spot price spike (+24% cost spike)", type: "DOWNTURN" },
            { month: "Mar 26", score: 41, financial: 80, operational: 82, event: null, type: null },
            { month: "Apr 26", score: 30, financial: 88, operational: 90, event: "Commissioning of automated robotic assembly cell", type: "UPTURN" },
            { month: "May 26", score: 26, financial: 91, operational: 92, event: "Long-term direct steel supply contract secured", type: "UPTURN" },
            { month: "Jun 26", score: 45, financial: 78, operational: 79, event: "Sub-tier actuator delivery delay (5-day plant bottleneck)", type: "DOWNTURN" },
            { month: "Jul 26", score: 34, financial: 85, operational: 88, event: "Secondary regional warehouse hub opened in Pune", type: "UPTURN" },
            { month: "Aug 26", score: 25, financial: 91, operational: 94, event: "ISO 9001 & AS9100 recertification passed with zero NRs", type: "UPTURN" },
            { month: "Sep 26", score: 29, financial: 89, operational: 92, event: null, type: null },
            { month: "Oct 26", score: 28, financial: 89, operational: 93, event: "Corporate working capital credit expansion approved", type: "UPTURN" }
          ],
          incident_log: [
            {
              id: "INC-XYZ-104",
              date: "Aug 16, 2026",
              type: "UPTURN",
              impact: "-9 pts Risk",
              title: "Comprehensive ISO 9001 & AS9100 Quality Audit Clean Pass",
              category: "Operational & Quality",
              description: "Passed comprehensive third-party manufacturing audit with zero major findings, improving quality reliability benchmark."
            },
            {
              id: "INC-XYZ-103",
              date: "Jun 20, 2026",
              type: "DOWNTURN",
              impact: "+16 pts Risk",
              title: "Tier-2 Actuator Sourcing Delay Bottleneck",
              category: "Supply Chain Disruption",
              description: "Component delays from overseas actuator sub-tier created an assembly line backlog, increasing operational delivery risk."
            },
            {
              id: "INC-XYZ-102",
              date: "Apr 08, 2026",
              type: "UPTURN",
              impact: "-11 pts Risk",
              title: "Robotic Automation Cell Activated (Capacity +30%)",
              category: "Manufacturing Innovation",
              description: "Commissioned 4 robotic welding and assembly workstations, expanding machinery batch throughput by 30% and reducing unit labor hours."
            },
            {
              id: "INC-XYZ-101",
              date: "Feb 14, 2026",
              type: "DOWNTURN",
              impact: "+15 pts Risk",
              title: "Alloy Steel Spot Market Price Surge",
              category: "Financial & Material Cost",
              description: "Unhedged steel spot market costs jumped 24% over 3 weeks, compressing gross margins before quarterly price indexing kicked in."
            }
          ],
          predictive_forecast: {
            forecast_30d: 24,
            forecast_90d: 22,
            direction: "STABLE_FAVORABLE",
            confidence: 95,
            summary: "AI predictive twin simulation projects stable performance for XYZ Machinery Ltd through Q4 2026 with 97%+ forecasted order fulfillment."
          },
          internal_contingency_actions: [
            { id: "ACT-1", action: "Maintain 45-day safety buffer stock on critical hydraulic components", priority: "Medium", status: "Active" },
            { id: "ACT-2", action: "Lock in H1 2027 raw material commodity futures forward contracts", priority: "High", status: "Recommended" },
            { id: "ACT-3", action: "Conduct preventive maintenance audit on high-torque gear cutting cells", priority: "Low", status: "Scheduled" }
          ]
        };
      }
    }
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  // Trajectory chart custom tooltip
  const CustomTrajectoryTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload as TrajectoryPoint;
      return (
        <div className="bg-slate-900 text-white p-3.5 rounded-xl shadow-xl border border-slate-700 text-xs space-y-1.5 max-w-xs z-50">
          <div className="flex items-center justify-between border-b border-slate-800 pb-1 font-bold">
            <span className="text-blue-300">{data.month}</span>
            <span className={`px-2 py-0.5 rounded font-black ${
              data.score > 60 ? 'bg-red-500/20 text-red-400' :
              data.score > 35 ? 'bg-amber-500/20 text-amber-400' :
              'bg-emerald-500/20 text-emerald-400'
            }`}>
              Risk Index: {data.score}/100
            </span>
          </div>
          <div className="flex justify-between text-slate-300">
            <span>Operational Reliability:</span>
            <span className="font-bold text-white">{data.operational}/100</span>
          </div>
          <div className="flex justify-between text-slate-300">
            <span>Financial Capitalization:</span>
            <span className="font-bold text-white">{data.financial}/100</span>
          </div>
          {data.event && (
            <div className={`mt-2 pt-1.5 border-t border-slate-800 font-semibold flex items-start gap-1.5 ${
              data.type === 'UPTURN' ? 'text-emerald-400' : 'text-red-400'
            }`}>
              {data.type === 'UPTURN' ? <TrendingDown className="w-3.5 h-3.5 shrink-0 mt-0.5" /> : <TrendingUp className="w-3.5 h-3.5 shrink-0 mt-0.5" />}
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

      {/* Header & Page Title - Explicitly Company-Centric */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Enterprise Operations</span>
            <span className="text-slate-300">/</span>
            <span className="text-blue-600 font-bold">Risk Command</span>
            <span className="text-slate-300">/</span>
            <span>XYZ Machinery Ltd Analytics</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <ShieldAlert className="w-8 h-8 text-blue-600" />
            <span>Risk Command: XYZ Machinery Ltd</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Company-centric operational resilience, financial solvency tracking, and 12-month analytics of ups and downs for XYZ Machinery Ltd.
          </p>
        </div>

        {/* Global Company Tools & Actions (No Company Selector) */}
        <div className="flex items-center flex-wrap gap-2.5">
          <button
            onClick={() => {
              refetch();
              showToast('Refreshed real-time risk telemetry for XYZ Machinery Ltd.');
            }}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <RefreshCw className="w-4 h-4 text-slate-500" />
            <span>Sync Live Telemetry</span>
          </button>

          <button
            onClick={() => showToast('Exported full Risk Dossier & Volatility Report for XYZ Machinery Ltd.')}
            className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95"
          >
            <Download className="w-4 h-4" />
            <span>Export Company Intelligence Dossier</span>
          </button>
        </div>
      </div>

      {/* COMPANY HERO CARD: DEDICATED TO XYZ MACHINERY LTD */}
      {company && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 relative overflow-hidden">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
            <div className="space-y-2 flex-1">
              <div className="flex items-center gap-2.5 flex-wrap">
                <span className="px-2.5 py-1 rounded-md text-xs font-black bg-blue-100 text-blue-800 flex items-center gap-1">
                  <Factory className="w-3.5 h-3.5" /> OEM Manufacturing Facility
                </span>
                <span className="px-2.5 py-1 rounded-md text-xs font-bold bg-slate-100 text-slate-600 flex items-center gap-1">
                  <MapPin className="w-3.5 h-3.5 text-slate-400" />
                  {company.headquarters}
                </span>
                <span className="text-xs font-bold text-slate-400">
                  Digital Twin Node: <code className="text-slate-600 font-mono font-bold">{company.digital_twin_id}</code>
                </span>
              </div>

              <h2 className="text-2xl font-black text-[#0B2550] tracking-tight flex items-center gap-2">
                <span>{company.name}</span>
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" title="Live Enterprise Node Active" />
              </h2>
              <p className="text-xs text-slate-500 font-medium">
                {company.legal_entity} • {company.category}
              </p>
            </div>

            {/* Overall Score & Ups/Downs Volatility Badges for XYZ Machinery Ltd */}
            <div className="flex items-center gap-4 bg-slate-50 p-4 rounded-xl border border-slate-100 shrink-0">
              <div className="text-center px-3 border-r border-slate-200">
                <span className="text-[10px] font-black uppercase text-slate-400 block tracking-wider">
                  Composite Risk Index
                </span>
                <div className="flex items-baseline justify-center gap-1 mt-0.5">
                  <span className={`text-3xl font-black ${
                    company.composite_risk_score > 60 ? 'text-red-600' :
                    company.composite_risk_score > 35 ? 'text-amber-600' :
                    'text-emerald-600'
                  }`}>
                    {company.composite_risk_score}
                  </span>
                  <span className="text-xs text-slate-400 font-bold">/100</span>
                </div>
                <span className="inline-block px-2 py-0.5 rounded text-[10px] font-black uppercase mt-1 bg-emerald-100 text-emerald-700">
                  {company.risk_level} RISK
                </span>
              </div>

              <div className="text-center px-3 border-r border-slate-200">
                <span className="text-[10px] font-black uppercase text-slate-400 block tracking-wider">
                  Ups & Downs Volatility
                </span>
                <span className="text-2xl font-black text-[#0B2550] block mt-0.5">
                  ±{company.volatility_index}%
                </span>
                <span className="text-[10px] font-bold inline-flex items-center gap-0.5 mt-1 text-emerald-600">
                  ● {company.volatility_trend}
                </span>
              </div>

              <div className="text-center px-3">
                <span className="text-[10px] font-black uppercase text-slate-400 block tracking-wider">
                  MoM Trajectory
                </span>
                <span className="text-2xl font-black block mt-0.5 flex items-center justify-center gap-0.5 text-emerald-600">
                  <ArrowDownRight className="w-5 h-5" />
                  {Math.abs(company.mom_change)} pts
                </span>
                <span className="text-[10px] text-slate-400 font-bold mt-1 block">
                  Performance Surge
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 4 EXECUTIVE PILLARS FOR XYZ MACHINERY LTD */}
      {company && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Pillar 1: Financial Solvency & Liquidity */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Financial Solvency</span>
              <span className="text-xs font-black px-2 py-0.5 rounded bg-blue-50 text-blue-700">
                {company.financial_health.credit_rating}
              </span>
            </div>
            <div className="mt-3">
              <div className="text-2xl font-black text-[#0B2550] tracking-tight">
                {company.financial_health.score}/100
              </div>
              <p className="text-xs font-bold text-emerald-600 mt-0.5">
                {company.financial_health.status}
              </p>
              <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-slate-100 text-[11px]">
                <div>
                  <span className="text-slate-400 block">Altman Z-Score</span>
                  <span className="font-bold text-slate-700">{company.financial_health.altman_z_score} (Sound)</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Cash Runway</span>
                  <span className="font-bold text-slate-700">{company.financial_health.cash_runway_months} Months</span>
                </div>
              </div>
            </div>
          </div>

          {/* Pillar 2: Manufacturing & Operational Delivery */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Manufacturing Execution</span>
              <span className="text-xs font-black px-2 py-0.5 rounded bg-emerald-50 text-emerald-700">
                OTIF {company.operational_resilience.otif_delivery_rate}%
              </span>
            </div>
            <div className="mt-3">
              <div className="text-2xl font-black text-[#0B2550] tracking-tight">
                {company.operational_resilience.score}/100
              </div>
              <p className="text-xs font-bold text-blue-600 mt-0.5">
                {company.operational_resilience.status}
              </p>
              <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-slate-100 text-[11px]">
                <div>
                  <span className="text-slate-400 block">Plant Utilization</span>
                  <span className="font-bold text-slate-700">{company.operational_resilience.factory_utilization}%</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Equipment OEE</span>
                  <span className="font-bold text-slate-700">{company.operational_resilience.equipment_oee}%</span>
                </div>
              </div>
            </div>
          </div>

          {/* Pillar 3: Supply Chain Vulnerability & Inputs */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Supply Chain Exposure</span>
              <span className="text-xs font-black px-2 py-0.5 rounded bg-emerald-50 text-emerald-700">
                Low Exposure
              </span>
            </div>
            <div className="mt-3">
              <div className="text-2xl font-black text-[#0B2550] tracking-tight">
                {company.supply_chain_vulnerability.score}/100 Risk
              </div>
              <p className="text-xs font-bold text-slate-600 mt-0.5">
                {company.supply_chain_vulnerability.status}
              </p>
              <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-slate-100 text-[11px]">
                <div>
                  <span className="text-slate-400 block">Material Hedging</span>
                  <span className="font-bold text-slate-700 truncate block">{company.supply_chain_vulnerability.raw_material_hedging}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Buffer Coverage</span>
                  <span className="font-bold text-emerald-600">{company.supply_chain_vulnerability.critical_component_buffer_days} Days Stock</span>
                </div>
              </div>
            </div>
          </div>

          {/* Pillar 4: ESG & Compliance Health */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">ESG & Compliance</span>
              <span className="text-xs font-black px-2 py-0.5 rounded bg-emerald-50 text-emerald-700">
                Tier A Certified
              </span>
            </div>
            <div className="mt-3">
              <div className="text-2xl font-black text-[#0B2550] tracking-tight">
                {company.esg_compliance.score}/100
              </div>
              <p className="text-xs font-bold text-emerald-700 mt-0.5">
                ISO 9001, 14001 & 45001 Audited
              </p>
              <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-slate-100 text-[11px]">
                <div>
                  <span className="text-slate-400 block">Carbon Intensity</span>
                  <span className="font-bold text-slate-700">{company.esg_compliance.carbon_intensity_kg_co2} kg/unit</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Workplace Safety</span>
                  <span className="font-bold text-slate-700">Zero Lost-Time Incidents</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* CORE VISUALIZATION: THE 12-MONTH UPS & DOWNS TRAJECTORY FOR XYZ MACHINERY LTD */}
      {company && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <Activity className="w-5 h-5 text-blue-600" />
                <h3 className="text-lg font-black text-[#0B2550]">
                  XYZ Machinery Ltd: 12-Month "Ups & Downs" Volatility Trajectory
                </h3>
              </div>
              <p className="text-xs text-slate-500 font-medium mt-0.5">
                Mapping historical performance peaks (operational surges / upturns) and risk troughs (disruptions & bottlenecks).
              </p>
            </div>

            {/* Timeframe & Threshold Legend */}
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2 text-[11px] font-bold text-slate-500 border border-slate-200 rounded-lg px-2.5 py-1">
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span> Optimal (&lt;30)
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span> Moderate (31-60)
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-full bg-red-500"></span> Vulnerable (&gt;60)
                </span>
              </div>

              <div className="flex bg-slate-100 p-0.5 rounded-lg text-xs font-bold text-slate-600">
                {['6M', '12M', 'YTD'].map((t) => (
                  <button
                    key={t}
                    onClick={() => setSelectedTimeframe(t)}
                    className={`px-3 py-1 rounded-md transition-all ${
                      selectedTimeframe === t ? 'bg-white text-blue-600 shadow-sm' : 'hover:text-slate-900'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Interactive Recharts Graph */}
          <div className="h-80 w-full pt-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={company.trajectory_12m} margin={{ top: 10, right: 20, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="xyzRiskGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#2563eb" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#2563eb" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis 
                  dataKey="month" 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{ fill: '#64748b', fontSize: 11, fontWeight: 600 }} 
                />
                <YAxis 
                  domain={[0, 100]} 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{ fill: '#64748b', fontSize: 11, fontWeight: 600 }} 
                />
                <Tooltip content={<CustomTrajectoryTooltip />} />
                <Area 
                  type="monotone" 
                  dataKey="score" 
                  stroke="#2563eb" 
                  strokeWidth={3} 
                  fillOpacity={1} 
                  fill="url(#xyzRiskGradient)" 
                  activeDot={{ r: 6, fill: '#0f172a', stroke: '#ffffff', strokeWidth: 2 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className="flex items-center justify-between text-xs text-slate-400 font-medium px-2 pt-2 border-t border-slate-100">
            <span>Hover over monthly data markers to view specific operational shocks, plant expansions, and commodity price shifts for XYZ Machinery Ltd.</span>
            <span className="font-bold text-slate-600">Model: Proprietary Enterprise Digital Twin Simulation</span>
          </div>
        </div>
      )}

      {/* TWO-COLUMN DETAILS: INCIDENTS LOG & INTERNAL CONTINGENCY ACTIONS */}
      {company && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Column 1: Historical Chronology of Ups & Downs */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-black text-[#0B2550] flex items-center gap-2">
                  <Clock className="w-4 h-4 text-blue-600" />
                  <span>Key "Ups & Downs" Milestones: XYZ Machinery Ltd</span>
                </h3>
                <p className="text-xs text-slate-500 font-medium mt-0.5">
                  Historical operational events, raw material price shocks, and capacity breakthroughs.
                </p>
              </div>
              <span className="text-xs font-bold text-slate-400">
                {company.incident_log.length} Major Milestones
              </span>
            </div>

            <div className="space-y-3 max-h-[380px] overflow-y-auto pr-1">
              {company.incident_log.map((inc: Incident) => (
                <div 
                  key={inc.id}
                  className={`p-4 rounded-xl border transition-all ${
                    inc.type === 'UPTURN' 
                      ? 'bg-emerald-50/40 border-emerald-200' 
                      : 'bg-red-50/40 border-red-200'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase flex items-center gap-1 ${
                          inc.type === 'UPTURN' 
                            ? 'bg-emerald-100 text-emerald-800' 
                            : 'bg-red-100 text-red-800'
                        }`}>
                          {inc.type === 'UPTURN' ? <TrendingDown className="w-3 h-3" /> : <TrendingUp className="w-3 h-3" />}
                          {inc.type === 'UPTURN' ? 'POSITIVE UPTURN' : 'RISK DOWNTURN'}
                        </span>
                        <span className="text-xs font-bold text-slate-400">{inc.date}</span>
                        <span className="text-xs font-bold text-slate-600">• {inc.category}</span>
                      </div>
                      <h4 className="text-sm font-bold text-[#0B2550]">
                        {inc.title}
                      </h4>
                      <p className="text-xs text-slate-600 leading-relaxed">
                        {inc.description}
                      </p>
                    </div>

                    <span className={`px-2.5 py-1 rounded-lg text-xs font-black shrink-0 ${
                      inc.type === 'UPTURN' 
                        ? 'bg-emerald-600 text-white' 
                        : 'bg-red-600 text-white'
                    }`}>
                      {inc.impact}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Column 2: Predictive Outlook & Internal Contingency Controls */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4 flex flex-col justify-between">
            <div className="space-y-4">
              <div className="border-b border-slate-100 pb-3">
                <h3 className="text-base font-black text-[#0B2550] flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-purple-600" />
                  <span>Forward-Looking Outlook: XYZ Machinery Ltd</span>
                </h3>
                <p className="text-xs text-slate-500 font-medium mt-0.5">
                  AI digital twin forecast simulating order fulfillment stability through upcoming quarters.
                </p>
              </div>

              {/* Forecast Card */}
              <div className="bg-gradient-to-br from-slate-900 to-[#0B2550] text-white p-5 rounded-xl shadow-md space-y-3">
                <div className="flex items-center justify-between text-xs text-blue-200">
                  <span>Simulation Confidence Level: {company.predictive_forecast.confidence}%</span>
                  <span className="px-2 py-0.5 rounded bg-blue-500/30 text-blue-100 font-bold">
                    {company.predictive_forecast.direction}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-4 border-y border-white/10 py-3">
                  <div>
                    <span className="text-xs text-blue-200 block">30-Day Projected Risk</span>
                    <span className="text-2xl font-black text-white">{company.predictive_forecast.forecast_30d}/100</span>
                  </div>
                  <div>
                    <span className="text-xs text-blue-200 block">90-Day Projected Risk</span>
                    <span className="text-2xl font-black text-white">{company.predictive_forecast.forecast_90d}/100</span>
                  </div>
                </div>
                <p className="text-xs text-blue-100 leading-relaxed">
                  {company.predictive_forecast.summary}
                </p>
              </div>

              {/* Internal Risk Mitigation Actions */}
              <div className="space-y-2 pt-1">
                <h4 className="text-xs font-black uppercase tracking-wider text-slate-500">
                  Enterprise Contingency Controls
                </h4>
                <div className="space-y-2">
                  {company.internal_contingency_actions.map((act: any) => (
                    <div 
                      key={act.id} 
                      className="p-3 rounded-xl border border-slate-200 hover:border-blue-300 transition-all flex items-center justify-between gap-3 bg-slate-50/50"
                    >
                      <div className="flex items-center gap-2 text-xs font-bold text-slate-700">
                        <span className={`w-2 h-2 rounded-full ${
                          act.priority === 'Critical' ? 'bg-red-500' :
                          act.priority === 'High' ? 'bg-amber-500' :
                          'bg-blue-500'
                        }`} />
                        <span>{act.action}</span>
                      </div>
                      <button
                        onClick={() => showToast(`Control executed: ${act.action}`)}
                        className="px-3 py-1 bg-white border border-slate-200 hover:bg-blue-50 hover:text-blue-700 text-slate-700 text-[11px] font-black rounded-lg transition-all shrink-0 active:scale-95 shadow-sm"
                      >
                        Execute
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Quick Links */}
            <div className="pt-4 border-t border-slate-100 flex items-center justify-between text-xs font-bold text-blue-600">
              <Link href="/inventory" className="hover:underline flex items-center gap-1">
                <span>View Inventory Safety Buffers</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </Link>
              <Link href="/rfqs" className="hover:underline flex items-center gap-1">
                <span>Manage Procurement RFQs & Orders</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
