'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';
import {
  Truck, Thermometer, Droplets, Zap, AlertTriangle, CheckCircle,
  MapPin, Package, Radio, Battery, Wind, Activity, ChevronRight,
  ShieldCheck, ShieldAlert, Clock, ArrowRight, RefreshCw, Navigation,
  AlertOctagon, Eye, Bell
} from 'lucide-react';
import axios from 'axios';

const API = 'http://localhost:8080/api/v1/iot';

// ─── Types ────────────────────────────────────────────────────────────────────

interface ShipmentSummary {
  shipment_id: string;
  asn_id: string;
  po_id: string;
  carrier: string;
  tracking_number: string;
  origin_city: string;
  destination_city: string;
  status: string;
  progress_pct: number;
  eta_hours: number;
  latitude: number;
  longitude: number;
  temperature_celsius: number;
  humidity_percent: number;
  shock_events_count: number;
  temp_alert: boolean;
  humidity_alert: boolean;
  seal_intact: boolean;
}

interface ShipmentDetail {
  shipment_id: string;
  asn_id: string;
  po_id: string;
  carrier: string;
  tracking_number: string;
  container_id: string;
  origin_city: string;
  destination_city: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  temperature_celsius: number;
  humidity_percent: number;
  shock_event_detected: boolean;
  progress_pct: number;
  eta_hours: number;
  seal_intact: boolean;
  battery_pct: number;
  status: string;
  altitude_m: number;
  speed_kmh: number;
  g_force_peak: number;
  co2_ppm: number;
  pressure_hpa: number;
  temp_min_threshold: number;
  temp_max_threshold: number;
  humidity_max_threshold: number;
}

interface SensorPoint {
  timestamp: string;
  temperature_celsius: number;
  humidity_percent: number;
  g_force: number;
  co2_ppm: number;
  pressure_hpa: number;
  latitude: number;
  longitude: number;
}

interface ShockEvent {
  event_id: string;
  shipment_id: string;
  timestamp: string;
  g_force: number;
  duration_ms: number;
  axis: string;
  latitude: number;
  longitude: number;
  location_desc: string;
  severity: string;
  acknowledged: boolean;
}

