'use client';
import React from 'react';
import { Search, Filter, Factory, MapPin, Award } from 'lucide-react';

export default function Discovery() {
  const searchResults = [
    { name: "Precision Machining Solutions", certs: ["ISO 9001", "AS9100"], location: "USA", match: "98%" },
    { name: "EuroCast Dynamics", certs: ["ISO 9001", "IATF 16949"], location: "Germany", match: "92%" },
    { name: "Advanced Plastics PLC", certs: ["ISO 14001"], location: "UK", match: "85%" }
  ];

  return (
    <div className="space-y-6">
      <div className="text-center py-8">
        <h1 className="text-4xl font-bold text-[#0B2550] mb-4">Discover Global Suppliers</h1>
        <p className="text-gray-600 max-w-2xl mx-auto">Search by manufacturing capabilities, ISO certifications, ESG scores, and geographic location across our verified network.</p>
      </div>

      <div className="bg-white p-4 rounded-xl shadow-md max-w-4xl mx-auto flex gap-2">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-3 text-gray-400" size={20} />
          <input type="text" placeholder="e.g. '5-Axis CNC Aluminum' or 'AS9100 Certified'" className="w-full pl-10 pr-4 py-3 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <button className="px-6 py-3 bg-[#0B2550] text-white rounded-lg shadow font-semibold hover:bg-blue-900">
          Search Directory
        </button>
      </div>

      <div className="max-w-4xl mx-auto mt-8">
        <h2 className="text-lg font-bold text-gray-800 mb-4">Top Matches</h2>
        <div className="space-y-4">
          {searchResults.map((result, idx) => (
            <div key={idx} className="bg-white border border-gray-100 rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow flex justify-between items-center">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-blue-50 rounded-lg flex items-center justify-center text-blue-600">
                  <Factory size={24} />
                </div>
                <div>
                  <h3 className="font-bold text-lg text-[#0B2550]">{result.name}</h3>
                  <div className="flex items-center gap-4 text-sm text-gray-500 mt-1">
                    <span className="flex items-center gap-1"><MapPin size={14}/> {result.location}</span>
                    <span className="flex items-center gap-1"><Award size={14}/> {result.certs.join(', ')}</span>
                  </div>
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm text-gray-500 mb-1">Match Score</div>
                <div className="text-xl font-bold text-green-600 bg-green-50 inline-block px-3 py-1 rounded-full">{result.match}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
