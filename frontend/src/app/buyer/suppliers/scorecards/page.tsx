'use client';

import React, { useState } from 'react';
import { 
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer,
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend
} from 'recharts';
import { Award, AlertTriangle, ShieldCheck, TrendingUp, CheckCircle, Search, Filter } from 'lucide-react';

// Mock data for Supplier Scorecards
const suppliers = [
  {
    id: "SUP-001",
    name: "TechCorp Logistics",
    tier: "Tier 1",
    status: "Approved",
    overallScore: 92,
    metrics: {
      quality: 95,
      delivery: 98,
      cost: 85,
      innovation: 90,
      sustainability: 92
    },
    trend: [
      { month: "Jan", score: 88 },
      { month: "Feb", score: 89 },
      { month: "Mar", score: 90 },
      { month: "Apr", score: 91 },
      { month: "May", score: 91 },
      { month: "Jun", score: 92 }
    ]
  },
  {
    id: "SUP-042",
    name: "Global Metals Inc.",
    tier: "Tier 2",
    status: "Under Review",
    overallScore: 74,
    metrics: {
      quality: 70,
      delivery: 82,
      cost: 95,
      innovation: 60,
      sustainability: 65
    },
    trend: [
      { month: "Jan", score: 82 },
      { month: "Feb", score: 80 },
      { month: "Mar", score: 79 },
      { month: "Apr", score: 76 },
      { month: "May", score: 75 },
      { month: "Jun", score: 74 }
    ]
  },
  {
    id: "SUP-089",
    name: "Apex Tooling",
    tier: "Tier 1",
    status: "Approved",
    overallScore: 88,
    metrics: {
      quality: 90,
      delivery: 85,
      cost: 88,
      innovation: 95,
      sustainability: 82
    },
    trend: [
      { month: "Jan", score: 85 },
      { month: "Feb", score: 86 },
      { month: "Mar", score: 87 },
      { month: "Apr", score: 88 },
      { month: "May", score: 88 },
      { month: "Jun", score: 88 }
    ]
  }
];

