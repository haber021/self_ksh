// API Configuration
// ===================
// IMPORTANT: Update this with your Django server URL
//
// For local development (testing on physical device):
//   1. Find your computer's IP address:
//      - Windows: ipconfig (look for IPv4 Address)
//      - Mac/Linux: ifconfig or ip addr
//   2. Make sure your phone and computer are on the same Wi-Fi network
//   3. Update LOCAL_IP below (e.g., 'http://192.168.1.100:8000')
//
// For Android Emulator:
//   - Change LOCAL_IP to 'http://10.0.2.2:8000'
//
// For iOS Simulator:
//   - Change LOCAL_IP to 'http://localhost:8000'
//
// For production:
//   Option 1: If you have a production server with domain/IP:
//     - Set PRODUCTION_URL to your server URL (e.g., 'https://api.yourdomain.com' or 'http://your-server-ip:8000')
//   Option 2: If testing APK and connecting to local server (same network):
//     - Set PRODUCTION_URL to your computer's IP address (same as LOCAL_IP)
//     - Make sure Django server is running and accessible from mobile device
//   Option 3: If deploying to cloud (Heroku, AWS, etc.):
//     - Set PRODUCTION_URL to your cloud server URL (e.g., 'https://your-app.herokuapp.com')

// Default configuration - UPDATE THIS!
const LOCAL_IP = 'http://172.16.37.58:8000'; // ⚠️ Your computer's IP address for development
const PRODUCTION_URL = 'http://172.16.37.58:8000'; // ⚠️ For APK: Use your server IP/domain here
// Examples:
//   - Local testing: 'http://172.16.37.58:8000' (your current IP)
//   - Production: 'https://api.yourdomain.com' or 'http://your-server-ip:8000'
//   - Cloud: 'https://your-app.herokuapp.com'

// Auto-select URL based on environment
// In production APK builds, __DEV__ is false, so PRODUCTION_URL will be used
// For development with Expo Go, __DEV__ is true, so LOCAL_IP will be used
export const API_BASE_URL = __DEV__ ? LOCAL_IP : PRODUCTION_URL;

// Export both URLs for debugging
export const getApiUrl = () => API_BASE_URL;
export const getLocalUrl = () => LOCAL_IP;
export const getProductionUrl = () => PRODUCTION_URL;

export const API_ENDPOINTS = {
  LOGIN: `${API_BASE_URL}/api/mobile/login/`,
  ACCOUNT_INFO: `${API_BASE_URL}/api/mobile/account/`,
  ACCOUNT_SUMMARY: `${API_BASE_URL}/api/mobile/account/summary/`,
  TRANSACTIONS: `${API_BASE_URL}/api/mobile/transactions/`,
  BALANCE_TRANSACTIONS: `${API_BASE_URL}/api/mobile/balance-transactions/`,
};

