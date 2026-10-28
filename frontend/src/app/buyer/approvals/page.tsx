'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileSignature, CheckCircle, XCircle, AlertCircle, Activity } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, ComposedChart, Line } from 'recharts';

export default function PendingApprovalsPage() {
  const [showAnalytics, setShowAnalytics] = useState(true);

  const { data: pos, isLoading } = useQuery({
    queryKey: ['pending-approvals'],
    queryFn: async () => {
      const res = await fetch(`http://localhost:8080/api/v1/actions/pending-approvals?tenant_id=BUYER-ORG-001`);
      return res.json();
    }
  });

  const { data: analytics } = useQuery({
    queryKey: ['approvals-analytics'],
    queryFn: async () => {
      const res = await fetch('http://localhost:8080/api/v1/analytics-hub/approvals');
      return res.json();
    }
  });

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
            <FileSignature size={32} />
            Orders & Approvals
          </h1>
          <p className="text-gray-500 mt-1">Review pending POs and analyze procurement workflow bottlenecks.</p>
        </div>
        <button 
          onClick={() => setShowAnalytics(!showAnalytics)} 
          className="bg-white text-[#0B2550] border border-[#0B2550] px-4 py-2 rounded-lg font-bold shadow-sm hover:bg-gray-50 flex items-center gap-2"
        >
          <Activity size={18} /> {showAnalytics ? 'Hide Analytics' : 'Show Pipeline Analytics'}
        </button>
      </div>

      {showAnalytics && analytics && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 animate-in fade-in slide-in-from-top-4">
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 h-72 flex flex-col">
            <h3 className="font-bold text-gray-800 mb-4">Procurement Funnel (YTD)</h3>
            <div className="flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={analytics.rfq_funnel} layout="vertical" margin={{ top: 0, right: 20, bottom: 0, left: 10 }}>
                  <XAxis type="number" hide />
                  <YAxis dataKey="stage" type="category" axisLine={false} tickLine={false} tick={{fill: '#6b7280', fontSize: 12}} width={80}/>
                  <RechartsTooltip cursor={{fill: '#f3f4f6'}} />
                  <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]} barSize={20} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 h-72 flex flex-col">
            <h3 className="font-bold text-gray-800 mb-4">Approval Cycle Time by Department</h3>
            <div className="flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analytics.cycle_time_days} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="department" tick={{fill: '#6b7280', fontSize: 12}} axisLine={false} tickLine={false} />
                  <YAxis tick={{fill: '#6b7280', fontSize: 12}} axisLine={false} tickLine={false} />
                  <RechartsTooltip cursor={{fill: 'transparent'}} />
                  <Bar dataKey="avg_days" name="Avg Days" fill="#f59e0b" radius={[4, 4, 0, 0]} barSize={30} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* Existing Approvals Table */}
      <div className="bg-white rounded-xl shadow-md overflow-hidden">
        <div className="p-4 bg-gray-50 border-b border-gray-100 flex justify-between items-center">
           <h2 className="font-bold text-gray-800 flex items-center gap-2"><AlertCircle size={18} className="text-amber-500"/> Action Required: Pending POs</h2>
        </div>
        {isLoading ? <div className="p-8 text-center text-gray-500">Loading...</div> : (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b-2 border-gray-100">
                <th className="p-4 text-sm font-semibold text-gray-600">PO Number</th>
                <th className="p-4 text-sm font-semibold text-gray-600">Amount</th>
                <th className="p-4 text-sm font-semibold text-gray-600 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {pos?.map((po: any) => (
                <tr key={po.id} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="p-4 font-bold text-[#0B2550]">{po.po_number}</td>
                  <td className="p-4 font-bold text-gray-800">${po.total_amount.toLocaleString()}</td>
                  <td className="p-4 text-right flex justify-end gap-2">
                     <button onClick={()=>alert('Rejected')} className="px-4 py-1.5 text-red-600 border border-red-200 hover:bg-red-50 font-bold rounded flex items-center gap-1 text-sm"><XCircle size={14}/> Reject</button>
                     <button onClick={()=>alert('Approved')} className="px-4 py-1.5 bg-[#0B2550] text-white hover:bg-blue-900 font-bold rounded flex items-center gap-1 text-sm"><CheckCircle size={14}/> Approve</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
