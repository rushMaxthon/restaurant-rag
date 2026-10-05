/**
 * @format
 */

import { AppRegistry } from 'react-native';
import App from './App';
import { name as appName } from './app.json';
import { registerBackgroundHandlers } from './src/services/pushNotifications';

// Before the app registers: a push that arrives, or a notification that is
// tapped, while the app is in the background or closed is handled here.
registerBackgroundHandlers();

AppRegistry.registerComponent(appName, () => App);
