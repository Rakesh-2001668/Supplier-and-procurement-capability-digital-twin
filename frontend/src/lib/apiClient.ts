import axios from 'axios';

export const apiClient = axios.create({
  baseURL: 'http://localhost:8080',
});

// Interceptor to add JWT token
apiClient.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// Fallbacks for components that still hardcode ?tenant_id=... until fully refactored
export const TEST_TENANT_ID = typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || "TENANT_BUYER_001" : "TENANT_BUYER_001";
export const TEST_SUPPLIER_TENANT_ID = typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || "TENANT_SUPPLIER_001" : "TENANT_SUPPLIER_001";
