/**
 * @format
 */

import { AppRegistry } from 'react-native';
import notifee from '@notifee/react-native';
import App from './App';
import { name as appName } from './app.json';
import {
  handleNotifeeEvent,
  registerBackgroundRemoteMessageHandler,
} from './src/services/pushNotifications';

registerBackgroundRemoteMessageHandler();
notifee.onBackgroundEvent(handleNotifeeEvent);
AppRegistry.registerComponent(appName, () => App);
