'use client';

import React, { useState } from 'react';
import { ShieldCheck, Box, Search, Fingerprint, Network, Factory, Activity } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, BarChart, Bar, Legend } from 'recharts';

export default function BuyerTraceability() {
  const [searchTerm, setSearchTerm] = useState('RAW-AL-001');
  const [itemId, setItemId] = useState('RAW-AL-001');
  const [showAnalytics, setShowAnalytics] = useState(false);

  const { data: traceability, isLoading, refetch } = useQuery({
    queryKey: ['traceability', itemId],
    queryFn: async () => {
      const res = await fetch(`http://localhost:8080/api/v1/blockchain/traceability/${itemId}`);
      return res.json();
    }
  });

  const { data: analytics } = useQuery({
    queryKey: ['blockchain-analytics'],
    queryFn: async () => {
      const res = await fetch('http://localhost:8080/api/v1/analytics-hub/blockchain');
      return res.json();
    }
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setItemId(searchTerm);
    refetch();
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
            <Fingerprint size={32} className="text-blue-600" />
            Immutable Traceability
          </h1>
          <p className="text-gray-500 mt-1">Audit material provenance and monitor ledger performance.</p>
        </div>
        <button 
          onClick={() => setShowAnalytics(!showAnalytics)} 
          className="bg-white text-[#0B2550] border border-[#0B2550] px-4 py-2 rounded-lg font-bold shadow-sm hover:bg-gray-50 flex items-center gap-2"
        >
          <Activity size={18} /> {showAnalytics ? 'Hide Network Analytics' : 'Show Network Analytics'}
        </button>
      </div>

      {showAnalytics && analytics && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 animate-in fade-in slide-in-from-top-4">
          <div className="bg-gray-900 rounded-xl shadow-lg border border-gray-800 p-6 h-72 flex flex-col">
            <h3 className="font-bold text-gray-200 mb-2">Settlement Volume: Traditional vs Smart Contract</h3>
            <div className="flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={analytics.execution_volume} margin={{ top: 10, right: 30, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#374151" />
                  <XAxis dataKey="month" tick={{fill: '#9ca3af'}} axisLine={false} tickLine={false} />
                  <YAxis tick={{fill: '#9ca3af'}} axisLine={false} tickLine={false} />
                  <RechartsTooltip contentStyle={{backgroundColor: '#1f2937', border: 'none', color: '#fff'}} />
                  <Legend />
                  <Area type="monotone" dataKey="smart_contract" stackId="1" stroke="#10b981" fill="#10b981" name="Smart Contracts" />
                  <Area type="monotone" dataKey="traditional_ach" stackId="1" stroke="#3b82f6" fill="#3b82f6" name="Traditional ACH" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="bg-gray-900 rounded-xl shadow-lg border border-gray-800 p-6 h-72 flex flex-col">
            <h3 className="font-bold text-gray-200 mb-2">Network Validation Latency</h3>
            <div className="flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analytics.validation_speed} margin={{ top: 20, right: 30, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#374151" />
                  <XAxis dataKey="node_region" tick={{fill: '#9ca3af', fontSize: 12}} axisLine={false} tickLine={false} />
                  <YAxis tick={{fill: '#9ca3af'}} axisLine={false} tickLine={false} />
                  <RechartsTooltip cursor={{fill: '#374151'}} contentStyle={{backgroundColor: '#1f2937', border: 'none', color: '#fff'}} />
                  <Bar dataKey="avg_ms" name="Avg Latency (ms)" fill="#8b5cf6" radius={[4, 4, 0, 0]} barSize={40} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* Existing Search UI */}
      <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
        <form onSubmit={handleSearch} className="flex gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-3 text-gray-400" size={18} />
            <input type="text" value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-[#0B2550]" placeholder="Enter Item ID or SKU" />
          </div>
          <button type="submit" className="bg-[#0B2550] text-white px-6 py-2 rounded-lg font-bold shadow hover:bg-blue-900">Audit Provenance</button>
        </form>
      </div>

      {isLoading ? <div className="p-12 text-center text-gray-500">Querying Blockchain Ledger...</div> : traceability?.provenance ? (
        <div className="bg-gray-50 rounded-xl p-8 border border-gray-200 shadow-inner">
           <h2 className="text-xl font-bold text-gray-800 mb-8 flex items-center gap-2"><Network /> Provenance Chain for {traceability.item_id}</h2>
           <div className="relative border-l-4 border-blue-500 ml-6 space-y-12">
             {traceability.provenance.map((block: any, idx: number) => (
               <div key={block.index} className="relative pl-8">
                 <div className="absolute -left-5 top-0 w-8 h-8 bg-blue-600 rounded-full border-4 border-white shadow-md flex items-center justify-center text-white">{idx === 0 ? <Factory size={14}/> : <Box size={14}/>}</div>
                 <div className="bg-white p-6 rounded-xl shadow-md border border-gray-200 hover:shadow-lg transition-shadow">
                    <div className="flex justify-between items-start mb-4 border-b border-gray-100 pb-2">
                       <h3 className="font-black text-lg text-[#0B2550]">{block.data.event}</h3>
                       <div className="text-right"><span className="text-xs text-gray-500 font-mono">Block #{block.index}</span><p className="text-xs text-gray-400">{new Date(block.timestamp).toLocaleString()}</p></div>
                    </div>
                    <div className="bg-gray-50 p-3 rounded-lg border border-gray-100 font-mono text-[10px] break-all mb-4">
                      <div className="text-gray-400 mb-1"><span className="text-blue-600 font-bold">Hash:</span> {block.hash}</div>
                      <div className="text-gray-400"><span className="text-gray-500 font-bold">Prev:</span> {block.previous_hash}</div>
                    </div>
                    <div className="flex items-center gap-2 text-green-600 text-xs font-bold uppercase"><ShieldCheck size={16} /> Verified on Ledger</div>
                 </div>
               </div>
             ))}
           </div>
        </div>
      ) : null}
    </div>
  );
}