export default function SupplierScorecards() {
  const [selectedId, setSelectedId] = useState(suppliers[0].id);
  const selectedSupplier = suppliers.find(s => s.id === selectedId) || suppliers[0];

  // Transform metrics object for RadarChart
  const radarData = [
    { subject: 'Quality', A: selectedSupplier.metrics.quality, fullMark: 100 },
    { subject: 'Delivery', A: selectedSupplier.metrics.delivery, fullMark: 100 },
    { subject: 'Cost Control', A: selectedSupplier.metrics.cost, fullMark: 100 },
    { subject: 'Innovation', A: selectedSupplier.metrics.innovation, fullMark: 100 },
    { subject: 'ESG / Sustain.', A: selectedSupplier.metrics.sustainability, fullMark: 100 },
  ];

  return (
    <div className="space-y-6">
      
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
          <Award size={32} />
          Supplier Performance Scorecards
        </h1>
        <p className="text-gray-500 mt-1">Multi-dimensional performance tracking and risk assessment.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        
        {/* Supplier List Sidebar */}
        <div className="lg:col-span-1 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col h-[700px]">
          <div className="p-4 border-b border-gray-100 flex items-center gap-2 bg-gray-50">
            <Search size={18} className="text-gray-400"/>
            <input 
              type="text" 
              placeholder="Search suppliers..." 
              className="bg-transparent border-none focus:ring-0 text-sm w-full outline-none"
            />
          </div>
          <div className="flex-1 overflow-y-auto divide-y divide-gray-50">
            {suppliers.map(sup => (
              <div 
                key={sup.id}
                onClick={() => setSelectedId(sup.id)}
                className={`p-4 cursor-pointer transition-colors hover:bg-blue-50 ${selectedId === sup.id ? 'bg-blue-50 border-l-4 border-[#0B2550]' : 'border-l-4 border-transparent'}`}
              >
                <div className="flex justify-between items-start mb-1">
                  <span className="font-bold text-[#0B2550]">{sup.name}</span>
                  <span className={`text-xs font-bold px-2 py-0.5 rounded ${sup.overallScore >= 90 ? 'bg-green-100 text-green-700' : sup.overallScore >= 80 ? 'bg-blue-100 text-blue-700' : 'bg-red-100 text-red-700'}`}>
                    {sup.overallScore}
                  </span>
                </div>
                <div className="text-xs text-gray-500 flex justify-between">
                  <span>{sup.tier}</span>
                  <span className={sup.status === 'Approved' ? 'text-green-600' : 'text-amber-600'}>{sup.status}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Scorecard Detail View */}
        <div className="lg:col-span-3 space-y-6 overflow-y-auto h-[700px] pr-2">
          
          {/* Supplier Header Card */}
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 flex justify-between items-center">
            <div>
              <h2 className="text-2xl font-black text-[#0B2550]">{selectedSupplier.name}</h2>
              <div className="flex items-center gap-4 mt-2 text-sm text-gray-600">
                <span className="flex items-center gap-1 font-bold"><BriefcaseIcon /> {selectedSupplier.tier}</span>
                <span className="flex items-center gap-1"><IdCardIcon /> {selectedSupplier.id}</span>
              </div>
            </div>
            <div className="text-right flex items-center gap-4">
              {selectedSupplier.overallScore >= 90 && <ShieldCheck size={48} className="text-green-500" />}
              {selectedSupplier.overallScore >= 80 && selectedSupplier.overallScore < 90 && <CheckCircle size={48} className="text-blue-500" />}
              {selectedSupplier.overallScore < 80 && <AlertTriangle size={48} className="text-amber-500" />}
              
              <div className="flex flex-col">
                <span className="text-gray-500 text-sm font-bold uppercase tracking-wider">Overall Score</span>
                <span className={`text-4xl font-black ${selectedSupplier.overallScore >= 90 ? 'text-green-600' : selectedSupplier.overallScore >= 80 ? 'text-blue-600' : 'text-amber-600'}`}>
                  {selectedSupplier.overallScore}<span className="text-lg text-gray-400">/100</span>
                </span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Radar Chart */}
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 h-80 flex flex-col">
              <h3 className="font-bold text-gray-800 border-b border-gray-100 pb-2 mb-4">Performance Dimensions</h3>
              <div className="flex-1">
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart cx="50%" cy="50%" outerRadius="75%" data={radarData}>
                    <PolarGrid stroke="#e5e7eb" />
                    <PolarAngleAxis dataKey="subject" tick={{ fill: '#4b5563', fontSize: 12, fontWeight: 'bold' }} />
                    <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
                    <Radar
                      name="Score"
                      dataKey="A"
                      stroke="#0B2550"
                      fill="#3b82f6"
                      fillOpacity={0.5}
                    />
                    <RechartsTooltip />
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Historical Trend */}
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 h-80 flex flex-col">
              <h3 className="font-bold text-gray-800 border-b border-gray-100 pb-2 mb-4">Historical Trend (6 Months)</h3>
              <div className="flex-1">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={selectedSupplier.trend} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
                    <XAxis dataKey="month" tick={{fill: '#6b7280', fontSize: 12}} axisLine={false} tickLine={false} />
                    <YAxis domain={[0, 100]} tick={{fill: '#6b7280', fontSize: 12}} axisLine={false} tickLine={false} />
                    <RechartsTooltip />
                    <Line 
                      type="monotone" 
                      dataKey="score" 
                      stroke="#0B2550" 
                      strokeWidth={3}
                      dot={{ r: 4, fill: '#0B2550', strokeWidth: 2, stroke: '#fff' }} 
                      activeDot={{ r: 6 }} 
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Corrective Action Plan */}
          {selectedSupplier.overallScore < 80 && (
            <div className="bg-amber-50 border border-amber-200 p-6 rounded-xl shadow-sm flex items-start gap-4">
              <div className="bg-amber-100 p-3 rounded-full text-amber-600">
                <AlertTriangle size={24} />
              </div>
              <div>
                <h4 className="font-bold text-amber-900 text-lg">Corrective Action Plan Required</h4>
                <p className="text-amber-800 text-sm mt-1 mb-4">
                  {selectedSupplier.name} has fallen below the 80-point threshold primarily due to declining Innovation and Sustainability metrics. A Supplier Corrective Action Request (SCAR) has been drafted.
                </p>
                <button onClick={() => alert('Issuing SCAR Document...')} className="bg-amber-600 text-white px-4 py-2 rounded font-bold shadow hover:bg-amber-700 transition-colors">
                  Issue SCAR Document
                </button>
              </div>
            </div>
          )}

          {selectedSupplier.overallScore >= 90 && (
            <div className="bg-green-50 border border-green-200 p-6 rounded-xl shadow-sm flex items-start gap-4">
              <div className="bg-green-100 p-3 rounded-full text-green-600">
                <Award size={24} />
              </div>
              <div>
                <h4 className="font-bold text-green-900 text-lg">Preferred Supplier Status</h4>
                <p className="text-green-800 text-sm mt-1 mb-4">
                  {selectedSupplier.name} is maintaining excellent performance across all dimensions, qualifying them for automated PO approvals up to $50,000.
                </p>
                <button onClick={() => alert('Opening Contract Renewal Form...')} className="bg-green-600 text-white px-4 py-2 rounded font-bold shadow hover:bg-green-700 transition-colors">
                  Review Contract Renewal
                </button>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}

// Simple icons to avoid extra lucide imports
function BriefcaseIcon() {
  return <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path></svg>;
}
function IdCardIcon() {
  return <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><circle cx="9" cy="11" r="2"></circle><path d="M15 11h4"></path><path d="M15 15h4"></path><path d="M9 15c-1.5 0-3 1-3 2v1h6v-1c0-1-1.5-2-3-2z"></path></svg>;
}
