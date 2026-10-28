'use client';
import React, { useState } from 'react';
import Link from 'next/link';
import { Factory, Briefcase, Truck, ArrowRight } from 'lucide-react';
import { useRouter } from 'next/navigation';

export default function Register() {
  const router = useRouter();
  const [accountType, setAccountType] = useState<'buyer' | 'supplier' | null>(null);

  const handleRegister = (e: React.FormEvent) => {
    e.preventDefault();
    if (accountType === 'buyer') {
      localStorage.setItem('app_role', 'buyer');
      router.push('/buyer/dashboard');
    } else {
      localStorage.setItem('app_role', 'supplier');
      router.push('/supplier/dashboard');
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-3xl">
        <div className="flex justify-center text-[#0B2550]">
          <Factory size={48} />
        </div>
        <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
          Join the Digital Supply Chain
        </h2>
        <p className="mt-2 text-center text-sm text-gray-600 mb-8">
          Already have an account?{' '}
          <Link href="/login" className="font-medium text-blue-600 hover:text-blue-500">
            Log in here
          </Link>
        </p>

        <div className="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10 border-t-4 border-[#0B2550]">
          
          <div className="mb-8">
            <h3 className="text-lg font-medium text-gray-900 mb-4 text-center">1. Select your Organization Type</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Buyer Option */}
              <div 
                className={`border-2 rounded-xl p-6 cursor-pointer transition-all ${accountType === 'buyer' ? 'border-[#0B2550] bg-blue-50 shadow-md' : 'border-gray-200 hover:border-blue-300'}`}
                onClick={() => setAccountType('buyer')}
              >
                <Briefcase size={32} className={accountType === 'buyer' ? 'text-[#0B2550]' : 'text-gray-400'} />
                <h4 className={`mt-4 text-xl font-bold ${accountType === 'buyer' ? 'text-[#0B2550]' : 'text-gray-700'}`}>Enterprise Buyer</h4>
                <p className="mt-2 text-sm text-gray-500">I want to discover suppliers, issue RFQs, and manage my procurement lifecycle.</p>
              </div>

              {/* Supplier Option */}
              <div 
                className={`border-2 rounded-xl p-6 cursor-pointer transition-all ${accountType === 'supplier' ? 'border-green-600 bg-green-50 shadow-md' : 'border-gray-200 hover:border-green-300'}`}
                onClick={() => setAccountType('supplier')}
              >
                <Truck size={32} className={accountType === 'supplier' ? 'text-green-600' : 'text-gray-400'} />
                <h4 className={`mt-4 text-xl font-bold ${accountType === 'supplier' ? 'text-green-700' : 'text-gray-700'}`}>Manufacturing Supplier</h4>
                <p className="mt-2 text-sm text-gray-500">I want to showcase my machinery capabilities, receive orders, and get paid.</p>
              </div>
            </div>
          </div>

          {accountType && (
            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
              <h3 className="text-lg font-medium text-gray-900 mb-4 border-t pt-6">2. Create Organization Details</h3>
              <form className="space-y-6" onSubmit={handleRegister}>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Company Name</label>
                    <input type="text" required className="mt-1 focus:ring-blue-500 focus:border-blue-500 block w-full shadow-sm sm:text-sm border-gray-300 rounded-md py-2 px-3 border" placeholder="e.g. Acme Corp" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Work Email</label>
                    <input type="email" required className="mt-1 focus:ring-blue-500 focus:border-blue-500 block w-full shadow-sm sm:text-sm border-gray-300 rounded-md py-2 px-3 border" placeholder="you@company.com" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Password</label>
                    <input type="password" required className="mt-1 focus:ring-blue-500 focus:border-blue-500 block w-full shadow-sm sm:text-sm border-gray-300 rounded-md py-2 px-3 border" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700">{accountType === 'supplier' ? 'Tax ID / Registration No.' : 'Department'}</label>
                    <input type="text" required className="mt-1 focus:ring-blue-500 focus:border-blue-500 block w-full shadow-sm sm:text-sm border-gray-300 rounded-md py-2 px-3 border" />
                  </div>
                </div>

                <div className="pt-4">
                  <button
                    type="submit"
                    className={`w-full flex justify-center items-center py-3 px-4 border border-transparent rounded-md shadow-sm text-lg font-medium text-white focus:outline-none focus:ring-2 focus:ring-offset-2 ${
                      accountType === 'buyer' 
                        ? 'bg-[#0B2550] hover:bg-blue-900 focus:ring-blue-500' 
                        : 'bg-green-700 hover:bg-green-800 focus:ring-green-500'
                    }`}
                  >
                    Create {accountType === 'buyer' ? 'Buyer' : 'Supplier'} Account <ArrowRight className="ml-2" size={20} />
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
