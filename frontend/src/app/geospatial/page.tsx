'use client';
import React, { useState } from 'react';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatusBadge } from '@/components/ui/StatusBadge';

export default function GeospatialIntelligence() {
  const handleGenericAction = (actionName: string) => {
    alert(`Action triggered: ${actionName}\n\nThis feature is currently being integrated with the backend APIs.`);
  };

  const [mitigated, setMitigated] = useState(false);

  return (
    <div className="max-w-[1600px] mx-auto pb-12">
      <PageHeader 
        title="Predictive Geospatial Intelligence" 
        subtitle="Global threat monitoring mapping live weather, AIS shipping data, and geopolitical events against your N-Tier supply chain."
        actions={
          <div className="flex gap-3">
             <button onClick={() => handleGenericAction('Configure Data Feeds')}  className="bg-white border border-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-slate-50 shadow-sm transition-colors">
                Configure Data Feeds
             </button>
             <button onClick={() => handleGenericAction('🌍 Refresh Global Map')}  className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 shadow-sm transition-colors flex items-center gap-2">
                <span className="text-xl">🌍</span> Refresh Global Map
             </button>
          </div>
        }
      />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        
        {/* Global Threat Map */}
        <div className="xl:col-span-2 bg-[#0F172A] rounded-xl border border-slate-800 shadow-xl overflow-hidden relative min-h-[700px] flex items-center justify-center">
           
           {/* Abstract World Map Graphic */}
           <div className="absolute inset-0 opacity-20" style={{backgroundImage: 'radial-gradient(circle at center, #38BDF8 1px, transparent 1px)', backgroundSize: '16px 16px'}}></div>
           
           <svg viewBox="0 0 800 400" className="w-full h-full relative z-10 p-8" fill="none" stroke="#1E293B">
              {/* Very rough world map approximation polygons */}
              <path d="M 100,50 L 150,40 L 250,60 L 220,150 L 180,250 L 120,300 L 90,200 L 50,150 Z" fill="#1E293B" strokeWidth="2" /> {/* Americas */}
              <path d="M 350,80 L 450,50 L 550,60 L 600,100 L 580,200 L 500,280 L 400,250 L 320,150 Z" fill="#1E293B" strokeWidth="2" /> {/* Eurasia/Africa */}
              <path d="M 650,220 L 720,200 L 760,250 L 700,320 L 620,280 Z" fill="#1E293B" strokeWidth="2" /> {/* Australia/Oceania */}
              
              {/* Shipping Route */}
              <path d="M 580,180 Q 400,280 200,180" stroke="#38BDF8" strokeWidth="2" strokeDasharray="5 5" className="animate-pulse" />
              
              {/* Shenzhen Supplier Node */}
              <circle cx="580" cy="180" r="6" fill="#38BDF8" className="animate-pulse" />
              
              {/* Destination Node (US) */}
              <circle cx="200" cy="180" r="6" fill="#38BDF8" />
              
              {/* The Threat: Typhoon */}
              <g className={`transition-all duration-1000 ${mitigated ? 'opacity-30 scale-75' : 'opacity-100 scale-100'}`}>
                 <circle cx="480" cy="220" r="40" fill="rgba(239, 68, 68, 0.1)" stroke="#EF4444" strokeWidth="1" />
                 <circle cx="480" cy="220" r="25" fill="rgba(239, 68, 68, 0.2)" stroke="#EF4444" strokeWidth="1" />
                 <circle cx="480" cy="220" r="10" fill="#EF4444" stroke="#EF4444" className="animate-ping" />
                 <path d="M 480,220 L 520,180" stroke="#EF4444" strokeWidth="2" strokeDasharray="3 3" />
                 <text x="440" y="280" fill="#EF4444" fontSize="12" fontWeight="bold">TYPHOON GAEMI</text>
              </g>

              {/* Reroute (Air Freight) */}
              {mitigated && (
                 <g className="animate-pulse">
                    <path d="M 580,180 Q 400,50 200,180" stroke="#22C55E" strokeWidth="3" strokeDasharray="8 4" />
                    <text x="360" y="100" fill="#22C55E" fontSize="14" fontWeight="bold">✈️ PREMIUM AIR FREIGHT</text>
                 </g>
              )}
           </svg>
           
           {/* Map HUD Overlays */}
           <div className="absolute top-4 right-4 bg-slate-900/80 backdrop-blur border border-slate-700 rounded-lg p-3 w-48 shadow-lg text-slate-300">
              <h4 className="text-xs font-bold text-slate-100 uppercase tracking-wider mb-2 border-b border-slate-700 pb-2">Live Data Feeds</h4>
              <div className="space-y-2">
                 <div className="flex justify-between items-center text-xs"><span>NOAA Weather:</span><span className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_5px_#22C55E]"></span></div>
                 <div className="flex justify-between items-center text-xs"><span>AIS Marine:</span><span className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_5px_#22C55E]"></span></div>
                 <div className="flex justify-between items-center text-xs"><span>GeoNews NLP:</span><span className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_5px_#22C55E]"></span></div>
              </div>
           </div>
        </div>

        {/* Predictive AI Impact Panel */}
        <div className="space-y-6">
           
           <div className="bg-white border border-[var(--border-light)] rounded-xl shadow-sm overflow-hidden flex flex-col h-full">
              <div className="p-5 border-b border-slate-100 bg-red-50">
                 <h3 className="font-bold text-red-800 flex items-center">
                    <span className="text-xl mr-2">🚨</span> Critical Threat Detected
                 </h3>
                 <p className="text-xs text-red-600 mt-1">Cross-referenced against live Purchase Orders.</p>
              </div>

              <div className="p-5 space-y-6 flex-1 bg-white">
                 
                 <div className="border border-red-200 rounded-lg p-4 bg-white shadow-sm relative overflow-hidden">
                    <div className="absolute right-0 top-0 w-16 h-16 bg-red-50 rounded-bl-full -z-10"></div>
                    <div className="flex justify-between items-start mb-3">
                       <b className="text-sm text-slate-900">Typhoon Gaemi Intersection</b>
                       <span className="px-2 py-1 bg-red-100 text-red-700 text-[10px] font-bold rounded">ETA: 48h</span>
                    </div>
                    <p className="text-xs text-slate-600 mb-4 leading-relaxed">
                       A Category 4 Typhoon is forming in the South China Sea. Trajectory models predict a direct intersection with shipping lane <b className="text-slate-800">SCL-14</b>.
                    </p>
                    
                    <div className="bg-slate-50 border border-slate-200 p-3 rounded text-xs space-y-2">
                       <div className="font-bold text-slate-800 border-b border-slate-200 pb-1 mb-2">Blast Radius Analysis</div>
                       <div className="flex justify-between"><span>Vessel:</span><span className="font-mono text-slate-700">MSC Gulsun (IMO: 9839430)</span></div>
                       <div className="flex justify-between"><span>Cargo at Risk:</span><span className="font-bold text-red-600">42,000 ECUs</span></div>
                       <div className="flex justify-between"><span>Predicted Delay:</span><span className="font-bold text-red-600">14 Days</span></div>
                       <div className="flex justify-between"><span>Line-Stop Threat:</span><span className="font-bold text-red-600">Plant 4 (Texas)</span></div>
                    </div>
                 </div>

                 <div className="border-t border-slate-100 pt-6 relative">
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-white px-2 text-xs font-bold text-slate-400">AI AUTONOMOUS MITIGATION</div>
                    
                    <div className={`border rounded-lg p-4 mt-2 transition-all duration-500 ${mitigated ? 'bg-green-50 border-green-200' : 'bg-blue-50 border-blue-200 shadow-md'}`}>
                       <b className={`text-sm block mb-2 ${mitigated ? 'text-green-800' : 'text-blue-800'}`}>
                          {mitigated ? 'Mitigation Executed ✓' : 'Proposed Reroute Strategy'}
                       </b>
                       
                       {!mitigated ? (
                          <>
                             <p className="text-xs text-slate-700 mb-4 leading-relaxed">
                                Intercept <b className="text-slate-900">5,000 critical units</b> at the Shenzhen port before vessel loading. Redirect to premium air-freight via DHL Aviation.
                             </p>
                             <div className="flex justify-between text-xs mb-1"><span>Air Freight Cost:</span><span className="font-bold text-orange-600">+$14,000</span></div>
                             <div className="flex justify-between text-xs mb-4"><span>Line-Stop Avoided:</span><span className="font-bold text-green-600">-$2.4M</span></div>
                             
                             <button onClick={() => setMitigated(true)} className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 rounded-lg text-sm transition-colors shadow-sm flex items-center justify-center">
                                ⚡ Authorize Reroute
                             </button>
                          </>
                       ) : (
                          <div className="space-y-3">
                             <p className="text-xs text-green-700 leading-relaxed">
                                <b>Success:</b> 5,000 units successfully redirected to DHL Aviation. 
                             </p>
                             <div className="bg-white border border-green-100 p-3 rounded text-xs">
                                <div className="flex justify-between mb-1"><span>New ETA:</span><span className="font-bold">Next Tuesday</span></div>
                                <div className="flex justify-between"><span>Plant Status:</span><span className="font-bold text-green-600">Secured (No Line Stop)</span></div>
                             </div>
                             <button onClick={() => handleGenericAction('Track Air Shipment')}  className="w-full bg-white border border-slate-200 text-slate-600 font-medium py-2 rounded-lg text-sm transition-colors">
                                Track Air Shipment
                             </button>
                          </div>
                       )}
                    </div>
                 </div>

              </div>
           </div>

        </div>

      </div>
    </div>
  );
}
