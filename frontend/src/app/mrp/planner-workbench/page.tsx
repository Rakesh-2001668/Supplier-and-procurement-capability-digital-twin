'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Layers, CheckCircle2, AlertTriangle, ArrowRight, 
  Search, RefreshCw, Calendar, Clock, Box, ShieldCheck, 
  Sparkles, Filter, ChevronRight, Play, Sliders, CheckCheck,
  TrendingUp, ArrowDownRight, Factory, FileText, Zap
} from 'lucide-react';
import axios from 'axios';

interface MRPRun {
  id: string;
  tenant_id: string;
  plant: string;
  run_type: string;
  status: string;
  executed_at: string;
  horizon_days: number;
  stats: {
    materials_evaluated: number;
    planned_orders_generated: number;
    shortage_exceptions: number;
    total_planned_value_cr: number;
  };
}

interface PlannedOrder {
  id: string;
  mrp_run_id: string;
  plant: string;
  material_id: string;
  material_description: string;
  bom_level: number;
  parent_assembly: string;
  gross_requirement: number;
  stock_on_hand: number;
  scheduled_receipts: number;
  safety_stock: number;
  net_requirement: number;
  planned_quantity: number;
  uom: string;
  order_type: string;
  lead_time_days: number;
  start_date: string;
  finish_date: string;
  is_firmed: boolean;
  status: string;
  converted_pr_id?: string;
  created_at: string;
}

