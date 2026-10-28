'use client';

import React, { useState, useEffect } from 'react';
import { Map, Navigation, Thermometer, Droplets, AlertOctagon, PackageCheck, Activity, ShieldCheck } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, LineChart, Line, Legend } from 'recharts';

export default function BuyerLogisticsIoT() {
  const [shipmentData, setShipmentData] = useState<any>(null);
  const [showAnalytics, setShowAnalytics] = useState(false);

  const { data: analytics } = useQuery({
    queryKey: ['iot-analytics'],
    queryFn: async () => {
      const res = await fetch('http://localhost:8080/api/v1/analytics-hub/iot');
      return res.json();
    }
  });

  useEffect(() => {
    const fetchShipment = async () => {
      try {
        const res = await fetch('http://localhost:8080/api/v1/iot/shipment/CONT-99482-XR');
        const data = await res.json();
        setShipmentData(data);
      } catch (err) {
        console.error("Failed to fetch IoT shipment data");
      }
    };

    fetchShipment();
    const interval = setInterval(fetchShipment, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
            <Navigation size={32} className="text-blue-600" />
            Live Shipment Tracking
          </h1>
          <p className="text-gray-500 mt-1">IoT Telematics for In-Transit Container: CONT-99482-XR</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowAnalytics(!showAnalytics)} className="bg-gray-100 text-[#0B2550] px-4 py-2 rounded-lg font-bold shadow-sm flex items-center gap-2">
            <Activity size={18} /> {showAnalytics ? 'Hide Analytics' : 'Show Fleet Analytics'}
          </button>
          <div className="bg-[#0B2550] text-white px-4 py-2 rounded-lg font-bold shadow-md flex items-center gap-2 cursor-pointer">
            <Map size={18} /> Open Global Map
          </div>
        </div>
      </div>

      {showAnalytics && analytics && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 animate-in fade-in slide-in-from-top-4">
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 h-72 flex flex-col">
            <h3 className="font-bold text-gray-800 mb-2">Fleet Route Deviation (Days)</h3>
            <div className="flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analytics.route_deviation} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="route" tick={{fill: '#6b7280', fontSize: 11}} axisLine={false} tickLine={false} />
                  <YAxis tick={{fill: '#6b7280'}} axisLine={false} tickLine={false} />
                  <RechartsTooltip cursor={{fill: 'transparent'}} />
                  <Legend />
                  <Bar dataKey="planned_days" name="Planned Duration" fill="#93c5fd" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="actual_days" name="Actual Duration" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 h-72 flex flex-col">
            <h3 className="font-bold text-gray-800 mb-2">Network Hardware Anomalies</h3>
            <div className="flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={analytics.machine_anomalies} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="week" tick={{fill: '#6b7280'}} axisLine={false} tickLine={false} />
                  <YAxis tick={{fill: '#6b7280'}} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Legend />
                  <Line type="monotone" dataKey="temp_spikes" name="Temp Spikes" stroke="#ef4444" strokeWidth={3} />
                  <Line type="monotone" dataKey="vib_spikes" name="Vibration Spikes" stroke="#f59e0b" strokeWidth={3} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Existing Tracking UI Elements */}
        <div className="bg-gray-100 rounded-xl shadow-inner border border-gray-200 h-[500px] flex flex-col relative overflow-hidden">
           <div className="absolute inset-0 opacity-20" style={{ backgroundImage: 'url("https://upload.wikimedia.org/wikipedia/commons/8/80/World_map_-_low_resolution.svg")', backgroundSize: 'cover', backgroundPosition: 'center' }}></div>
           {shipmentData && (
             <div className="absolute w-4 h-4 bg-blue-600 rounded-full shadow-[0_0_15px_rgba(37,99,235,1)] animate-pulse" style={{ top: `${50 - (shipmentData.latitude / 90) * 50}%`, left: `${50 + (shipmentData.longitude / 180) * 50}%` }}>
                <div className="absolute -top-10 left-1/2 -translate-x-1/2 bg-[#0B2550] text-white text-xs font-bold px-2 py-1 rounded whitespace-nowrap">Vessel: Ocean Star</div>
             </div>
           )}
           <div className="absolute bottom-4 left-4 right-4 bg-white/90 backdrop-blur rounded-lg shadow-lg p-4 flex justify-between items-center">
              <div><p className="text-xs text-gray-500 font-bold uppercase">Coordinates</p><p className="font-mono font-bold text-[#0B2550]">Lat: {shipmentData?.latitude.toFixed(4)} | Lon: {shipmentData?.longitude.toFixed(4)}</p></div>
              <div className="text-right"><p className="text-xs text-gray-500 font-bold uppercase">Estimated Arrival</p><p className="font-bold text-gray-800">In 4 Days, 12 Hrs</p></div>
           </div>
        </div>

        <div className="space-y-6 flex flex-col justify-between">
           <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
             <h3 className="font-bold text-gray-800 mb-6 flex items-center gap-2"><PackageCheck /> Cargo Integrity Sensors</h3>
             <div className="grid grid-cols-2 gap-4">
                <div className="p-4 bg-blue-50 rounded-lg border border-blue-100"><div className="flex items-center gap-2 text-blue-800 mb-2 font-bold text-sm"><Thermometer size={16}/> Internal Temp</div><div className="text-3xl font-black text-gray-800">{shipmentData?.temperature_celsius.toFixed(1)} <span className="text-lg text-gray-400">Â°C</span></div></div>
                <div className="p-4 bg-blue-50 rounded-lg border border-blue-100"><div className="flex items-center gap-2 text-blue-800 mb-2 font-bold text-sm"><Droplets size={16}/> Humidity</div><div className="text-3xl font-black text-gray-800">{shipmentData?.humidity_percent.toFixed(1)} <span className="text-lg text-gray-400">%</span></div></div>
             </div>
           </div>
           <div className={`p-6 rounded-xl shadow-sm border flex-1 flex flex-col items-center justify-center text-center ${shipmentData?.shock_event_detected ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}`}>
              {shipmentData?.shock_event_detected ? (
                <><AlertOctagon size={48} className="text-red-500 mb-4 animate-bounce" /><h3 className="text-xl font-bold text-red-900">Shock Event Detected!</h3><p className="text-red-700 mt-2">Force exceeded 5G. Damage possible.</p></>
              ) : (
                <><ShieldCheck size={48} className="text-green-500 mb-4" /><h3 className="text-xl font-bold text-green-900">Cargo Stable</h3><p className="text-green-700 mt-2">Environment within optimal ranges.</p></>
              )}
           </div>
        </div>
      </div>
    </div>
  );
}
