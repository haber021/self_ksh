import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_BASE_URL, API_ENDPOINTS } from '../config';

// Create axios instance with default config
// Use dynamic baseURL to handle connection issues better
const getBaseURL = () => {
  // Always use the configured API_BASE_URL
  return API_BASE_URL;
};

const api = axios.create({
  baseURL: getBaseURL(),
  timeout: 20000, // Increased timeout for slower networks and mobile connections
  withCredentials: true, // Important for session cookies
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  },
  // Add retry configuration
  validateStatus: function (status) {
    return status < 500; // Don't throw for 4xx errors, only 5xx
  },
});

// Add request interceptor to include session cookie
api.interceptors.request.use(
  async (config) => {
    // Session cookies are handled automatically by axios with withCredentials
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Add response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      // Unauthorized - clear storage and redirect to login
      await AsyncStorage.removeItem('memberData');
    }
    
    // Improve error messages
    if (error.code === 'ECONNABORTED') {
      error.message = 'Request timeout. Please check your connection and try again.';
    } else if (error.code === 'ERR_NETWORK' || !error.response) {
      error.message = 'Network error. Please check your internet connection and server URL.';
    } else if (error.response?.status >= 500) {
      error.message = 'Server error. Please try again later.';
    }
    
    return Promise.reject(error);
  }
);

// Helper function to test API connectivity with multiple attempts
const testConnection = async (maxAttempts = 3) => {
  const baseURL = getBaseURL();
  
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      // Try to reach the root API endpoint or a simple endpoint
      // Use a shorter timeout for connection test
      const testUrl = baseURL.replace(/\/$/, '') + '/api/mobile/';
      
      try {
        // Try to hit the mobile API base path
        const response = await axios.get(testUrl, {
          timeout: 8000,
          validateStatus: () => true, // Accept any status code
        });
        
        // If we get any response (even 404/405), server is reachable
        return { connected: true, url: baseURL };
      } catch (testError) {
        // Try alternative: check if we can reach the Django admin (always exists)
        const adminUrl = baseURL.replace(/\/$/, '') + '/admin/';
        try {
          await axios.get(adminUrl, {
            timeout: 8000,
            validateStatus: () => true,
          });
          return { connected: true, url: baseURL };
        } catch (adminError) {
          // Both failed, check error type
          if (adminError.code === 'ERR_NETWORK' || adminError.code === 'ECONNABORTED' || !adminError.response) {
            // Network error - server unreachable
            if (attempt < maxAttempts) {
              // Wait before retry (exponential backoff)
              await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
              continue;
            }
            return { 
              connected: false, 
              url: baseURL,
              error: 'Cannot reach server. Check:\n• Internet connection\n• Server is running\n• Server URL is correct'
            };
          }
          // Got a response (even error), server is reachable
          return { connected: true, url: baseURL };
        }
      }
    } catch (error) {
      // If we get a response (even 404/405/500), server is reachable
      if (error.response) {
        return { connected: true, url: baseURL };
      }
      
      // Network error - server unreachable
      if (error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED' || !error.response) {
        if (attempt < maxAttempts) {
          // Wait before retry
          await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
          continue;
        }
        return { 
          connected: false, 
          url: baseURL,
          error: error.message || 'Network error. Please check your connection.'
        };
      }
      
      // Other errors - assume server is reachable
      return { connected: true, url: baseURL };
    }
  }
  
  return { 
    connected: false, 
    url: baseURL,
    error: 'Connection failed after multiple attempts'
  };
};

