/**
 * @format
 */

import { AppRegistry } from 'react-native';
import App from './App';
import { name as appName } from './app.json';
import { registerShiftService } from './src/services/shiftService';
import { registerBackgroundPush } from './src/services/push';

// Before the app renders: Android may start the foreground service's task
// while the UI is not up, and the task must already be registered.
registerShiftService();
// Same reason: a push can start a killed app headless, before any screen.
registerBackgroundPush();

AppRegistry.registerComponent(appName, () => App);
