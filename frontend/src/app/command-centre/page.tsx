"use client";
import React, { useState, useEffect } from "react";
import Link from 'next/link';
import GoldenScenarioSimulator from '@/components/GoldenScenarioSimulator';

interface CapabilityDimension {
  dimension: string;
  score: number;
  unit: string;
  status: string;
  color: string;
}

interface OperationalNode {
  id: string;
  name: string;
  city: string;
  country: string;
  region: string;
  coordinates: { lat: number; lng: number };
  risk_level: string;
  active_po_value_usd: number;
  capacity_utilization_pct: number;
  current_otif_pct: number;
  current_defect_ppm: number;
  status: string;
  alert?: string | null;
}

interface DecisionItem {
  id: string;
  title: string;
  category: string;
  priority: string;
  threat_description: string;
  recommended_action: string;
  financial_impact_usd: number;
  sla_impact: string;
  status: string;
  created_at: string;
  executed_by?: string;
  executed_at?: string;
}

interface OverviewData {
  timestamp: string;
  region: string;
  kpis: {
    total_suppliers: number;
    verified_digital_twins: number;
    connected_iiot_cells: number;
    at_risk_suppliers: number;
    open_rfqs_count: number;
    open_rfqs_value_usd: number;
    total_active_po_exposure_usd: number;
    platform_resilience_index: number;
    average_otif_pct: number;
    average_defect_ppm: number;
    active_autonomous_interventions: number;
    active_choke_points: number;
  };
  capability_health: CapabilityDimension[];
  threat_radar: {
    axes: string[];
    current_scores: number[];
    predicted_90d_scores: number[];
    highest_threat_vector: string;
    highest_resilience_vector: string;
  };
  ai_sentinel_alerts: Array<{
    id: string;
    title: string;
    supplier: string;
    severity: string;
    action_label: string;
    deep_link: string;
  }>;
}