export const authService = {
  async checkConnection() {
    const result = await testConnection();
    return result.connected;
  },
  
  async checkConnectionDetailed() {
    return await testConnection();
  },

  async login(username, pin, retries = 2) {
    let lastError;
    
    // Validate input before making request
    if (!username || !username.trim()) {
      throw 'Username is required';
    }
    
    if (!pin || !pin.trim()) {
      throw 'PIN is required';
    }
    
    if (!/^\d{4}$/.test(pin)) {
      throw 'PIN must be exactly 4 digits';
    }
    
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const response = await api.post(API_ENDPOINTS.LOGIN, {
          username: username.trim(),
          pin: pin.trim(),
        });
        
        if (response.data.success) {
          // Store member data
          await AsyncStorage.setItem('memberData', JSON.stringify(response.data.member));
          // Store session info if provided
          if (response.data.session_id) {
            await AsyncStorage.setItem('sessionId', response.data.session_id);
          }
          return response.data;
        }
        
        // If login failed but we got a response, return the error
        throw new Error(response.data.error || 'Login failed');
      } catch (error) {
        lastError = error;
        
        // Handle specific error status codes
        if (error.response?.status === 400) {
          // Bad request - validation error
          throw error.response?.data?.error || 'Invalid input. Please check your username and PIN.';
        }
        
        if (error.response?.status === 401) {
          // Unauthorized - invalid credentials
          throw error.response?.data?.error || 'Invalid username or PIN. Please try again.';
        }
        
        if (error.response?.status === 403) {
          // Forbidden - account inactive
          throw error.response?.data?.error || 'Your account is inactive. Please contact administrator.';
        }
        
        if (error.response?.status === 404) {
          // Not found - member doesn't exist
          throw error.response?.data?.error || 'User not found. Please check your username.';
        }
        
        if (error.response?.status === 500) {
          // Server error
          throw error.response?.data?.error || 'Server error. Please try again later.';
        }
        
        // Don't retry on client errors (4xx)
        if (error.response?.status >= 400 && error.response?.status < 500) {
          throw error.response?.data?.error || error.message || 'Login failed';
        }
        
        // Retry on network errors or server errors (5xx)
        if (attempt < retries && (error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED' || (error.response?.status >= 500))) {
          // Wait a bit before retrying (exponential backoff)
          await new Promise(resolve => setTimeout(resolve, 1000 * (attempt + 1)));
          continue;
        }
        
        // Format error message
        if (error.response?.data?.error) {
          throw error.response.data.error;
        }
        
        if (error.code === 'ERR_NETWORK' || !error.response) {
          const connectionTest = await testConnection(1);
          if (!connectionTest.connected) {
            throw `Cannot connect to server at ${getBaseURL()}\n\nPlease check:\n• Your internet connection\n• Server is running\n• Server URL is correct\n• Both devices are on same network (if using local IP)`;
          }
          throw 'Network error occurred. Please try again.';
        }
        
        throw error.message || 'Login failed. Please try again.';
      }
    }
    
    throw lastError?.message || 'Login failed after multiple attempts';
  },

  async logout() {
    await AsyncStorage.removeItem('memberData');
  },

  async getStoredMember() {
    const memberData = await AsyncStorage.getItem('memberData');
    return memberData ? JSON.parse(memberData) : null;
  },
};

export const accountService = {
  async getAccountInfo() {
    try {
      const response = await api.get(API_ENDPOINTS.ACCOUNT_INFO);
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to fetch account info';
    }
  },

  async getAccountSummary(year = null, month = null) {
    try {
      const params = {};
      if (year) params.year = year;
      if (month) params.month = month;
      const response = await api.get(API_ENDPOINTS.ACCOUNT_SUMMARY, { params });
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to fetch account summary';
    }
  },

  async getTransactionHistory(page = 1, limit = 20) {
    try {
      const response = await api.get(API_ENDPOINTS.TRANSACTIONS, {
        params: { page, limit },
      });
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to fetch transactions';
    }
  },

  async getBalanceTransactions(page = 1, limit = 20) {
    try {
      const response = await api.get(API_ENDPOINTS.BALANCE_TRANSACTIONS, {
        params: { page, limit },
      });
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to fetch balance transactions';
    }
  },
};

export default api;