export default function MRPPlannerWorkbenchPage() {
  const [runs, setRuns] = useState<MRPRun[]>([]);
  const [plannedOrders, setPlannedOrders] = useState<PlannedOrder[]>([]);
  const [selectedPlant, setSelectedPlant] = useState<string>('All');
  const [loading, setLoading] = useState(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Trigger MRP Run Modal State
  const [showRunModal, setShowRunModal] = useState(false);
  const [triggerPlant, setTriggerPlant] = useState('P100 Hosur');
  const [horizonDays, setHorizonDays] = useState(90);
  const [triggering, setTriggering] = useState(false);

  // Convert Planned Order Modal State
  const [showConvertModal, setShowConvertModal] = useState(false);
  const [selectedPLO, setSelectedPLO] = useState<PlannedOrder | null>(null);
  const [convertQty, setConvertQty] = useState<number>(0);
  const [converting, setConverting] = useState(false);

  const fetchMRPData = async () => {
    setLoading(true);
    try {
      const [runsRes, ordersRes] = await Promise.all([
        axios.get('http://localhost:8080/api/v1/planning/mrp/runs'),
        axios.get('http://localhost:8080/api/v1/planning/mrp/planned-orders')
      ]);

      if (runsRes.data && runsRes.data.status === 'success') {
        setRuns(runsRes.data.runs || []);
      }
      if (ordersRes.data && ordersRes.data.status === 'success') {
        setPlannedOrders(ordersRes.data.planned_orders || []);
      }
    } catch (err) {
      console.error('Failed to load MRP data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMRPData();
  }, []);

  const handleTriggerRun = async () => {
    setTriggering(true);
    try {
      const res = await axios.post('http://localhost:8080/api/v1/planning/mrp/runs/trigger', {
        plant: triggerPlant,
        run_type: 'NET_CHANGE',
        horizon_days: horizonDays,
        lot_sizing_rule: 'EXACT_REQUIREMENT',
        actor: 'u:planner.hosur'
      });

      if (res.data && res.data.status === 'success') {
        setToastMessage(`MRP Net-Change Run ${res.data.run.id} completed. Generated ${res.data.generated_orders?.length || 1} orders.`);
        setShowRunModal(false);
        fetchMRPData();
      }
    } catch (err: any) {
      console.error('Error triggering MRP:', err);
      setToastMessage(err.response?.data?.detail || 'Failed to execute MRP run');
    } finally {
      setTriggering(false);
    }
  };

  const handleFirmOrder = async (orderId: string) => {
    try {
      const res = await axios.post(`http://localhost:8080/api/v1/planning/mrp/planned-orders/${orderId}/firm?actor=u:planner.hosur`);
      if (res.data && res.data.status === 'success') {
        setToastMessage(`Planned Order ${orderId} firmed.`);
        fetchMRPData();
      }
    } catch (err) {
      console.error('Firming error:', err);
    }
  };

  const handleConvertOrder = async () => {
    if (!selectedPLO) return;
    setConverting(true);
    try {
      const res = await axios.post(
        `http://localhost:8080/api/v1/planning/mrp/planned-orders/${selectedPLO.id}/convert-to-pr`,
        {
          firmed_quantity: convertQty,
          actor: 'u:planner.hosur'
        }
      );

      if (res.data && res.data.status === 'success') {
        setToastMessage(`Planned Order ${selectedPLO.id} converted to Requisition ${res.data.requisition_id}. Lineage recorded (Principle P10).`);
        setShowConvertModal(false);
        fetchMRPData();
      }
    } catch (err: any) {
      console.error('Conversion error:', err);
      setToastMessage(err.response?.data?.detail || 'Failed to convert planned order');
    } finally {
      setConverting(false);
    }
  };

  const filteredOrders = plannedOrders.filter(
    o => selectedPlant === 'All' || o.plant.toLowerCase().includes(selectedPlant.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 space-y-6">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="p-4 rounded-xl bg-cyan-950/80 border border-cyan-500/50 text-cyan-200 flex items-center justify-between shadow-xl shadow-cyan-950/30 animate-in fade-in duration-200">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-cyan-400" />
            <span className="font-medium text-sm">{toastMessage}</span>
          </div>
          <button 
            onClick={() => setToastMessage(null)} 
            className="text-xs px-2.5 py-1 rounded-md bg-cyan-900/60 hover:bg-cyan-800 text-cyan-300"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold tracking-wider uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              Module M02 • MRP-01..04
            </span>
            <span className="text-xs text-slate-400 font-mono">Governed Demand Planning</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Material Requirements Planning (MRP) Workbench
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Net-change netting engine: Gross Demand - Stock on Hand - Scheduled Receipts + Safety Stock = Net Requirement.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchMRPData}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-xs font-medium text-slate-200 border border-slate-700/60 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button 
            onClick={() => setShowRunModal(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-xs font-semibold text-white shadow-lg shadow-blue-600/20 transition"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            Trigger Net-Change Run
          </button>
          <Link
            href="/p2p"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 text-xs font-semibold text-white shadow-lg shadow-cyan-600/20 transition"
          >
            <Box className="w-3.5 h-3.5" />
            P2P Requisitions
          </Link>
        </div>
      </div>

      {/* Signature Case Banner */}
      <div className="p-4 rounded-xl bg-gradient-to-r from-blue-950/40 via-slate-900/60 to-slate-900/40 border border-blue-500/30 flex items-start gap-3.5">
        <Layers className="w-5 h-5 text-cyan-400 mt-0.5 shrink-0" />
        <div className="space-y-1 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-bold text-white">Axion Mobility Systems Golden Path:</span>
            <span className="font-mono text-cyan-300 font-bold">MR-1043 &rarr; PLO-55821 &rarr; REQ-2311</span>
          </div>
          <p className="text-slate-300 leading-relaxed">
            Finished motor production requires <strong>12,000 units</strong> of <strong>MAT-DC330-HSG</strong> at Plant P100 Hosur. 
            Subtracting 2,500 on-hand stock and 700 scheduled receipts while preserving 200 safety stock yielded a net requirement of <strong>9,000 EA</strong>, converted into Requisition REQ-2311.
          </p>
        </div>
      </div>

      {/* MRP Runs Summary Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {runs.map(run => (
          <div key={run.id} className="p-5 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-3">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs font-bold text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-500/30">
                {run.id}
              </span>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                {run.status}
              </span>
            </div>

            <div>
              <h4 className="text-sm font-bold text-white">{run.plant}</h4>
              <span className="text-[11px] text-slate-400 font-mono">Type: {run.run_type} ({run.horizon_days}d horizon)</span>
            </div>

            <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-800/80 text-[11px]">
              <div>
                <span className="text-slate-500 block">Evaluated</span>
                <span className="font-mono text-slate-200 font-bold">{run.stats.materials_evaluated} BOM items</span>
              </div>
              <div>
                <span className="text-slate-500 block">Generated PLOs</span>
                <span className="font-mono text-cyan-400 font-bold">{run.stats.planned_orders_generated} orders</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Planned Orders Table (MRP-02) */}
      <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
          <div>
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <Layers className="w-5 h-5 text-cyan-400" />
              Planned Procurement Orders & Netting Breakdown (MRP-02)
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Review multi-tier netting math, confirm firm order status, and convert to Governed Purchase Requisitions.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Filter Plant:</span>
            <select
              value={selectedPlant}
              onChange={(e) => setSelectedPlant(e.target.value)}
              className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs font-mono text-slate-200 focus:outline-none"
            >
              <option value="All">All Plants</option>
              <option value="P100">P100 Hosur</option>
              <option value="P200">P200 Chennai</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-800/80">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-900/80 text-slate-400 font-medium border-b border-slate-800">
              <tr>
                <th className="py-3 px-3.5">Planned Order ID</th>
                <th className="py-3 px-3.5">Material & Assembly</th>
                <th className="py-3 px-3.5">Gross & Stock Breakdown</th>
                <th className="py-3 px-3.5">Net Requirement</th>
                <th className="py-3 px-3.5">Lead Time & Schedule</th>
                <th className="py-3 px-3.5">Status</th>
                <th className="py-3 px-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {filteredOrders.map((plo) => (
                <tr key={plo.id} className="hover:bg-slate-800/30">
                  <td className="py-3.5 px-3.5">
                    <span className="font-bold text-cyan-400">{plo.id}</span>
                    <div className="text-[10px] text-slate-400 font-mono mt-0.5">Run: {plo.mrp_run_id}</div>
                    <div className="text-[10px] text-slate-400 font-mono">{plo.plant}</div>
                  </td>

                  <td className="py-3.5 px-3.5 font-sans">
                    <div className="font-bold text-slate-200">{plo.material_id}</div>
                    <div className="text-xs text-slate-300 line-clamp-1">{plo.material_description}</div>
                    <div className="text-[10px] text-slate-500 font-mono mt-0.5">Parent: {plo.parent_assembly} (BOM L{plo.bom_level})</div>
                  </td>

                  <td className="py-3.5 px-3.5 text-slate-300">
                    <div>Gross: <strong className="text-slate-100">{plo.gross_requirement.toLocaleString()}</strong></div>
                    <div className="text-[11px] text-slate-400">
                      - OnHand: {plo.stock_on_hand.toLocaleString()} | - Sched: {plo.scheduled_receipts.toLocaleString()}
                    </div>
                    <div className="text-[11px] text-slate-400">
                      + Safety: {plo.safety_stock.toLocaleString()} {plo.uom}
                    </div>
                  </td>

                  <td className="py-3.5 px-3.5">
                    <div className="text-base font-bold text-emerald-400 font-mono">
                      {plo.net_requirement.toLocaleString()} {plo.uom}
                    </div>
                    <span className="text-[10px] text-slate-400 uppercase">
                      Exact Lot Size
                    </span>
                  </td>

                  <td className="py-3.5 px-3.5 text-slate-300">
                    <div>Start: {plo.start_date}</div>
                    <div>Finish: {plo.finish_date}</div>
                    <span className="text-[10px] text-cyan-400 font-mono">{plo.lead_time_days} days lead time</span>
                  </td>

                  <td className="py-3.5 px-3.5 font-sans">
                    {plo.status === 'CONVERTED' ? (
                      <div>
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                          <CheckCircle2 className="w-3 h-3" />
                          CONVERTED
                        </span>
                        {plo.converted_pr_id && (
                          <div className="text-[10px] font-mono text-cyan-300 mt-1">
                            PR: {plo.converted_pr_id}
                          </div>
                        )}
                      </div>
                    ) : plo.is_firmed ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/30">
                        <ShieldCheck className="w-3 h-3" />
                        FIRMED
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                        PLANNED
                      </span>
                    )}
                  </td>

                  <td className="py-3.5 px-3.5 text-right font-sans">
                    {plo.status === 'CONVERTED' ? (
                      <Link
                        href="/p2p"
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-cyan-950/60 hover:bg-cyan-900/60 text-cyan-300 border border-cyan-500/30 text-xs font-medium transition"
                      >
                        View {plo.converted_pr_id}
                        <ArrowRight className="w-3 h-3" />
                      </Link>
                    ) : (
                      <div className="flex items-center justify-end gap-2">
                        {!plo.is_firmed && (
                          <button
                            onClick={() => handleFirmOrder(plo.id)}
                            className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition"
                          >
                            Firm
                          </button>
                        )}
                        <button
                          onClick={() => {
                            setSelectedPLO(plo);
                            setConvertQty(plo.planned_quantity);
                            setShowConvertModal(true);
                          }}
                          className="px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold shadow-md shadow-cyan-600/20 transition"
                        >
                          Convert &rarr; PR
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Trigger MRP Run Modal */}
      {showRunModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-md bg-[#0B1528] border border-slate-700 rounded-2xl shadow-2xl p-6 space-y-5 text-slate-100">
            <div className="flex items-start justify-between border-b border-slate-800 pb-3">
              <div>
                <span className="text-xs font-mono text-cyan-400 font-semibold">Net-Change Engine</span>
                <h3 className="text-lg font-bold text-white mt-0.5">Trigger Net-Change MRP Run</h3>
              </div>
              <button onClick={() => setShowRunModal(false)} className="text-slate-400 hover:text-white">✕</button>
            </div>

            <div className="space-y-4 text-xs">
              <div>
                <label className="block font-semibold text-slate-300 mb-1">Target Plant</label>
                <select
                  value={triggerPlant}
                  onChange={(e) => setTriggerPlant(e.target.value)}
                  className="w-full px-3.5 py-2 bg-slate-900 border border-slate-700 rounded-xl font-mono text-slate-200 focus:outline-none"
                >
                  <option value="P100 Hosur">P100 Hosur (Powertrain & Motors)</option>
                  <option value="P200 Chennai">P200 Chennai (Chassis & Body)</option>
                </select>
              </div>

              <div>
                <label className="block font-semibold text-slate-300 mb-1">Planning Horizon (Days)</label>
                <input
                  type="number"
                  value={horizonDays}
                  onChange={(e) => setHorizonDays(parseInt(e.target.value))}
                  className="w-full px-3.5 py-2 bg-slate-900 border border-slate-700 rounded-xl font-mono text-cyan-300 focus:outline-none"
                />
              </div>

              <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800 text-[11px] text-slate-400 space-y-1">
                <div>&bull; Includes safety stock buffer dynamically.</div>
                <div>&bull; Respects firm order frozen horizon (14 days).</div>
                <div>&bull; Exact lot sizing based on BOM explosion.</div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button onClick={() => setShowRunModal(false)} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300">
                Cancel
              </button>
              <button
                onClick={handleTriggerRun}
                disabled={triggering}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-xs font-bold text-white shadow-lg shadow-blue-600/20 disabled:opacity-50 transition"
              >
                {triggering ? 'Computing Net Requirements...' : 'Run MRP'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Convert PLO to PR Modal */}
      {showConvertModal && selectedPLO && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-md bg-[#0B1528] border border-slate-700 rounded-2xl shadow-2xl p-6 space-y-5 text-slate-100">
            <div className="flex items-start justify-between border-b border-slate-800 pb-3">
              <div>
                <span className="text-xs font-mono text-emerald-400 font-semibold">Principle P10 • Lineage Enforced</span>
                <h3 className="text-lg font-bold text-white mt-0.5">Convert Planned Order to Requisition</h3>
              </div>
              <button onClick={() => setShowConvertModal(false)} className="text-slate-400 hover:text-white">✕</button>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 space-y-1.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Order ID:</span>
                <span className="font-mono font-bold text-cyan-400">{selectedPLO.id}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Material:</span>
                <span className="font-mono text-slate-200 font-bold">{selectedPLO.material_id}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Net Requirement:</span>
                <span className="font-mono text-emerald-400 font-bold">{selectedPLO.net_requirement.toLocaleString()} {selectedPLO.uom}</span>
              </div>
            </div>

            <div className="space-y-3">
              <label className="block text-xs font-semibold text-slate-300">
                Confirm Quantity to Requisition
              </label>
              <input
                type="number"
                value={convertQty}
                onChange={(e) => setConvertQty(parseInt(e.target.value))}
                className="w-full px-3.5 py-2.5 bg-slate-900 border border-slate-700 rounded-xl font-mono text-cyan-300 text-sm focus:outline-none focus:border-cyan-500"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button onClick={() => setShowConvertModal(false)} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300">
                Cancel
              </button>
              <button
                onClick={handleConvertOrder}
                disabled={converting}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 text-xs font-bold text-white shadow-lg shadow-cyan-600/20 disabled:opacity-50 transition"
              >
                {converting ? 'Creating Requisition...' : 'Convert to PR'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