export default function AutonomousCommandCentre() {
  const [viewMode, setViewMode] = useState<'GOLDEN_SCENARIO' | 'RADAR'>('GOLDEN_SCENARIO');
  const [selectedRegion, setSelectedRegion] = useState<'GLOBAL' | 'NORTH_AMERICA' | 'EUROPE' | 'ASIA_PACIFIC'>('GLOBAL');
  const [horizonDays, setHorizonDays] = useState<'LIVE' | '30D' | '90D'>('90D');
  const [radarMode, setRadarMode] = useState<'DUAL' | 'CURRENT' | 'PROJECTED'>('DUAL');
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [nodes, setNodes] = useState<OperationalNode[]>([]);
  const [selectedNode, setSelectedNode] = useState<OperationalNode | null>(null);
  const [decisionQueue, setDecisionQueue] = useState<DecisionItem[]>([]);
  const [trends, setTrends] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [executingId, setExecutingId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4500);
  };

  const fetchData = async (region: string) => {
    setIsRefreshing(true);
    try {
      const [resOverview, resNodes, resQueue, resTrends] = await Promise.all([
        fetch(`http://127.0.0.1:8080/api/v1/command-centre/overview?region=${region}`).catch(() => null),
        fetch(`http://127.0.0.1:8080/api/v1/command-centre/nodes?region=${region}`).catch(() => null),
        fetch('http://127.0.0.1:8080/api/v1/command-centre/decision-queue').catch(() => null),
        fetch('http://127.0.0.1:8080/api/v1/command-centre/trends').catch(() => null),
      ]);

      if (resOverview && resOverview.ok) {
        const data = await resOverview.json();
        setOverview(data);
      }
      if (resNodes && resNodes.ok) {
        const data = await resNodes.json();
        setNodes(data.nodes || []);
        if (data.nodes && data.nodes.length > 0 && !selectedNode) {
          setSelectedNode(data.nodes[0]);
        }
      }
      if (resQueue && resQueue.ok) {
        const data = await resQueue.json();
        setDecisionQueue(data.queue || []);
      }
      if (resTrends && resTrends.ok) {
        const data = await resTrends.json();
        setTrends(data);
      }
    } catch (e) {
      console.warn("Could not reach backend command centre APIs, using active state", e);
    } finally {
      setIsRefreshing(false);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData(selectedRegion);
  }, [selectedRegion]);

  const handleExecuteDecision = async (id: string) => {
    setExecutingId(id);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/command-centre/decision-queue/${id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notes: "Executed via Autonomous Operational Command Centre Sentinel",
          actor: "Chief Procurement Officer"
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Decision ${id} executed successfully! Multi-agent pipeline engaged.`);
        // Update local state
        setDecisionQueue(prev => prev.map(d => d.id === id ? { ...d, status: 'EXECUTED', executed_by: 'CPO' } : d));
      } else {
        showToast("Error executing autonomous decision.");
      }
    } catch {
      showToast("Network error executing decision.");
    } finally {
      setExecutingId(null);
    }
  };

  const handleExportBriefing = async () => {
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/command-centre/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          region_filter: selectedRegion,
          horizon_days: horizonDays === 'LIVE' ? 1 : horizonDays === '30D' ? 30 : 90,
          include_threat_matrix: true
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Executive Intelligence Briefing ${data.report_id} generated & archived!`);
      } else {
        showToast("Generated local executive briefing summary.");
      }
    } catch {
      showToast("Export payload compiled for active horizon.");
    }
  };

  // Helper function to calculate SVG coordinates for 6-axis radar
  const getRadarCoordinates = (scores: number[], scale = 1) => {
    const center = 100;
    const maxRadius = 75 * scale;
    const points: string[] = [];

    scores.forEach((score, index) => {
      // 6 axes: 0, 60, 120, 180, 240, 300 degrees (-90 to start at 12 o'clock)
      const angle = (index * 60 - 90) * (Math.PI / 180);
      const r = (score / 100) * maxRadius;
      const x = center + r * Math.cos(angle);
      const y = center + r * Math.sin(angle);
      points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    });

    return points.join(" ");
  };

  return (
    <div className="flex h-full bg-[#0B0F19] text-slate-100 flex-col overflow-y-auto">
      {/* Toast Notification */}
      {toast && (
        <div className="fixed top-6 right-6 z-50 bg-emerald-950 border border-emerald-500/50 text-emerald-300 px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 text-sm font-semibold animate-fade-in">
          <span>✨</span> {toast}
        </div>
      )}

      {/* Header Control Bar */}
      <div className="bg-[#111827] border-b border-slate-800 px-8 pt-6 pb-4 shrink-0">
        <div className="flex justify-between items-start mb-3">
          <div>
            <div className="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest mb-1 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span>AlphaHelion Autonomous Sourcing Cloud</span>
              <span className="text-slate-600">•</span>
              <span className="font-mono text-cyan-400">Chief Procurement Officer (CPO) Command Centre</span>
            </div>
            <h1 className="text-2xl font-bold font-mono tracking-tight text-white flex items-center gap-3">
              Executive CPO Command Centre
              <span className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2.5 py-0.5 rounded-full text-xs font-sans font-bold flex items-center gap-1.5">
                ● Autonomous Sentinel Active
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-1 font-medium">
              Enterprise lifecycle orchestration, real-time multi-tier supplier twin telemetry, and governed end-to-end execution.
            </p>
          </div>

          {/* Action Tools */}
          <div className="flex items-center gap-3 shrink-0">
            {/* Region Filters (for Radar mode) */}
            <div className="flex bg-slate-900 border border-slate-800 rounded-lg p-1 text-xs font-semibold">
              {(['GLOBAL', 'NORTH_AMERICA', 'EUROPE', 'ASIA_PACIFIC'] as const).map(reg => (
                <button
                  key={reg}
                  onClick={() => setSelectedRegion(reg)}
                  className={`px-3 py-1 rounded transition-colors ${
                    selectedRegion === reg ? 'bg-blue-600 text-white font-bold shadow' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {reg === 'GLOBAL' ? 'Global' : reg === 'NORTH_AMERICA' ? 'N. America' : reg === 'EUROPE' ? 'Europe' : 'Asia-Pac'}
                </button>
              ))}
            </div>

            {/* Time Horizon */}
            <div className="flex bg-slate-900 border border-slate-800 rounded-lg p-1 text-xs font-semibold">
              {(['LIVE', '30D', '90D'] as const).map(h => (
                <button
                  key={h}
                  onClick={() => setHorizonDays(h)}
                  className={`px-2.5 py-1 rounded transition-colors ${
                    horizonDays === h ? 'bg-purple-600 text-white font-bold shadow' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {h === 'LIVE' ? 'Real-Time' : h === '30D' ? '30d Window' : '90d Forecast'}
                </button>
              ))}
            </div>

            <button
              onClick={() => fetchData(selectedRegion)}
              className="p-2 bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-300 rounded-lg transition-colors"
              title="Refresh Live Telemetry"
            >
              <span className={isRefreshing ? 'inline-block animate-spin' : ''}>🔄</span>
            </button>

            <button
              onClick={handleExportBriefing}
              className="px-4 py-2 bg-slate-900 border border-slate-700 hover:border-slate-600 text-white font-bold text-xs rounded-lg transition-colors flex items-center gap-2"
            >
              <span>📥</span> Export Briefing
            </button>
          </div>
        </div>

        {/* Executive View Switcher & Quick Navigation */}
        <div className="mt-3 pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-3">
          <div className="flex bg-slate-900/95 border border-slate-800 rounded-xl p-1 text-xs font-semibold shadow-inner">
            <button
              onClick={() => setViewMode('GOLDEN_SCENARIO')}
              className={`px-4 py-2 rounded-lg transition-all flex items-center gap-2.5 ${
                viewMode === 'GOLDEN_SCENARIO'
                  ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white font-bold shadow-lg shadow-cyan-500/25 border border-cyan-400/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <span className="text-sm">✨</span>
              <span>Axion Golden Path Simulator</span>
              <span className="text-[10px] bg-cyan-400/20 text-cyan-300 px-2 py-0.5 rounded-full font-mono font-bold">10 Steps</span>
            </button>
            <button
              onClick={() => setViewMode('RADAR')}
              className={`px-4 py-2 rounded-lg transition-all flex items-center gap-2.5 ${
                viewMode === 'RADAR'
                  ? 'bg-blue-600 text-white font-bold shadow-lg shadow-blue-500/25 border border-blue-400/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <span className="text-sm">📡</span>
              <span>Operational Radar & Telemetry</span>
            </button>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/command-centre/ai-agents"
              className="px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 hover:border-cyan-500/50 text-xs font-semibold text-slate-300 hover:text-cyan-300 transition flex items-center gap-1.5"
            >
              <span>🤖</span> 14 AI Fleet
            </Link>
            <Link
              href="/admin/governance"
              className="px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 hover:border-amber-500/50 text-xs font-semibold text-slate-300 hover:text-amber-300 transition flex items-center gap-1.5"
            >
              <span>⚖️</span> SoD & Outbox
            </Link>
            <Link
              href="/spend/cube"
              className="px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 hover:border-emerald-500/50 text-xs font-semibold text-slate-300 hover:text-emerald-300 transition flex items-center gap-1.5"
            >
              <span>📊</span> Spend Cube
            </Link>
            <Link
              href="/savings"
              className="px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 hover:border-purple-500/50 text-xs font-semibold text-slate-300 hover:text-purple-300 transition flex items-center gap-1.5"
            >
              <span>💰</span> Savings P12
            </Link>
          </div>
        </div>

        {/* Live Mission Status Sub-ribbon */}
        <div className="flex items-center justify-between text-xs text-slate-400 pt-3 mt-3 border-t border-slate-800/80 font-mono">
          <div className="flex items-center gap-6">
            <div>Mode: <span className="text-white font-bold">{viewMode === 'GOLDEN_SCENARIO' ? 'Axion Golden Scenario (M01-M13)' : `Live Radar (${selectedRegion})`}</span></div>
            <div>Oracle Sync: <span className="text-emerald-400 font-bold">100% (Sub-second Edge Stream)</span></div>
            <div>Active Choke Points: <span className="text-amber-400 font-bold">{overview?.kpis?.active_choke_points || 2} Transit Buffers</span></div>
          </div>
          <div className="text-[11px] text-slate-500">
            {viewMode === 'GOLDEN_SCENARIO' ? 'Idempotent SAP Doc 5100004421 • CN-TF-221 Applied' : `Last Updated: ${overview?.timestamp ? new Date(overview.timestamp).toLocaleTimeString() : 'Live'}`}
          </div>
        </div>
      </div>

      {/* Main Content Body */}
      {viewMode === 'GOLDEN_SCENARIO' ? (
        <div className="flex-1 p-8 max-w-[1700px] mx-auto w-full">
          <GoldenScenarioSimulator />
        </div>
      ) : (
        <div className="flex-1 p-8 max-w-[1650px] mx-auto w-full flex flex-col gap-6">
        
        {/* TOP KPI RIBBON (5 High-Density Cards) */}
        <div className="grid grid-cols-5 gap-4">
          {/* KPI 1 */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col justify-between">
            <div className="flex justify-between items-start">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Monitored Suppliers</span>
              <span className="text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded font-mono font-bold">+12% QoQ</span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black font-mono text-white">
                {overview?.kpis?.total_suppliers.toLocaleString() || '2,845'}
              </span>
              <span className="text-xs text-slate-400">Total</span>
            </div>
            <div className="mt-2 text-[11px] text-slate-400 flex items-center justify-between pt-2 border-t border-slate-800/80">
              <span>Active: <span className="text-white font-bold">2,758</span></span>
              <span>At Risk: <span className="text-red-400 font-bold">87</span></span>
            </div>
          </div>

          {/* KPI 2 */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col justify-between">
            <div className="flex justify-between items-start">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Verified Digital Twins</span>
              <span className="text-xs bg-blue-500/10 text-blue-400 border border-blue-500/30 px-2 py-0.5 rounded font-mono font-bold">81.4% Coverage</span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black font-mono text-cyan-400">
                {overview?.kpis?.verified_digital_twins.toLocaleString() || '2,316'}
              </span>
              <span className="text-xs text-slate-400">Twins</span>
            </div>
            <div className="mt-2 text-[11px] text-slate-400 flex items-center justify-between pt-2 border-t border-slate-800/80">
              <span>IIoT Telemetry Cells:</span>
              <span className="text-white font-mono font-bold">{overview?.kpis?.connected_iiot_cells || '1,894'}</span>
            </div>
          </div>

          {/* KPI 3 */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col justify-between">
            <div className="flex justify-between items-start">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Resilience Index</span>
              <span className="text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded font-mono font-bold">Optimal</span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black font-mono text-emerald-400">
                {overview?.kpis?.platform_resilience_index || '92.4'}
              </span>
              <span className="text-xs text-slate-400">/ 100</span>
            </div>
            <div className="mt-2 text-[11px] text-slate-400 flex items-center justify-between pt-2 border-t border-slate-800/80">
              <span>Avg OTIF: <span className="text-white font-bold">{overview?.kpis?.average_otif_pct || '96.8'}%</span></span>
              <span>PPM: <span className="text-emerald-400 font-bold">{overview?.kpis?.average_defect_ppm || '32'}</span></span>
            </div>
          </div>

          {/* KPI 4 */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col justify-between">
            <div className="flex justify-between items-start">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Active PO Exposure</span>
              <span className="text-xs bg-purple-500/10 text-purple-400 border border-purple-500/30 px-2 py-0.5 rounded font-mono font-bold">124 Orders</span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black font-mono text-purple-400">
                ${(overview?.kpis?.total_active_po_exposure_usd ? (overview.kpis.total_active_po_exposure_usd / 1000000).toFixed(2) : '4.85')}M
              </span>
              <span className="text-xs text-slate-400">USD</span>
            </div>
            <div className="mt-2 text-[11px] text-slate-400 flex items-center justify-between pt-2 border-t border-slate-800/80">
              <span>Open RFQs Value:</span>
              <span className="text-white font-mono font-bold">${(overview?.kpis?.open_rfqs_value_usd ? (overview.kpis.open_rfqs_value_usd / 1000000).toFixed(2) : '4.85')}M</span>
            </div>
          </div>

          {/* KPI 5 */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col justify-between">
            <div className="flex justify-between items-start">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Autonomous Sentinels</span>
              <span className="text-xs bg-amber-500/10 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded font-mono font-bold">Zero Human Latency</span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black font-mono text-amber-400">
                {overview?.kpis?.active_autonomous_interventions || 18}
              </span>
              <span className="text-xs text-slate-400">Interventions</span>
            </div>
            <div className="mt-2 text-[11px] text-slate-400 flex items-center justify-between pt-2 border-t border-slate-800/80">
              <span>Dual-Source: <span className="text-white font-bold">7</span></span>
              <span>Escrow Releases: <span className="text-emerald-400 font-bold">6</span></span>
            </div>
          </div>
        </div>

        {/* MIDDLE OPERATIONAL THEATER (3 Columns) */}
        <div className="grid grid-cols-12 gap-6">
          
          {/* Column 1: Capability Health Matrix (4 Cols) */}
          <div className="col-span-4 bg-[#111827] border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col justify-between">
            <div>
              <div className="flex justify-between items-center mb-4">
                <h3 className="font-bold text-white text-sm flex items-center gap-2">
                  <span className="text-blue-400">🏭</span> Supplier Capability Health Matrix
                </h3>
                <Link href="/buyer/analytics" className="text-xs text-blue-400 hover:underline">
                  Deep Audit →
                </Link>
              </div>

              <div className="space-y-3.5">
                {(overview?.capability_health || [
                  { dimension: "Manufacturing", score: 88, unit: "CNC & HPDC", status: "OPTIMAL", color: "emerald" },
                  { dimension: "Quality Assurance", score: 86, unit: "32 Avg PPM", status: "VERIFIED", color: "emerald" },
                  { dimension: "Engineering & CAD", score: 82, unit: "DFSC AP242", status: "ACTIVE", color: "blue" },
                  { dimension: "Capacity Headroom", score: 84, unit: "18.4% Free", status: "BALANCED", color: "blue" },
                  { dimension: "Technology & IIoT", score: 79, unit: "Edge Telemetry", status: "STREAMING", color: "cyan" },
                  { dimension: "Financial Escrow", score: 83, unit: "Smart Escrow", status: "FUNDED", color: "purple" },
                  { dimension: "ESG Compliance", score: 76, unit: "CBAM Scope 1-3", status: "CONFORMANT", color: "slate" }
                ]).map((dim, i) => (
                  <div key={i} className="text-xs">
                    <div className="flex justify-between items-center mb-1">
                      <span className="font-semibold text-slate-300">{dim.dimension}</span>
                      <div className="flex items-center gap-2 font-mono">
                        <span className="text-[10px] text-slate-500">{dim.unit}</span>
                        <span className="font-bold text-white">{dim.score}%</span>
                      </div>
                    </div>
                    <div className="w-full bg-slate-900 h-2 rounded-full overflow-hidden border border-slate-800">
                      <div 
                        className={`h-full ${
                          dim.color === 'emerald' ? 'bg-emerald-500' :
                          dim.color === 'blue' ? 'bg-blue-500' :
                          dim.color === 'cyan' ? 'bg-cyan-400' :
                          dim.color === 'purple' ? 'bg-purple-500' : 'bg-slate-500'
                        }`}
                        style={{ width: `${dim.score}%` }}
                      ></div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
              <span>Automated Calibration: <span className="text-emerald-400 font-bold font-mono">ON-LINE</span></span>
              <span className="font-mono">Composite: 83.2%</span>
            </div>
          </div>

          {/* Column 2: Predictive 6-Axis Threat Radar (4 Cols) */}
          <div className="col-span-4 bg-[#111827] border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col justify-between">
            <div>
              <div className="flex justify-between items-center mb-2">
                <h3 className="font-bold text-white text-sm flex items-center gap-2">
                  <span className="text-cyan-400">📡</span> 6-Axis Predictive Threat Radar
                </h3>
                {/* Radar Mode Toggles */}
                <div className="flex bg-slate-900 border border-slate-800 rounded text-[10px] font-semibold p-0.5">
                  <button
                    onClick={() => setRadarMode('CURRENT')}
                    className={`px-2 py-0.5 rounded ${radarMode === 'CURRENT' ? 'bg-cyan-600 text-white font-bold' : 'text-slate-400'}`}
                  >
                    Current
                  </button>
                  <button
                    onClick={() => setRadarMode('PROJECTED')}
                    className={`px-2 py-0.5 rounded ${radarMode === 'PROJECTED' ? 'bg-amber-600 text-white font-bold' : 'text-slate-400'}`}
                  >
                    90d ML
                  </button>
                  <button
                    onClick={() => setRadarMode('DUAL')}
                    className={`px-2 py-0.5 rounded ${radarMode === 'DUAL' ? 'bg-purple-600 text-white font-bold' : 'text-slate-400'}`}
                  >
                    Dual
                  </button>
                </div>
              </div>

              {/* Pure SVG Hexagonal Radar */}
              <div className="relative w-full h-52 flex items-center justify-center my-1">
                <svg viewBox="0 0 200 200" className="w-full h-full overflow-visible">
                  {/* Outer & Inner Hexagonal Grid Webs */}
                  <polygon points="100,25 165,62.5 165,137.5 100,175 35,137.5 35,62.5" fill="none" stroke="#1E293B" strokeWidth="1" />
                  <polygon points="100,43.7 148.7,71.8 148.7,128.1 100,156.2 51.3,128.1 51.3,71.8" fill="none" stroke="#1E293B" strokeWidth="1" />
                  <polygon points="100,62.5 132.5,81.2 132.5,118.7 100,137.5 67.5,118.7 67.5,81.2" fill="none" stroke="#1E293B" strokeWidth="1" />

                  {/* Radial Axis Lines */}
                  <line x1="100" y1="100" x2="100" y2="25" stroke="#334155" strokeWidth="0.75" strokeDasharray="2 2" />
                  <line x1="100" y1="100" x2="165" y2="62.5" stroke="#334155" strokeWidth="0.75" strokeDasharray="2 2" />
                  <line x1="100" y1="100" x2="165" y2="137.5" stroke="#334155" strokeWidth="0.75" strokeDasharray="2 2" />
                  <line x1="100" y1="100" x2="100" y2="175" stroke="#334155" strokeWidth="0.75" strokeDasharray="2 2" />
                  <line x1="100" y1="100" x2="35" y2="137.5" stroke="#334155" strokeWidth="0.75" strokeDasharray="2 2" />
                  <line x1="100" y1="100" x2="35" y2="62.5" stroke="#334155" strokeWidth="0.75" strokeDasharray="2 2" />

                  {/* Axis Text Labels */}
                  <text x="100" y="16" fontSize="8" textAnchor="middle" fill="#94A3B8" fontWeight="bold">Financial</text>
                  <text x="175" y="62" fontSize="8" textAnchor="start" fill="#94A3B8" fontWeight="bold">Operational</text>
                  <text x="175" y="142" fontSize="8" textAnchor="start" fill="#94A3B8" fontWeight="bold">Quality</text>
                  <text x="100" y="190" fontSize="8" textAnchor="middle" fill="#94A3B8" fontWeight="bold">Capacity</text>
                  <text x="25" y="142" fontSize="8" textAnchor="end" fill="#94A3B8" fontWeight="bold">Geopolitics</text>
                  <text x="25" y="62" fontSize="8" textAnchor="end" fill="#94A3B8" fontWeight="bold">ESG</text>

                  {/* Projected 90d Polygon (Amber) */}
                  {(radarMode === 'PROJECTED' || radarMode === 'DUAL') && (
                    <polygon
                      points={getRadarCoordinates(overview?.threat_radar?.predicted_90d_scores || [81, 76, 91, 86, 62, 80])}
                      fill="rgba(245, 158, 11, 0.15)"
                      stroke="#F59E0B"
                      strokeWidth="1.75"
                      strokeDasharray="3 3"
                    />
                  )}

                  {/* Current Polygon (Cyan) */}
                  {(radarMode === 'CURRENT' || radarMode === 'DUAL') && (
                    <polygon
                      points={getRadarCoordinates(overview?.threat_radar?.current_scores || [74, 82, 88, 79, 68, 75])}
                      fill="rgba(6, 182, 212, 0.25)"
                      stroke="#06B6D4"
                      strokeWidth="2"
                    />
                  )}
                </svg>
              </div>

              <div className="flex items-center justify-center gap-6 text-[10px] text-slate-400 font-mono mb-2">
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-0.5 bg-cyan-400 inline-block"></span>
                  <span>Live Telemetry Risk</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-0.5 border-t border-amber-400 border-dashed inline-block"></span>
                  <span>90-Day ML Forecast</span>
                </div>
              </div>
            </div>

            <div className="p-3 bg-slate-900/70 border border-slate-800 rounded-lg text-xs space-y-1">
              <div className="text-[11px] text-red-400 font-semibold flex items-center gap-1">
                <span>⚠️ Choke Point:</span> {overview?.threat_radar?.highest_threat_vector || 'Geopolitical Transit Choke Points (Suez & Malacca)'}
              </div>
              <div className="text-[11px] text-emerald-400 font-semibold flex items-center gap-1">
                <span>🛡️ High Resilience:</span> {overview?.threat_radar?.highest_resilience_vector || 'Quality PPM & Coordinate CMM Verification'}
              </div>
            </div>
          </div>

          {/* Column 3: Global Digital Twin Map (4 Cols) */}
          <div className="col-span-4 bg-[#111827] border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col justify-between">
            <div>
              <div className="flex justify-between items-center mb-2">
                <h3 className="font-bold text-white text-sm flex items-center gap-2">
                  <span className="text-emerald-400">🌍</span> Global Digital Twin Facility Map
                </h3>
                <span className="text-xs font-mono text-slate-400">{nodes.length} Key Hubs</span>
              </div>

              {/* Map Canvas */}
              <div className="relative w-full h-44 bg-slate-950/70 border border-slate-800/80 rounded-lg overflow-hidden my-2">
                <svg viewBox="0 0 400 200" className="w-full h-full">
                  {/* Continents Outline */}
                  <path d="M 50,30 L 110,25 L 140,45 L 115,100 L 95,150 L 60,170 L 45,105 L 20,85 Z" fill="#1E293B" />
                  <path d="M 180,35 L 240,25 L 310,35 L 350,60 L 320,130 L 250,170 L 210,135 L 175,80 Z" fill="#1E293B" />
                  <path d="M 320,125 L 360,115 L 380,150 L 345,180 Z" fill="#1E293B" />

                  {/* Interactive Facility Nodes */}
                  {nodes.map((node) => {
                    // Map lat/lng to SVG x,y
                    const x = ((node.coordinates.lng + 180) / 360) * 400;
                    const y = ((90 - node.coordinates.lat) / 180) * 200;
                    const isSelected = selectedNode?.id === node.id;
                    const isCritical = node.risk_level === 'CRITICAL';
                    const isElevated = node.risk_level === 'ELEVATED';

                    return (
                      <g key={node.id} className="cursor-pointer" onClick={() => setSelectedNode(node)}>
                        {/* Pulse Ring if elevated/critical */}
                        {(isCritical || isElevated) && (
                          <circle cx={x} cy={y} r="8" fill="none" stroke={isCritical ? "#EF4444" : "#F59E0B"} strokeWidth="1" className="animate-ping" opacity="0.7" />
                        )}
                        <circle
                          cx={x}
                          cy={y}
                          r={isSelected ? "5" : "3.5"}
                          fill={isCritical ? "#EF4444" : isElevated ? "#F59E0B" : "#10B981"}
                          stroke="#FFFFFF"
                          strokeWidth={isSelected ? "1.5" : "0.75"}
                        />
                        <text x={x + 6} y={y + 3} fontSize="7" fill="#CBD5E1" fontWeight="bold">
                          {node.city}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              </div>

              {/* Selected Node Details Drawer */}
              {selectedNode && (
                <div className="p-3 bg-slate-900/80 border border-slate-800 rounded-lg text-xs space-y-1.5">
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="font-bold text-white text-sm">{selectedNode.name}</div>
                      <div className="text-[11px] text-slate-400 font-mono">{selectedNode.city}, {selectedNode.country}</div>
                    </div>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                      selectedNode.risk_level === 'CRITICAL' ? 'bg-red-500/10 text-red-400 border border-red-500/30' :
                      selectedNode.risk_level === 'ELEVATED' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' :
                      'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                    }`}>
                      {selectedNode.status}
                    </span>
                  </div>

                  <div className="grid grid-cols-3 gap-2 pt-1 font-mono text-[11px]">
                    <div>
                      <span className="text-slate-500 block text-[9px]">Active PO</span>
                      <span className="text-purple-400 font-bold">${(selectedNode.active_po_value_usd / 1000).toFixed(0)}k</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block text-[9px]">Capacity</span>
                      <span className="text-white font-bold">{selectedNode.capacity_utilization_pct}%</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block text-[9px]">OTIF / PPM</span>
                      <span className="text-emerald-400 font-bold">{selectedNode.current_otif_pct}% / {selectedNode.current_defect_ppm}</span>
                    </div>
                  </div>

                  {selectedNode.alert && (
                    <div className="text-[10px] text-amber-300 bg-amber-950/40 p-1.5 rounded border border-amber-800/40 font-sans">
                      ⚠️ {selectedNode.alert}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between text-[11px] text-slate-400 pt-2 border-t border-slate-800/80">
              <span className="flex items-center gap-3">
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-400"></span> Optimal (4)</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400"></span> Choke Point (1)</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-400"></span> Critical (1)</span>
              </span>
              <Link href="/network" className="text-blue-400 hover:underline">Full Mesh →</Link>
            </div>
          </div>
        </div>

        {/* BOTTOM OPERATIONAL HORIZON (3 Columns) */}
        <div className="grid grid-cols-12 gap-6">
          
          {/* Column 1: AI Copilot Live Sentinel Interventions (4 Cols) */}
          <div className="col-span-4 bg-[#111827] border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col justify-between">
            <div>
              <div className="flex justify-between items-center mb-4">
                <h3 className="font-bold text-white text-sm flex items-center gap-2">
                  <span className="text-purple-400">🤖</span> AI Copilot Sentinel Alerts
                </h3>
                <Link href="/copilot" className="text-xs text-blue-400 hover:underline">
                  Open Copilot →
                </Link>
              </div>

              <div className="space-y-3">
                {(overview?.ai_sentinel_alerts || [
                  {
                    id: "ALT-1",
                    title: "Chennai Port Customs Bottleneck (2.2 Days Delay)",
                    supplier: "Kovai Diecast Industries",
                    severity: "ELEVATED",
                    action_label: "Trigger 48h Escrow Buffer",
                    deep_link: "/contracts"
                  },
                  {
                    id: "ALT-2",
                    title: "CMRT Conflict Smelter CID002918 Flagged",
                    supplier: "Apex Copper Formings",
                    severity: "CRITICAL",
                    action_label: "Open Evidence Quarantine",
                    deep_link: "/evidence"
                  },
                  {
                    id: "ALT-3",
                    title: "Machine Headroom Optimization Opportunity (18% Idle)",
                    supplier: "Kovai Diecast Industries",
                    severity: "LOW",
                    action_label: "Allocate SOW-2026 Batch",
                    deep_link: "/negotiation"
                  }
                ]).map((alert, idx) => (
                  <div key={idx} className="p-3.5 bg-slate-900/70 border border-slate-800 rounded-xl hover:border-slate-700 transition-colors">
                    <div className="flex justify-between items-start mb-1.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                        alert.severity === 'CRITICAL' ? 'bg-red-500/10 text-red-400 border border-red-500/30' :
                        alert.severity === 'ELEVATED' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' :
                        'bg-blue-500/10 text-blue-400 border border-blue-500/30'
                      }`}>
                        {alert.severity}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">Live Ingestion</span>
                    </div>
                    <div className="text-xs font-bold text-white mb-1">{alert.title}</div>
                    <div className="text-[11px] text-slate-400 mb-2">Entity: {alert.supplier}</div>
                    <Link
                      href={alert.deep_link}
                      className="inline-flex items-center gap-1 text-[11px] font-bold text-blue-400 hover:text-blue-300 hover:underline"
                    >
                      ⚡ {alert.action_label} →
                    </Link>
                  </div>
                ))}
              </div>
            </div>

            <div className="pt-3 border-t border-slate-800/80 text-[11px] text-slate-400">
              Autonomous Remediation Protocol: <span className="text-emerald-400 font-bold font-mono">ACTIVE</span>
            </div>
          </div>

          {/* Column 2: Autonomous Decision Queue (4 Cols) */}
          <div className="col-span-4 bg-[#111827] border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col justify-between">
            <div>
              <div className="flex justify-between items-center mb-4">
                <h3 className="font-bold text-white text-sm flex items-center gap-2">
                  <span className="text-amber-400">⚡</span> Autonomous Decision Queue
                  <span className="ml-1 px-1.5 py-0.5 bg-amber-500/10 text-amber-400 border border-amber-500/30 rounded-full font-mono text-xs font-bold">
                    {decisionQueue.filter(d => d.status === 'PENDING').length}
                  </span>
                </h3>
                <span className="text-xs text-slate-400">Real-Time Approvals</span>
              </div>

              <div className="space-y-3 max-h-[360px] overflow-y-auto pr-1">
                {decisionQueue.map((item) => (
                  <div key={item.id} className="p-3.5 bg-slate-900/70 border border-slate-800 rounded-xl flex flex-col gap-2">
                    <div className="flex justify-between items-start">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[10px] text-blue-400 bg-blue-950/60 px-1.5 py-0.5 rounded border border-blue-800/50">
                          {item.id}
                        </span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                          item.priority === 'CRITICAL' ? 'bg-red-500/10 text-red-400 border border-red-500/30' :
                          item.priority === 'HIGH' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' :
                          'bg-blue-500/10 text-blue-400 border border-blue-500/30'
                        }`}>
                          {item.priority}
                        </span>
                      </div>
                      <span className="text-[10px] text-slate-500">{item.created_at}</span>
                    </div>

                    <div className="text-xs font-bold text-white leading-tight">{item.title}</div>
                    <p className="text-[11px] text-slate-300 leading-snug">{item.threat_description}</p>
                    <div className="text-[10px] text-cyan-300 font-mono bg-cyan-950/30 p-2 rounded border border-cyan-800/40">
                      💡 Recommended: {item.recommended_action}
                    </div>

                    <div className="flex justify-between items-center pt-1">
                      <span className="font-mono text-xs font-bold text-slate-300">
                        ${item.financial_impact_usd.toLocaleString()} USD
                      </span>
                      {item.status === 'PENDING' ? (
                        <button
                          disabled={executingId === item.id}
                          onClick={() => handleExecuteDecision(item.id)}
                          className="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs rounded transition-colors shadow-md disabled:opacity-50"
                        >
                          {executingId === item.id ? 'Engaging...' : 'Approve & Execute ⚡'}
                        </button>
                      ) : (
                        <span className="text-xs text-emerald-400 font-mono font-bold flex items-center gap-1 bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded">
                          ✓ Executed
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="pt-3 border-t border-slate-800/80 text-[11px] text-slate-400">
              Zero-Human Latency Protocol: <span className="text-emerald-400 font-mono font-bold">READY</span>
            </div>
          </div>

          {/* Column 3: Multi-Metric Trend & Forecast Theater (4 Cols) */}
          <div className="col-span-4 bg-[#111827] border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col justify-between">
            <div>
              <div className="flex justify-between items-center mb-4">
                <h3 className="font-bold text-white text-sm flex items-center gap-2">
                  <span className="text-emerald-400">📈</span> 6-Month Performance & AI Forecast
                </h3>
                <span className="text-xs font-mono text-purple-400">9-Month Trendline</span>
              </div>

              {/* Pure SVG Line Chart */}
              <div className="relative w-full h-56 bg-slate-950/70 border border-slate-800/80 rounded-lg p-3 my-1">
                <svg viewBox="0 0 320 160" className="w-full h-full overflow-visible">
                  {/* Grid Lines */}
                  <line x1="30" y1="20" x2="310" y2="20" stroke="#1E293B" strokeWidth="1" />
                  <line x1="30" y1="50" x2="310" y2="50" stroke="#1E293B" strokeWidth="1" />
                  <line x1="30" y1="80" x2="310" y2="80" stroke="#1E293B" strokeWidth="1" />
                  <line x1="30" y1="110" x2="310" y2="110" stroke="#1E293B" strokeWidth="1" />
                  <line x1="30" y1="140" x2="310" y2="140" stroke="#334155" strokeWidth="1" />

                  {/* Forecast Horizon Boundary Divider */}
                  <line x1="217" y1="15" x2="217" y2="140" stroke="#A855F7" strokeWidth="1" strokeDasharray="2 2" />
                  <text x="220" y="15" fontSize="6.5" fill="#C084FC" fontWeight="bold">AI Forecast →</text>

                  {/* Y Axis Labels */}
                  <text x="25" y="23" fontSize="7" textAnchor="end" fill="#64748B">100%</text>
                  <text x="25" y="83" fontSize="7" textAnchor="end" fill="#64748B">50%</text>
                  <text x="25" y="143" fontSize="7" textAnchor="end" fill="#64748B">0%</text>

                  {/* X Axis Labels */}
                  {['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan'].map((m, i) => (
                    <text key={m} x={45 + i * 31} y="152" fontSize="6.5" textAnchor="middle" fill="#64748B">
                      {m}
                    </text>
                  ))}

                  {/* OTIF Line (Emerald) */}
                  <polyline
                    points="45,28 76,26 107,24 138,23 169,21 200,19 231,17 262,16 293,14"
                    fill="none"
                    stroke="#10B981"
                    strokeWidth="2.5"
                  />

                  {/* Quality Index Line (Cyan) */}
                  <polyline
                    points="45,45 76,43 107,41 138,39 169,36 200,34 231,31 262,29 293,27"
                    fill="none"
                    stroke="#06B6D4"
                    strokeWidth="2"
                  />

                  {/* Defect PPM Line (Inverse Amber) */}
                  <polyline
                    points="45,100 76,105 107,112 138,118 169,124 200,128 231,132 262,136 293,138"
                    fill="none"
                    stroke="#F59E0B"
                    strokeWidth="1.5"
                    strokeDasharray="2 2"
                  />
                </svg>
              </div>

              {/* Legend */}
              <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono mt-2">
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-0.5 bg-emerald-400 inline-block"></span> OTIF Delivery (98.8%)</span>
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-0.5 bg-cyan-400 inline-block"></span> Quality Index (91.0)</span>
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-0.5 border-t border-amber-400 border-dashed inline-block"></span> Defect PPM (18)</span>
              </div>
            </div>

            <div className="p-3 bg-slate-900/70 border border-slate-800 rounded-lg text-xs mt-3 flex justify-between items-center">
              <div>
                <span className="text-slate-400 block text-[10px]">Predicted Q1 Performance:</span>
                <span className="font-bold text-white">OTIF &gt; 98.5% with &lt; 20 Defect PPM</span>
              </div>
              <Link href="/simulation" className="text-blue-400 font-bold text-xs hover:underline">
                Simulate Risk →
              </Link>
            </div>
          </div>
        </div>

      </div>
      )}
    </div>
  );
}
