'use client';

import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, AreaChart, Area
} from 'recharts';
import {
  Activity, Thermometer, Radio, Zap, AlertTriangle, ShieldCheck,
  Cpu, RefreshCw, Layers, Gauge, Wrench, CheckCircle2, Clock, Info,
  Check, X, ArrowRight, Box, ChevronRight, AlertCircle, Sparkles,
  Calendar, UserCheck, CheckCheck
} from 'lucide-react';
import Link from 'next/link';
import { apiClient } from '@/lib/apiClient';

interface MachineSummary {
  id: string;
  name: string;
  type: string;
  bay_location: string;
  status: string;
  oee: number;
  availability_pct: number;
  performance_pct: number;
  quality_pct: number;
  temperature_celsius: number;
  vibration_mm_s: number;
  rpm: number;
  tool_wear_pct: number;
  health_index: number;
  current_job_po: string;
  current_job_part: string;
  hours_until_service: number;
}

interface PredictiveAlert {
  id: string;
  machine_id: string;
  machine_name: string;
  severity: 'INFO' | 'WARNING' | 'CRITICAL';
  category: string;
  title: string;
  description: string;
  recommended_action: string;
  detected_at: string;
  estimated_time_to_failure: string;
  acknowledged: boolean;
}

export default function SupplierMachineTelemetryPage() {
  const queryClient = useQueryClient();
  const [selectedMachineId, setSelectedMachineId] = useState<string>('MAC-DMG-65');
  const [telemetryHistory, setTelemetryHistory] = useState<any[]>([]);
  const [showWorkOrderModal, setShowWorkOrderModal] = useState(false);
  const [selectedAlertForWO, setSelectedAlertForWO] = useState<PredictiveAlert | null>(null);
  const [workOrderForm, setWorkOrderForm] = useState({
    task_type: 'Spindle Bearing Hydrodynamic Grease Flush',
    priority: 'HIGH',
    technician: 'Sarah Jenkins (Lead Metrology Specialist)',
    scheduled_downtime_hours: 1.5,
    notes: 'Pre-emptive bearing lubrication following micro-vibration threshold.'
  });
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  // 1. Fetch Fleet Overview
  const { data: fleetData, refetch: refetchFleet } = useQuery({
    queryKey: ['iot-fleet'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/iot/fleet');
      return res.data;
    },
    refetchInterval: 5000
  });

  // 2. Fetch Active Machine Telemetry (poll every 2s for live real-time simulation)
  const { data: machineData, refetch: refetchMachine } = useQuery({
    queryKey: ['iot-machine', selectedMachineId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/iot/machine/${selectedMachineId}`);
      return res.data;
    },
    refetchInterval: 2000
  });

  // 3. Fetch Predictive Maintenance Alerts
  const { data: alerts = [], refetch: refetchAlerts } = useQuery<PredictiveAlert[]>({
    queryKey: ['iot-alerts'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/iot/predictive-maintenance/alerts');
      return res.data;
    },
    refetchInterval: 10000
  });

  // Maintain Rolling 20-Point Time-Series
  useEffect(() => {
    if (machineData) {
      const timeStr = new Date(machineData.timestamp).toLocaleTimeString();
      const point = {
        time: timeStr,
        temp: machineData.temperature_celsius,
        vib: machineData.vibration_mm_s,
        load: machineData.spindle_load_pct || 65,
        wear: machineData.tool_wear_pct || 25
      };

      setTelemetryHistory((prev) => {
        const next = [...prev, point];
        return next.length > 20 ? next.slice(next.length - 20) : next;
      });
    }
  }, [machineData]);

  // Reset rolling history on machine switch
  const handleSelectMachine = (mId: string) => {
    if (mId !== selectedMachineId) {
      setSelectedMachineId(mId);
      setTelemetryHistory([]);
    }
  };

  // Work Order Mutation
  const workOrderMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        machine_id: selectedMachineId,
        task_type: workOrderForm.task_type,
        priority: workOrderForm.priority,
        technician: workOrderForm.technician,
        scheduled_downtime_hours: Number(workOrderForm.scheduled_downtime_hours),
        notes: workOrderForm.notes
      };
      const res = await apiClient.post('/api/v1/iot/maintenance/work-order', payload);
      return res.data;
    },
    onSuccess: (data) => {
      setShowWorkOrderModal(false);
      showToast(data.message || 'Work order successfully dispatched to plant maintenance.');
      refetchAlerts();
    }
  });

  const activeMachineSummary: MachineSummary = fleetData?.machines?.find((m: any) => m.id === selectedMachineId) || {
    id: selectedMachineId,
    name: 'DMG Mori DMU 65 monoBLOCK 5-Axis',
    type: '5-Axis CNC Milling Center',
    bay_location: 'Depot Bay Alpha-1',
    status: 'OPTIMAL',
    oee: 88.4,
    availability_pct: 95.5,
    performance_pct: 93.2,
    quality_pct: 99.4,
    temperature_celsius: 64.2,
    vibration_mm_s: 2.1,
    rpm: 12500,
    tool_wear_pct: 22.5,
    health_index: 94.2,
    current_job_po: 'PO-2025-00123',
    current_job_part: 'FG-ACT-SHF-01 (Avionics Enclosure)',
    hours_until_service: 120.0
  };

  return (
    <div className="space-y-6 pb-20 max-w-[1600px] mx-auto">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-2xl shadow-2xl flex items-center gap-3 border border-blue-400/30 animate-in fade-in slide-in-from-top-4">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-bold">{toastMessage}</span>
        </div>
      )}

      {/* HEADER BREADCRUMB & SCADA STATUS */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Supplier Operations</span>
            <span className="text-slate-300">/</span>
            <span className="text-blue-600 font-bold">Industrial IoT & SCADA</span>
            <span className="text-slate-300">/</span>
            <span>Live Machine Digital Twin</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <Radio className="w-8 h-8 text-emerald-500 animate-pulse" />
            <span>Shop Floor Telemetry & Predictive Maintenance Hub</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Real-time high-frequency SCADA sensor streaming (OPC-UA / MQTT) monitoring spindle vibration, thermal expansion, tool wear, and OEE.
          </p>
        </div>

        {/* Live Status Indicators */}
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="bg-emerald-50 text-emerald-800 border border-emerald-200 px-3.5 py-1.5 rounded-xl text-xs font-bold flex items-center gap-2 shadow-xs">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping"></span>
            <span>OPC-UA Edge Node Online (2.0s Telemetry Stream)</span>
          </div>
          <button
            onClick={() => {
              refetchFleet();
              refetchMachine();
              refetchAlerts();
              showToast('SCADA sensor stream synchronized with shop floor PLC.');
            }}
            className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-xs transition-all flex items-center gap-1.5 active:scale-95"
          >
            <RefreshCw size={13} className="text-slate-500" />
            <span>Sync PLC</span>
          </button>
          <button
            onClick={() => {
              setSelectedAlertForWO(null);
              setShowWorkOrderModal(true);
            }}
            className="px-4 py-1.5 bg-purple-600 hover:bg-purple-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95"
          >
            <Wrench size={13} />
            <span>Dispatch Work Order</span>
          </button>
        </div>
      </div>

      {/* PLANT-WIDE FLEET SUMMARY KPIS */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Fleet Overall OEE</span>
            <h3 className="text-2xl font-black text-[#0B2550] mt-1">
              {fleetData?.overall_oee || 88.4}%
            </h3>
            <p className="text-[11px] text-slate-500 font-medium mt-0.5">Avail: 95.5% • Perf: 93.2% • Qual: 99.4%</p>
          </div>
          <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center border border-blue-100">
            <Gauge size={24} />
          </div>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Active Machinery Cells</span>
            <h3 className="text-2xl font-black text-emerald-600 mt-1">
              {fleetData?.active_machines_count || 4} of {fleetData?.total_machines_count || 4} Online
            </h3>
            <p className="text-[11px] text-slate-500 font-medium mt-0.5">Zero unplanned downtime</p>
          </div>
          <div className="w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 flex items-center justify-center border border-emerald-100">
            <Cpu size={24} />
          </div>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Fleet Health Index</span>
            <h3 className="text-2xl font-black text-purple-700 mt-1">
              {fleetData?.fleet_health_score || 94.2} / 100
            </h3>
            <p className="text-[11px] text-slate-500 font-medium mt-0.5">ISO 10816 Vibration Compliant</p>
          </div>
          <div className="w-12 h-12 rounded-2xl bg-purple-50 text-purple-600 flex items-center justify-center border border-purple-100">
            <ShieldCheck size={24} />
          </div>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Predictive Diagnostics</span>
            <h3 className="text-2xl font-black text-amber-600 mt-1">
              {alerts.length} Active Notice{alerts.length !== 1 ? 's' : ''}
            </h3>
            <p className="text-[11px] text-slate-500 font-medium mt-0.5">Early anomaly warning horizon</p>
          </div>
          <div className="w-12 h-12 rounded-2xl bg-amber-50 text-amber-600 flex items-center justify-center border border-amber-100">
            <AlertTriangle size={24} />
          </div>
        </div>
      </div>

      {/* MACHINE FLEET SELECTOR CARDS */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-black text-[#0B2550] uppercase tracking-wider flex items-center gap-1.5">
            <Layers size={16} className="text-blue-600" />
            <span>Select Machine Center for Telemetry Stream</span>
          </h2>
          <span className="text-xs text-slate-400 font-medium">Click to inspect live SCADA telemetry & axis loads</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {(fleetData?.machines || [activeMachineSummary]).map((m: MachineSummary) => {
            const isSelected = m.id === selectedMachineId;

            return (
              <div
                key={m.id}
                onClick={() => handleSelectMachine(m.id)}
                className={`p-4 rounded-2xl border transition-all cursor-pointer relative overflow-hidden ${
                  isSelected
                    ? 'border-blue-600 bg-gradient-to-br from-blue-50/80 to-white shadow-md ring-2 ring-blue-500/20'
                    : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-xs'
                }`}
              >
                {isSelected && (
                  <div className="absolute top-0 right-0 w-8 h-8 bg-blue-600 text-white rounded-bl-xl flex items-center justify-center">
                    <Check size={14} className="stroke-[3]" />
                  </div>
                )}

                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                    <span className="font-mono font-bold text-slate-400 text-[11px]">{m.id}</span>
                    <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200">
                      {m.bay_location}
                    </span>
                  </div>

                  <h3 className="font-black text-slate-900 text-sm leading-snug line-clamp-1">{m.name}</h3>
                  <p className="text-[11px] text-slate-500 truncate">{m.type}</p>

                  <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-100 text-xs">
                    <div>
                      <span className="text-[10px] text-slate-400 block">OEE</span>
                      <span className="font-black text-slate-800">{m.oee}%</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-400 block">Temp</span>
                      <span className="font-bold text-slate-700">{m.temperature_celsius}°C</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-400 block">Health</span>
                      <span className="font-bold text-emerald-700">{m.health_index}%</span>
                    </div>
                  </div>

                  <div className="pt-2 text-[10px] text-slate-500 truncate flex items-center gap-1 bg-slate-50 p-1.5 rounded-lg">
                    <Box size={11} className="text-slate-400 shrink-0" />
                    <span className="truncate">Job: <strong className="text-slate-700">{m.current_job_part}</strong></span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ACTIVE MACHINE LIVE TELEMETRY GAUGES */}
      <div className="bg-white rounded-2xl shadow-xs border border-slate-200 p-6 space-y-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-slate-100 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center font-black border border-blue-100">
              <Cpu size={26} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-black text-[#0B2550]">{activeMachineSummary.name}</h2>
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black bg-emerald-100 text-emerald-800 border border-emerald-200">
                  {machineData?.status || 'OPTIMAL'}
                </span>
              </div>
              <p className="text-xs text-slate-500 font-medium">
                Asset ID: <code className="font-mono font-bold text-slate-700">{selectedMachineId}</code> • Location: {activeMachineSummary.bay_location} • Connected via OPC-UA Server
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/supplier/profile"
              className="px-3.5 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold text-xs rounded-xl transition-all"
            >
              View in Digital Twin Profile
            </Link>
            <button
              onClick={() => {
                setSelectedAlertForWO(null);
                setWorkOrderForm({
                  task_type: 'Scheduled Calibration & Hydrodynamic Inspection',
                  priority: 'HIGH',
                  technician: 'Sarah Jenkins (Lead Metrology Specialist)',
                  scheduled_downtime_hours: 2.0,
                  notes: `Work order dispatched from active telemetry monitor for ${selectedMachineId}.`
                });
                setShowWorkOrderModal(true);
              }}
              className="px-3.5 py-2 bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs rounded-xl shadow-xs transition-all flex items-center gap-1.5"
            >
              <Wrench size={13} />
              <span>Schedule Service</span>
            </button>
          </div>
        </div>

        {/* 5 Real-Time Telemetry Dials */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <div className="bg-slate-50/80 p-4 rounded-2xl border border-slate-200/80 space-y-1.5">
            <span className="text-[11px] font-bold text-slate-500 uppercase flex items-center gap-1.5">
              <Thermometer size={14} className="text-rose-500" />
              <span>Spindle Temp</span>
            </span>
            <div className="text-3xl font-black text-slate-900 font-mono">
              {machineData?.temperature_celsius?.toFixed(1) || activeMachineSummary.temperature_celsius}
              <span className="text-base text-slate-400 font-normal"> °C</span>
            </div>
            <div className="text-[10px] text-emerald-700 font-bold flex items-center gap-1">
              <CheckCircle2 size={11} />
              <span>Optimal range (&lt; 72°C)</span>
            </div>
          </div>

          <div className="bg-slate-50/80 p-4 rounded-2xl border border-slate-200/80 space-y-1.5">
            <span className="text-[11px] font-bold text-slate-500 uppercase flex items-center gap-1.5">
              <Activity size={14} className="text-blue-500" />
              <span>Vibration RMS</span>
            </span>
            <div className="text-3xl font-black text-slate-900 font-mono">
              {machineData?.vibration_mm_s?.toFixed(2) || activeMachineSummary.vibration_mm_s}
              <span className="text-base text-slate-400 font-normal"> mm/s</span>
            </div>
            <div className="text-[10px] text-slate-500 font-medium">
              ISO 10816 Class II Limit: 4.5 mm/s
            </div>
          </div>

          <div className="bg-slate-50/80 p-4 rounded-2xl border border-slate-200/80 space-y-1.5">
            <span className="text-[11px] font-bold text-slate-500 uppercase flex items-center gap-1.5">
              <Zap size={14} className="text-amber-500" />
              <span>Spindle Speed</span>
            </span>
            <div className="text-3xl font-black text-slate-900 font-mono">
              {machineData?.rpm?.toLocaleString() || activeMachineSummary.rpm}
              <span className="text-base text-slate-400 font-normal"> RPM</span>
            </div>
            <div className="text-[10px] text-slate-500 font-medium">
              Load: <strong>{machineData?.spindle_load_pct || 68}%</strong> of motor rated
            </div>
          </div>

          <div className="bg-slate-50/80 p-4 rounded-2xl border border-slate-200/80 space-y-1.5">
            <span className="text-[11px] font-bold text-slate-500 uppercase flex items-center gap-1.5">
              <Wrench size={14} className="text-purple-500" />
              <span>Tool Wear Index</span>
            </span>
            <div className="text-3xl font-black text-purple-700 font-mono">
              {machineData?.tool_wear_pct || activeMachineSummary.tool_wear_pct}%
            </div>
            <div className="text-[10px] text-purple-700 font-bold">
              {machineData?.tool_life_hours_remaining || activeMachineSummary.hours_until_service} operating hrs remaining
            </div>
          </div>

          <div className="bg-slate-50/80 p-4 rounded-2xl border border-slate-200/80 space-y-1.5">
            <span className="text-[11px] font-bold text-slate-500 uppercase flex items-center gap-1.5">
              <Gauge size={14} className="text-emerald-500" />
              <span>Coolant Pressure</span>
            </span>
            <div className="text-3xl font-black text-slate-900 font-mono">
              {machineData?.coolant_pressure_bar || 70}
              <span className="text-base text-slate-400 font-normal"> bar</span>
            </div>
            <div className="text-[10px] text-emerald-700 font-bold">
              Through-spindle high-pressure
            </div>
          </div>
        </div>

        {/* Multi-Axis Load Distribution & Active Job Trace */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pt-2">
          {/* Axis Loads (5 cols) */}
          <div className="lg:col-span-5 bg-slate-50/70 p-5 rounded-2xl border border-slate-200 space-y-3">
            <h3 className="text-xs font-black text-[#0B2550] uppercase tracking-wider flex items-center gap-1.5">
              <Cpu size={14} className="text-blue-600" />
              <span>5-Axis Servo Drive Load Breakdown</span>
            </h3>

            <div className="space-y-2.5 text-xs font-mono">
              {Object.entries(machineData?.axis_load || { X: 52, Y: 61, Z: 64, A: 38, C: 31 }).map(([axis, val]: any) => (
                <div key={axis} className="space-y-1">
                  <div className="flex justify-between text-slate-700 font-bold">
                    <span>{axis}-Axis Servo Drive</span>
                    <span>{val}%</span>
                  </div>
                  <div className="w-full bg-slate-200 rounded-full h-2 overflow-hidden">
                    <div
                      className={`h-2 rounded-full transition-all duration-500 ${
                        val > 75 ? 'bg-amber-500' : 'bg-blue-600'
                      }`}
                      style={{ width: `${val}%` }}
                    ></div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Active Manufacturing Job (7 cols) */}
          <div className="lg:col-span-7 bg-blue-50/60 p-5 rounded-2xl border border-blue-200 space-y-3">
            <div className="flex items-center justify-between border-b border-blue-200/80 pb-2">
              <h3 className="text-xs font-black text-blue-950 uppercase tracking-wider flex items-center gap-1.5">
                <Box size={14} className="text-blue-700" />
                <span>Currently Active Machining Job Commitment</span>
              </h3>
              <span className="font-mono font-bold text-blue-800 text-xs">
                PO: {activeMachineSummary.current_job_po}
              </span>
            </div>

            <div className="space-y-3 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-600">Manufactured Component:</span>
                <span className="font-bold text-slate-900">{activeMachineSummary.current_job_part}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Batch Progress:</span>
                <span className="font-bold text-emerald-700 font-mono">38 of 50 units (76% Completed)</span>
              </div>
              <div className="w-full bg-blue-200/80 rounded-full h-2.5 overflow-hidden">
                <div className="bg-emerald-600 h-2.5 rounded-full" style={{ width: '76%' }}></div>
              </div>
              <div className="flex justify-between text-[11px] text-slate-500 pt-1">
                <span>Cycle Time: <strong>240 seconds</strong></span>
                <span>Spindle Runtime: <strong>1,420.5 hours</strong></span>
                <span>Tolerance Gate: <strong>AS9100D ±0.003mm</strong></span>
              </div>
            </div>

            <div className="flex gap-2 pt-1">
              <Link
                href="/supplier/orders"
                className="px-3 py-1.5 bg-white border border-blue-300 text-blue-900 font-bold text-xs rounded-xl shadow-xs hover:bg-blue-50"
              >
                Track in Orders Desk
              </Link>
              <Link
                href="/supplier/inventory"
                className="px-3 py-1.5 bg-white border border-blue-300 text-blue-900 font-bold text-xs rounded-xl shadow-xs hover:bg-blue-50"
              >
                Inspect Depot Finished Goods
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* DUAL REAL-TIME STREAMING CHARTS */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* CHART 1: THERMAL STREAM */}
        <div className="bg-white p-6 rounded-2xl shadow-xs border border-slate-200 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <h3 className="text-sm font-black text-[#0B2550] flex items-center gap-2">
                <Thermometer size={16} className="text-rose-500" />
                <span>Spindle Thermal Dynamics (°C)</span>
              </h3>
              <p className="text-xs text-slate-400">Live 2-second streaming sensor frequency</p>
            </div>
            <span className="text-xs font-mono font-bold text-slate-700 bg-slate-100 px-2.5 py-1 rounded-lg">
              {machineData?.temperature_celsius?.toFixed(1) || 64.0}°C
            </span>
          </div>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={telemetryHistory} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="tempGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="time" tick={{ fontSize: 10 }} stroke="#94a3b8" />
                <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} stroke="#94a3b8" />
                <RechartsTooltip />
                <Area type="monotone" dataKey="temp" stroke="#ef4444" strokeWidth={2.5} fillOpacity={1} fill="url(#tempGradient)" name="Temp (°C)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* CHART 2: VIBRATION RMS SPECTRUM */}
        <div className="bg-white p-6 rounded-2xl shadow-xs border border-slate-200 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <h3 className="text-sm font-black text-[#0B2550] flex items-center gap-2">
                <Activity size={16} className="text-blue-600" />
                <span>Tri-Axial Vibration Amplitude (mm/s RMS)</span>
              </h3>
              <p className="text-xs text-slate-400">ISO 10816 Mechanical Bearing Monitoring</p>
            </div>
            <span className="text-xs font-mono font-bold text-slate-700 bg-slate-100 px-2.5 py-1 rounded-lg">
              {machineData?.vibration_mm_s?.toFixed(2) || 2.1} mm/s
            </span>
          </div>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={telemetryHistory} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="vibGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#2563eb" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#2563eb" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="time" tick={{ fontSize: 10 }} stroke="#94a3b8" />
                <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} stroke="#94a3b8" />
                <RechartsTooltip />
                <Area type="monotone" dataKey="vib" stroke="#2563eb" strokeWidth={2.5} fillOpacity={1} fill="url(#vibGradient)" name="Vibration (mm/s)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* PREDICTIVE MAINTENANCE & AI ANOMALY RADAR */}
      <div className="bg-white rounded-2xl shadow-xs border border-slate-200 p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div>
            <h2 className="text-base font-black text-[#0B2550] flex items-center gap-2">
              <Sparkles size={18} className="text-purple-600" />
              <span>Predictive Maintenance & AI Anomaly Diagnostic Radar</span>
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">Automated vibration frequency analysis, tool life forecasting, and early failure prevention.</p>
          </div>
          <span className="px-3 py-1 bg-purple-50 text-purple-900 border border-purple-200 rounded-full text-xs font-bold font-mono">
            3 Active Diagnostic Models
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {alerts.map((alert: PredictiveAlert) => {
            const isWarning = alert.severity === 'WARNING';

            return (
              <div
                key={alert.id}
                className={`p-4 rounded-2xl border space-y-3 flex flex-col justify-between ${
                  isWarning
                    ? 'border-amber-300 bg-amber-50/40'
                    : 'border-slate-200 bg-slate-50/50'
                }`}
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider ${
                      isWarning
                        ? 'bg-amber-100 text-amber-800 border border-amber-300'
                        : 'bg-blue-100 text-blue-800 border border-blue-200'
                    }`}>
                      {alert.severity} • {alert.category}
                    </span>
                    <span className="font-mono text-[10px] text-slate-400">{alert.id}</span>
                  </div>

                  <h3 className="font-bold text-slate-900 text-xs leading-snug">{alert.title}</h3>
                  <p className="text-[11px] text-slate-600 leading-relaxed">{alert.description}</p>
                </div>

                <div className="space-y-3 pt-2 border-t border-slate-200/60 text-[11px]">
                  <div className="bg-white p-2.5 rounded-xl border border-slate-200/80 space-y-1">
                    <span className="text-[10px] font-bold text-purple-700 uppercase block">Recommended Prescriptive Action:</span>
                    <p className="text-slate-800 font-medium">{alert.recommended_action}</p>
                  </div>

                  <div className="flex items-center justify-between text-slate-500">
                    <span>Failure Horizon:</span>
                    <span className="font-bold text-slate-800">{alert.estimated_time_to_failure}</span>
                  </div>

                  <button
                    onClick={() => {
                      setSelectedAlertForWO(alert);
                      setWorkOrderForm({
                        task_type: alert.title,
                        priority: isWarning ? 'CRITICAL' : 'HIGH',
                        technician: 'Sarah Jenkins (Lead Metrology Specialist)',
                        scheduled_downtime_hours: 1.5,
                        notes: `Dispatched from Predictive Alert ${alert.id}: ${alert.recommended_action}`
                      });
                      setShowWorkOrderModal(true);
                    }}
                    className="w-full py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-xs transition-all flex items-center justify-center gap-1.5 active:scale-95"
                  >
                    <Wrench size={13} />
                    <span>Dispatch Preventive Work Order</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* DISPATCH WORK ORDER MODAL */}
      {showWorkOrderModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550] flex items-center gap-2">
                <Wrench className="w-5 h-5 text-purple-600" />
                <span>Dispatch Preventive Maintenance Work Order</span>
              </h3>
              <button
                onClick={() => setShowWorkOrderModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3.5 text-xs">
              <div>
                <label className="font-bold text-slate-700 block mb-1">Target Asset Machine:</label>
                <input
                  type="text"
                  value={activeMachineSummary.name}
                  readOnly
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl bg-slate-50 text-slate-700 font-bold"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Maintenance Task Type:</label>
                <input
                  type="text"
                  value={workOrderForm.task_type}
                  onChange={(e) => setWorkOrderForm({ ...workOrderForm, task_type: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-xl font-medium text-slate-800 focus:ring-2 focus:ring-blue-500 outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Priority Level:</label>
                  <select
                    value={workOrderForm.priority}
                    onChange={(e) => setWorkOrderForm({ ...workOrderForm, priority: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-300 rounded-xl font-bold text-slate-800 bg-white"
                  >
                    <option value="CRITICAL">CRITICAL (Immediate)</option>
                    <option value="HIGH">HIGH (Within 24h)</option>
                    <option value="MEDIUM">MEDIUM (Scheduled Batch)</option>
                  </select>
                </div>

                <div>
                  <label className="font-bold text-slate-700 block mb-1">Estimated Downtime:</label>
                  <input
                    type="number"
                    step="0.5"
                    value={workOrderForm.scheduled_downtime_hours}
                    onChange={(e) => setWorkOrderForm({ ...workOrderForm, scheduled_downtime_hours: parseFloat(e.target.value) || 1.0 })}
                    className="w-full px-3 py-2 border border-slate-300 rounded-xl font-medium text-slate-800"
                  />
                </div>
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Assign Lead Technician:</label>
                <input
                  type="text"
                  value={workOrderForm.technician}
                  onChange={(e) => setWorkOrderForm({ ...workOrderForm, technician: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-xl font-medium text-slate-800"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Engineering Notes / Justification:</label>
                <textarea
                  rows={2}
                  value={workOrderForm.notes}
                  onChange={(e) => setWorkOrderForm({ ...workOrderForm, notes: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-xl font-medium text-slate-800"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowWorkOrderModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={() => workOrderMutation.mutate()}
                disabled={workOrderMutation.isPending}
                className="px-5 py-2 bg-purple-600 hover:bg-purple-700 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95 flex items-center gap-1.5"
              >
                {workOrderMutation.isPending ? (
                  <>
                    <RefreshCw size={13} className="animate-spin" />
                    <span>Dispatching...</span>
                  </>
                ) : (
                  <>
                    <Wrench size={13} />
                    <span>Dispatch to Maintenance Team</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
