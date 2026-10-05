import { Platform } from 'react-native';

// The Android emulator reaches the host machine through 10.0.2.2; the iOS
// simulator shares the host's loopback. A physical device on the Wi-Fi needs
// the Mac's LAN address here instead (and the backend started with
// --host 0.0.0.0). A native app is not subject to CORS, so no backend
// setting is involved.
const DEV_HOST = Platform.OS === 'android' ? '10.0.2.2' : 'localhost';

const DEV_API_BASE_URL = `http://${DEV_HOST}:8000/api`;

// Release builds. The same Render API the web board's production build uses
// (frontend-kitchen/src/lib/api.ts) — Render mints a new suffix whenever the
// service is recreated, so re-check both when that happens. HTTPS matters
// beyond security: Android release builds refuse plain http outright.
const PROD_API_BASE_URL = 'https://restaurant-rag-api-oj8p.onrender.com/api';

export const API_BASE_URL = __DEV__ ? DEV_API_BASE_URL : PROD_API_BASE_URL;