interface ConditionAlert {
  alert_id: string;
  shipment_id: string;
  asn_id: string;
  po_id: string;
  type: string;
  severity: string;
  title: string;
  description: string;
  recommended_action: string;
  detected_at: string;
  acknowledged: boolean;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatHoursAgo(isoString: string) {
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function formatETA(hours: number) {
  if (hours < 1) return `${Math.round(hours * 60)}min`;
  return `${Math.floor(hours)}h ${Math.round((hours % 1) * 60)}m`;
}

function severityColors(severity: string) {
  switch (severity) {
    case 'HIGH': return { bg: 'bg-rose-950/60', border: 'border-rose-500/60', badge: 'bg-rose-500', text: 'text-rose-300' };
    case 'MEDIUM': return { bg: 'bg-amber-950/60', border: 'border-amber-500/60', badge: 'bg-amber-500', text: 'text-amber-300' };
    default: return { bg: 'bg-blue-950/60', border: 'border-blue-500/40', badge: 'bg-blue-500', text: 'text-blue-300' };
  }
}

// ─── Sub-Components ───────────────────────────────────────────────────────────

function GaugeArc({ value, min, max, danger, label, unit, color }: {
  value: number; min: number; max: number; danger?: number; label: string; unit: string; color: string;
}) {
  const pct = Math.min(1, Math.max(0, (value - min) / (max - min)));
  const angle = -135 + pct * 270;
  const isAlert = danger !== undefined && value > danger;

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative w-24 h-24">
        <svg viewBox="0 0 100 100" className="w-full h-full -rotate-[0deg]">
          {/* Background arc */}
          <circle cx="50" cy="50" r="38" fill="none" stroke="#1e293b" strokeWidth="10"
            strokeDasharray="239" strokeDashoffset="60" strokeLinecap="round"
            transform="rotate(135 50 50)" />
          {/* Value arc */}
          <circle cx="50" cy="50" r="38" fill="none"
            stroke={isAlert ? '#ef4444' : color}
            strokeWidth="10"
            strokeDasharray={`${pct * 239} 239`}
            strokeDashoffset="60"
            strokeLinecap="round"
            transform="rotate(135 50 50)"
            style={{ transition: 'stroke-dasharray 0.5s ease' }}
          />
          {/* Needle dot */}
          <circle cx="50" cy="50" r="4" fill={isAlert ? '#ef4444' : color} />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center mt-2">
          <span className={`text-lg font-black ${isAlert ? 'text-rose-400' : 'text-white'}`}>
            {typeof value === 'number' ? value.toFixed(1) : '--'}
          </span>
          <span className="text-[9px] text-slate-400 font-semibold">{unit}</span>
        </div>
        {isAlert && (
          <div className="absolute -top-1 -right-1 h-3 w-3 rounded-full bg-rose-500 animate-ping" />
        )}
      </div>
      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">{label}</span>
    </div>
  );
}

function RouteProgressBar({ progress, origin, destination, eta }: {
  progress: number; origin: string; destination: string; eta: number;
}) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center text-xs">
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-emerald-400/30" />
          <span className="font-bold text-slate-300 truncate max-w-[120px]">{origin}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="font-bold text-blue-300 truncate max-w-[120px] text-right">{destination}</span>
          <div className="h-2.5 w-2.5 rounded-full bg-blue-400 ring-2 ring-blue-400/30" />
        </div>
      </div>
      <div className="relative h-2.5 bg-slate-700/60 rounded-full overflow-visible">
        <div
          className="h-full bg-gradient-to-r from-emerald-500 to-blue-500 rounded-full transition-all duration-700"
          style={{ width: `${progress}%` }}
        />
        {/* Truck icon on progress */}
        <div
          className="absolute -top-1.5 -translate-x-1/2 transition-all duration-700"
          style={{ left: `${Math.max(5, Math.min(95, progress))}%` }}
        >
          <div className="bg-white rounded-full p-0.5 shadow-lg shadow-blue-500/30 ring-2 ring-blue-400">
            <Truck size={10} className="text-blue-700" />
          </div>
        </div>
      </div>
      <div className="flex justify-between items-center text-[10px] text-slate-500">
        <span className="font-bold text-emerald-400">{progress.toFixed(1)}% complete</span>
        <span className="flex items-center gap-1">
          <Clock size={9} />
          ETA: <strong className="text-blue-300 ml-0.5">{formatETA(eta)}</strong>
        </span>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ShipmentTransitPage() {
  const [shipments, setShipments] = useState<ShipmentSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ShipmentDetail | null>(null);
  const [sensorHistory, setSensorHistory] = useState<SensorPoint[]>([]);
  const [shockEvents, setShockEvents] = useState<ShockEvent[]>([]);
  const [alerts, setAlerts] = useState<ConditionAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [activeTab, setActiveTab] = useState<'sensors' | 'shocks' | 'route'>('sensors');

  // Fetch fleet overview
  const fetchFleet = useCallback(async () => {
    try {
      const [fleetRes, alertsRes] = await Promise.all([
        axios.get(`${API}/shipments`),
        axios.get(`${API}/shipments/alerts`)
      ]);
      setShipments(fleetRes.data);
      setAlerts(alertsRes.data.alerts || []);
      setLastUpdated(new Date());

      // Auto-select first
      if (!selected && fleetRes.data.length > 0) {
        setSelected(fleetRes.data[0].shipment_id);
      }
    } catch (e) {
      console.error('Fleet fetch error', e);
    } finally {
      setLoading(false);
    }
  }, [selected]);

  // Fetch selected shipment detail
  const fetchDetail = useCallback(async (id: string) => {
    try {
      const [detailRes, sensorsRes, shocksRes] = await Promise.all([
        axios.get(`${API}/shipment/${id}`),
        axios.get(`${API}/shipment/${id}/sensors?points=24`),
        axios.get(`${API}/shipment/${id}/shocks`)
      ]);
      setDetail(detailRes.data);
      setSensorHistory(sensorsRes.data);
      setShockEvents(shocksRes.data);
    } catch (e) {
      console.error('Detail fetch error', e);
    }
  }, []);

  useEffect(() => {
    fetchFleet();
    const interval = setInterval(fetchFleet, 5000);
    return () => clearInterval(interval);
  }, [fetchFleet]);

  useEffect(() => {
    if (selected) {
      fetchDetail(selected);
      const interval = setInterval(() => fetchDetail(selected), 5000);
      return () => clearInterval(interval);
    }
  }, [selected, fetchDetail]);

  // Chart data
  const chartData = sensorHistory.map((p, i) => ({
    t: `${24 - i}h`,
    temp: p.temperature_celsius,
    humidity: p.humidity_percent,
    g: p.g_force,
    co2: p.co2_ppm,
    pressure: p.pressure_hpa,
  })).reverse();

  const selectedShipment = shipments.find(s => s.shipment_id === selected);

  return (
    <div
      className="min-h-screen pb-10"
      style={{ background: 'linear-gradient(135deg, #060d1a 0%, #0b1e38 50%, #081525 100%)' }}
    >
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="border-b border-slate-700/50 bg-slate-900/60 backdrop-blur-sm sticky top-0 z-20 px-6 py-4">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
              <span>Supplier Portal</span>
              <ChevronRight size={11} />
              <span>Logistics</span>
              <ChevronRight size={11} />
              <span className="text-blue-400 font-semibold">Shipment Transit IoT</span>
            </div>
            <h1 className="text-2xl font-black text-white flex items-center gap-3">
              <div className="p-2 rounded-xl bg-blue-600/20 border border-blue-500/30">
                <Navigation size={22} className="text-blue-400" />
              </div>
              Real-Time Shipment Transit &amp; IoT Monitoring
              <span className="px-2 py-0.5 text-[10px] font-black rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1 animate-pulse">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
                LIVE
              </span>
            </h1>
          </div>
          <div className="flex items-center gap-4">
            {alerts.length > 0 && (
              <div className="flex items-center gap-2 px-3 py-2 bg-rose-900/40 border border-rose-500/40 rounded-xl text-rose-300 text-xs font-bold">
                <AlertOctagon size={14} className="animate-pulse" />
                {alerts.length} Active Alert{alerts.length !== 1 ? 's' : ''}
              </div>
            )}
            <div className="text-[11px] text-slate-500 flex items-center gap-1.5">
              <RefreshCw size={10} className="text-emerald-400" />
              Updated {formatHoursAgo(lastUpdated.toISOString())}
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-[1600px] mx-auto px-6 pt-6 space-y-6">

        {/* ── Condition Alerts Banner ─────────────────────────────────── */}
        {alerts.length > 0 && (
          <div className="space-y-2">
            {alerts.map(alert => {
              const c = severityColors(alert.severity);
              return (
                <div key={alert.alert_id}
                  className={`flex items-start gap-4 p-4 rounded-xl border ${c.bg} ${c.border} backdrop-blur-sm`}>
                  <div className={`p-2 rounded-lg ${c.badge}/20 shrink-0`}>
                    {alert.type === 'SHOCK_EVENT'
                      ? <AlertOctagon size={18} className={c.text} />
                      : <Thermometer size={18} className={c.text} />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className={`text-[10px] font-black px-2 py-0.5 rounded-full ${c.badge} text-white`}>
                        {alert.severity}
                      </span>
                      <span className="font-bold text-white text-sm">{alert.title}</span>
                      <span className="text-[10px] text-slate-500 font-mono">{alert.shipment_id}</span>
                    </div>
                    <p className="text-xs text-slate-400 mb-1">{alert.description}</p>
                    <p className="text-xs text-amber-300 font-semibold flex items-center gap-1">
                      <Eye size={10} /> Action: {alert.recommended_action}
                    </p>
                  </div>
                  <div className="text-[10px] text-slate-500 shrink-0">
                    {formatHoursAgo(alert.detected_at)}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* ── Shipment Fleet Cards ────────────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {loading ? Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-48 rounded-2xl bg-slate-800/40 animate-pulse border border-slate-700/40" />
          )) : shipments.map(s => {
            const isActive = s.shipment_id === selected;
            const hasAlert = s.temp_alert || s.humidity_alert || s.shock_events_count > 0;
            return (
              <button
                key={s.shipment_id}
                onClick={() => setSelected(s.shipment_id)}
                className={`text-left p-5 rounded-2xl border transition-all duration-200 hover:scale-[1.01] ${
                  isActive
                    ? 'bg-blue-600/20 border-blue-500/60 shadow-lg shadow-blue-500/10'
                    : 'bg-slate-800/40 border-slate-700/40 hover:border-slate-600/60 hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <div className="font-mono text-xs text-blue-400 font-bold mb-0.5">{s.shipment_id}</div>
                    <div className="text-white font-bold text-sm">{s.carrier}</div>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    {hasAlert && (
                      <span className="px-1.5 py-0.5 text-[9px] font-black rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/40 flex items-center gap-0.5">
                        <AlertTriangle size={8} /> ALERT
                      </span>
                    )}
                    <span className="px-1.5 py-0.5 text-[9px] font-black rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-0.5">
                      <Radio size={8} /> {s.status}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 text-[11px] text-slate-400 mb-3">
                  <MapPin size={10} className="text-emerald-400 shrink-0" />
                  <span className="truncate">{s.origin_city}</span>
                  <ArrowRight size={9} className="shrink-0" />
                  <span className="truncate text-blue-300 font-semibold">{s.destination_city}</span>
                </div>

                <RouteProgressBar
                  progress={s.progress_pct}
                  origin={s.origin_city}
                  destination={s.destination_city}
                  eta={s.eta_hours}
                />

                <div className="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-slate-700/40">
                  <div className="text-center">
                    <div className={`text-sm font-black ${s.temp_alert ? 'text-rose-400' : 'text-white'}`}>
                      {s.temperature_celsius.toFixed(1)}°C
                    </div>
                    <div className="text-[9px] text-slate-500 font-semibold">TEMP</div>
                  </div>
                  <div className="text-center">
                    <div className={`text-sm font-black ${s.humidity_alert ? 'text-amber-400' : 'text-white'}`}>
                      {s.humidity_percent.toFixed(1)}%
                    </div>
                    <div className="text-[9px] text-slate-500 font-semibold">HUMIDITY</div>
                  </div>
                  <div className="text-center">
                    <div className={`text-sm font-black ${s.shock_events_count > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                      {s.shock_events_count}
                    </div>
                    <div className="text-[9px] text-slate-500 font-semibold">SHOCKS</div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* ── Main Detail Panel ───────────────────────────────────────── */}
        {detail && selectedShipment && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">

            {/* LEFT: Sensor gauges + tabs */}
            <div className="xl:col-span-2 space-y-5">

              {/* Shipment Header Card */}
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-2xl p-5 backdrop-blur-sm">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-blue-400 font-bold text-sm">{detail.shipment_id}</span>
                      <span className="text-slate-600">•</span>
                      <span className="font-mono text-slate-400 text-xs">{detail.asn_id}</span>
                    </div>
                    <h2 className="text-xl font-black text-white mb-0.5">{detail.carrier}</h2>
                    <div className="flex items-center gap-2 text-xs text-slate-400">
                      <span className="font-mono text-slate-500">{detail.tracking_number}</span>
                      <span>•</span>
                      <span>Container: <span className="font-mono text-cyan-400">{detail.container_id}</span></span>
                    </div>
                  </div>
                  <div className="text-right space-y-1.5">
                    <div className={`flex items-center gap-1.5 justify-end text-xs font-bold ${detail.seal_intact ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {detail.seal_intact ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
                      Seal {detail.seal_intact ? 'Intact' : 'BROKEN'}
                    </div>
                    <div className="flex items-center gap-1.5 justify-end text-xs text-slate-400">
                      <Battery size={12} className={detail.battery_pct < 25 ? 'text-rose-400' : 'text-emerald-400'} />
                      <span className={detail.battery_pct < 25 ? 'text-rose-400 font-bold' : ''}>
                        {detail.battery_pct}% battery
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 justify-end text-xs text-slate-400">
                      <Activity size={12} className="text-blue-400" />
                      PO: <span className="font-mono text-blue-300 font-bold ml-1">{detail.po_id}</span>
                    </div>
                  </div>
                </div>

                <RouteProgressBar
                  progress={detail.progress_pct}
                  origin={detail.origin_city}
                  destination={detail.destination_city}
                  eta={detail.eta_hours}
                />
              </div>

              {/* Live Sensor Gauges */}
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-2xl p-5 backdrop-blur-sm">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-black text-white flex items-center gap-2">
                    <Radio size={15} className="text-blue-400 animate-pulse" />
                    Live IoT Sensor Readings
                  </h3>
                  <span className="text-[10px] text-slate-500 font-mono">
                    {new Date(detail.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 justify-items-center">
                  <GaugeArc
                    value={detail.temperature_celsius}
                    min={-10} max={50}
                    danger={detail.temp_max_threshold}
                    label="Temp" unit="°C"
                    color="#3b82f6"
                  />
                  <GaugeArc
                    value={detail.humidity_percent}
                    min={0} max={100}
                    danger={detail.humidity_max_threshold}
                    label="Humidity" unit="%RH"
                    color="#06b6d4"
                  />
                  <GaugeArc
                    value={detail.g_force_peak}
                    min={0} max={10}
                    danger={3.5}
                    label="G-Force" unit="G"
                    color="#f59e0b"
                  />
                  <GaugeArc
                    value={detail.co2_ppm}
                    min={350} max={700}
                    danger={600}
                    label="CO₂" unit="ppm"
                    color="#8b5cf6"
                  />
                  <GaugeArc
                    value={detail.pressure_hpa}
                    min={900} max={1100}
                    label="Pressure" unit="hPa"
                    color="#10b981"
                  />
                  <GaugeArc
                    value={detail.speed_kmh}
                    min={0} max={1000}
                    label="Speed" unit="km/h"
                    color="#f97316"
                  />
                </div>

                {/* Threshold Compliance Strip */}
                <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-slate-700/40">
                  <div className={`flex items-center gap-2 p-2.5 rounded-xl border text-xs font-bold ${
                    detail.temperature_celsius > detail.temp_max_threshold || detail.temperature_celsius < detail.temp_min_threshold
                      ? 'bg-rose-950/50 border-rose-500/40 text-rose-300' : 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300'
                  }`}>
                    <Thermometer size={13} />
                    <div>
                      <div>Temp Range</div>
                      <div className="font-mono text-[10px] opacity-70">{detail.temp_min_threshold}–{detail.temp_max_threshold}°C</div>
                    </div>
                    {detail.temperature_celsius > detail.temp_max_threshold || detail.temperature_celsius < detail.temp_min_threshold
                      ? <AlertTriangle size={12} className="ml-auto" />
                      : <CheckCircle size={12} className="ml-auto" />}
                  </div>
                  <div className={`flex items-center gap-2 p-2.5 rounded-xl border text-xs font-bold ${
                    detail.humidity_percent > detail.humidity_max_threshold
                      ? 'bg-amber-950/50 border-amber-500/40 text-amber-300' : 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300'
                  }`}>
                    <Droplets size={13} />
                    <div>
                      <div>Humidity Max</div>
                      <div className="font-mono text-[10px] opacity-70">&lt;{detail.humidity_max_threshold}%RH</div>
                    </div>
                    {detail.humidity_percent > detail.humidity_max_threshold
                      ? <AlertTriangle size={12} className="ml-auto" />
                      : <CheckCircle size={12} className="ml-auto" />}
                  </div>
                  <div className={`flex items-center gap-2 p-2.5 rounded-xl border text-xs font-bold ${
                    detail.shock_event_detected
                      ? 'bg-rose-950/50 border-rose-500/40 text-rose-300' : 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300'
                  }`}>
                    <Zap size={13} />
                    <div>
                      <div>Shock Status</div>
                      <div className="font-mono text-[10px] opacity-70">{detail.shock_event_detected ? 'DETECTED' : 'None'}</div>
                    </div>
                    {detail.shock_event_detected
                      ? <AlertTriangle size={12} className="ml-auto animate-pulse" />
                      : <CheckCircle size={12} className="ml-auto" />}
                  </div>
                </div>
              </div>

              {/* Tabs: Sensor History / Shock Log / Route */}
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-2xl overflow-hidden backdrop-blur-sm">
                <div className="flex border-b border-slate-700/50">
                  {(['sensors', 'shocks', 'route'] as const).map(tab => (
                    <button
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      className={`px-5 py-3.5 text-xs font-bold uppercase tracking-wider transition-all ${
                        activeTab === tab
                          ? 'bg-blue-600/20 text-blue-300 border-b-2 border-blue-500'
                          : 'text-slate-500 hover:text-slate-300 hover:bg-slate-700/30'
                      }`}
                    >
                      {tab === 'sensors' && '📊 Sensor History'}
                      {tab === 'shocks' && `⚡ Shock Events (${shockEvents.length})`}
                      {tab === 'route' && '🗺️ Route Waypoints'}
                    </button>
                  ))}
                </div>

                {activeTab === 'sensors' && (
                  <div className="p-5 space-y-5">
                    {/* Temperature chart */}
                    <div>
                      <div className="text-xs font-bold text-slate-400 mb-3 flex items-center gap-2">
                        <Thermometer size={12} className="text-blue-400" />
                        Temperature & Humidity (24h)
                        <span className="ml-auto font-mono text-slate-600">Thresholds shown as dashed lines</span>
                      </div>
                      <ResponsiveContainer width="100%" height={180}>
                        <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                          <defs>
                            <linearGradient id="tempGrad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.25} />
                              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                            </linearGradient>
                            <linearGradient id="humidGrad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.2} />
                              <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1e2d45" />
                          <XAxis dataKey="t" tick={{ fill: '#475569', fontSize: 9 }} />
                          <YAxis tick={{ fill: '#475569', fontSize: 9 }} />
                          <Tooltip
                            contentStyle={{ backgroundColor: '#0f1f35', border: '1px solid #1e3a5f', borderRadius: 8, fontSize: 11 }}
                            labelStyle={{ color: '#94a3b8' }}
                          />
                          <ReferenceLine y={detail.temp_max_threshold} stroke="#ef4444" strokeDasharray="4 4" strokeWidth={1.5} />
                          <ReferenceLine y={detail.temp_min_threshold} stroke="#f59e0b" strokeDasharray="4 4" strokeWidth={1.5} />
                          <Area type="monotone" dataKey="temp" stroke="#3b82f6" strokeWidth={2} fill="url(#tempGrad)" name="Temp °C" dot={false} />
                          <Area type="monotone" dataKey="humidity" stroke="#06b6d4" strokeWidth={1.5} fill="url(#humidGrad)" name="Humidity %" dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>

                    {/* G-Force chart */}
                    <div>
                      <div className="text-xs font-bold text-slate-400 mb-3 flex items-center gap-2">
                        <Zap size={12} className="text-amber-400" />
                        G-Force & CO₂ (24h)
                      </div>
                      <ResponsiveContainer width="100%" height={150}>
                        <LineChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1e2d45" />
                          <XAxis dataKey="t" tick={{ fill: '#475569', fontSize: 9 }} />
                          <YAxis tick={{ fill: '#475569', fontSize: 9 }} />
                          <Tooltip
                            contentStyle={{ backgroundColor: '#0f1f35', border: '1px solid #1e3a5f', borderRadius: 8, fontSize: 11 }}
                            labelStyle={{ color: '#94a3b8' }}
                          />
                          <ReferenceLine y={3.5} stroke="#ef4444" strokeDasharray="4 4" strokeWidth={1.5} label={{ value: 'G-Limit', fill: '#ef4444', fontSize: 8 }} />
                          <Line type="monotone" dataKey="g" stroke="#f59e0b" strokeWidth={2} name="G-Force" dot={false} activeDot={{ r: 4 }} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {activeTab === 'shocks' && (
                  <div className="p-5">
                    {shockEvents.length === 0 ? (
                      <div className="text-center py-12">
                        <ShieldCheck size={40} className="text-emerald-500 mx-auto mb-3 opacity-70" />
                        <p className="text-slate-400 font-semibold text-sm">No shock events recorded for this shipment</p>
                        <p className="text-slate-600 text-xs mt-1">Container handling has been within safe G-force limits</p>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {shockEvents.map(ev => {
                          const c = severityColors(ev.severity);
                          return (
                            <div key={ev.event_id} className={`flex items-start gap-4 p-4 rounded-xl border ${c.bg} ${c.border}`}>
                              <div className={`p-2.5 rounded-xl ${c.badge}/20 shrink-0`}>
                                <Zap size={16} className={c.text} />
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className={`text-[10px] font-black px-2 py-0.5 rounded-full ${c.badge} text-white`}>
                                    {ev.severity}
                                  </span>
                                  <span className="font-black text-white text-sm">{ev.g_force}G Peak</span>
                                  <span className="text-slate-500 text-xs">on {ev.axis}-Axis</span>
                                  <span className="text-slate-600 text-[10px] font-mono">{ev.event_id}</span>
                                </div>
                                <div className="flex items-center gap-3 text-xs text-slate-400 mb-1.5">
                                  <span className="flex items-center gap-1"><MapPin size={9} />{ev.location_desc}</span>
                                </div>
                                <div className="flex items-center gap-4 text-[11px]">
                                  <span className="text-slate-500">Duration: <span className="font-bold text-white">{ev.duration_ms}ms</span></span>
                                  <span className="text-slate-500">GPS: <span className="font-mono text-cyan-400">{ev.latitude.toFixed(3)}, {ev.longitude.toFixed(3)}</span></span>
                                  <span className="text-slate-500">{formatHoursAgo(ev.timestamp)}</span>
                                </div>
                              </div>
                              <div className={`text-[10px] font-bold px-2 py-1 rounded-lg ${
                                ev.acknowledged ? 'bg-slate-700/50 text-slate-400' : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                              }`}>
                                {ev.acknowledged ? '✓ ACK' : 'UNACK'}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {activeTab === 'route' && (
                  <div className="p-5">
                    <div className="space-y-3">
                      {sensorHistory.slice(0, 8).map((p, i) => (
                        <div key={i} className="flex items-center gap-4 p-3 rounded-xl bg-slate-700/30 border border-slate-700/40">
                          <div className="relative flex flex-col items-center">
                            <div className={`h-3 w-3 rounded-full border-2 ${
                              i === 0 ? 'bg-emerald-400 border-emerald-300' :
                              i === sensorHistory.slice(0, 8).length - 1 ? 'bg-blue-400 border-blue-300' :
                              'bg-slate-600 border-slate-500'
                            }`} />
                            {i < sensorHistory.slice(0, 8).length - 1 && (
                              <div className="w-px h-6 bg-slate-600/60 mt-1 absolute top-3" />
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 text-xs">
                              <span className="font-mono text-cyan-400">{p.latitude.toFixed(3)}, {p.longitude.toFixed(3)}</span>
                              <span className="text-slate-600">•</span>
                              <span className="text-slate-500">{new Date(p.timestamp).toLocaleTimeString()}</span>
                            </div>
                          </div>
                          <div className="grid grid-cols-3 gap-3 text-center text-[10px]">
                            <div>
                              <div className="font-bold text-blue-300">{p.temperature_celsius.toFixed(1)}°C</div>
                              <div className="text-slate-600">temp</div>
                            </div>
                            <div>
                              <div className="font-bold text-cyan-300">{p.humidity_percent.toFixed(1)}%</div>
                              <div className="text-slate-600">humid</div>
                            </div>
                            <div>
                              <div className="font-bold text-amber-300">{p.g_force.toFixed(1)}G</div>
                              <div className="text-slate-600">g-force</div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* RIGHT: Metadata + GPS + Stats */}
            <div className="space-y-5">

              {/* Container Metadata */}
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-2xl p-5 backdrop-blur-sm">
                <h3 className="text-xs font-black text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
                  <Package size={13} className="text-blue-400" />
                  Container &amp; Logistics
                </h3>
                <div className="space-y-3">
                  {[
                    { label: 'Container ID', value: detail.container_id, mono: true },
                    { label: 'ASN Reference', value: detail.asn_id, mono: true },
                    { label: 'Purchase Order', value: detail.po_id, mono: true },
                    { label: 'Tracking Number', value: detail.tracking_number, mono: true },
                    { label: 'Carrier', value: detail.carrier, mono: false },
                  ].map(r => (
                    <div key={r.label} className="flex justify-between items-center text-xs py-2 border-b border-slate-700/30 last:border-0">
                      <span className="text-slate-500 font-semibold">{r.label}</span>
                      <span className={`font-bold text-slate-200 ${r.mono ? 'font-mono text-cyan-300' : ''}`}>{r.value}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Live Position */}
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-2xl p-5 backdrop-blur-sm">
                <h3 className="text-xs font-black text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
                  <Navigation size={13} className="text-emerald-400" />
                  Live GPS Position
                </h3>
                <div className="bg-slate-900/60 rounded-xl p-4 border border-slate-700/40 text-center mb-3">
                  <div className="text-2xl font-black text-white mb-0.5">{detail.latitude.toFixed(4)}°</div>
                  <div className="text-xs text-slate-500 mb-2">Latitude (N)</div>
                  <div className="text-2xl font-black text-white mb-0.5">{detail.longitude.toFixed(4)}°</div>
                  <div className="text-xs text-slate-500">Longitude (E/W)</div>
                </div>
                <div className="grid grid-cols-2 gap-3 text-center">
                  <div className="bg-slate-900/40 rounded-lg p-2.5 border border-slate-700/30">
                    <div className="text-sm font-black text-orange-300">{detail.altitude_m.toLocaleString()}m</div>
                    <div className="text-[9px] text-slate-500 font-bold uppercase mt-0.5">Altitude</div>
                  </div>
                  <div className="bg-slate-900/40 rounded-lg p-2.5 border border-slate-700/30">
                    <div className="text-sm font-black text-purple-300">{detail.speed_kmh.toFixed(0)} km/h</div>
                    <div className="text-[9px] text-slate-500 font-bold uppercase mt-0.5">Speed</div>
                  </div>
                </div>
              </div>

              {/* Fleet Stats Summary */}
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-2xl p-5 backdrop-blur-sm">
                <h3 className="text-xs font-black text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
                  <Truck size={13} className="text-blue-400" />
                  Fleet Status
                </h3>
                <div className="space-y-3">
                  <div className="flex justify-between text-xs py-2 border-b border-slate-700/30">
                    <span className="text-slate-500 font-semibold">Active Shipments</span>
                    <span className="font-black text-white">{shipments.length}</span>
                  </div>
                  <div className="flex justify-between text-xs py-2 border-b border-slate-700/30">
                    <span className="text-slate-500 font-semibold">Total Shock Events</span>
                    <span className={`font-black ${shipments.reduce((a, s) => a + s.shock_events_count, 0) > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                      {shipments.reduce((a, s) => a + s.shock_events_count, 0)}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs py-2 border-b border-slate-700/30">
                    <span className="text-slate-500 font-semibold">Temp Alerts</span>
                    <span className={`font-black ${shipments.filter(s => s.temp_alert).length > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                      {shipments.filter(s => s.temp_alert).length}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs py-2">
                    <span className="text-slate-500 font-semibold">Humidity Alerts</span>
                    <span className={`font-black ${shipments.filter(s => s.humidity_alert).length > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
                      {shipments.filter(s => s.humidity_alert).length}
                    </span>
                  </div>
                </div>

                {/* All shipments mini-list */}
                <div className="mt-4 pt-4 border-t border-slate-700/40 space-y-2">
                  {shipments.map(s => (
                    <button
                      key={s.shipment_id}
                      onClick={() => setSelected(s.shipment_id)}
                      className={`w-full flex items-center justify-between p-2.5 rounded-lg text-xs transition-all ${
                        s.shipment_id === selected
                          ? 'bg-blue-600/20 border border-blue-500/30 text-blue-300'
                          : 'bg-slate-700/30 border border-slate-700/20 text-slate-400 hover:bg-slate-700/50'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <div className={`h-1.5 w-1.5 rounded-full ${s.temp_alert || s.shock_events_count > 0 ? 'bg-rose-400 animate-ping' : 'bg-emerald-400'}`} />
                        <span className="font-mono font-bold">{s.shipment_id}</span>
                      </div>
                      <div className="font-bold">{s.progress_pct.toFixed(0)}%</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && shipments.length === 0 && (
          <div className="text-center py-24">
            <Truck size={52} className="text-slate-600 mx-auto mb-4" />
            <p className="text-slate-400 font-bold text-lg">No active shipments in transit</p>
            <p className="text-slate-600 text-sm mt-1">Create an ASN to start monitoring in-transit IoT telemetry</p>
          </div>
        )}
      </div>
    </div>
  );
}
