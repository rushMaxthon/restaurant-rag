# Push Notifications Phase 1

This document describes the Phase 1 customer push notification scope for the Restaurant RAG platform.

Phase 1 includes only:

- payment success plus order placed notifications sent automatically after a successful prepaid order

It does not include the full notification event matrix yet.

## Supported Event

### Payment Success + Order Placed

Trigger:

- online payment succeeds
- order creation succeeds
- payment method is not `COD`

Payload fields:

```json
{
  "notification_type": "order_placed",
  "order_id": "order-uuid",
  "title": "✅ Order Placed Successfully",
  "body": "Your payment was successful and your order has been placed."
}
```

Mobile behavior on tap:

- opens `OrderDetail`
- passes the exact `orderId`
- avoids landing on `Home` first by resetting the stack directly to the target route

## End-to-End Flow

### Automatic Order Placed Notification

1. Customer completes online payment
2. Backend creates the order successfully
3. `backend/app/services/orders.py` triggers `send_order_placed_notification(...)`
4. Backend sends the FCM payload with:
   - `notification_type = order_placed`
   - `order_id`
5. Mobile routes the tap directly to `OrderDetail`

## Deep Linking

Deep linking is handled in:

- `mobile/src/services/pushNotifications.ts`
- `mobile/src/navigation/navigationService.ts`

The mobile app supports notification taps from:

- foreground local notifications through Notifee press events
- background remote notification opens through `messaging().onNotificationOpenedApp(...)`
- killed-state remote notification opens through `messaging().getInitialNotification()`

Supported deep link target in Phase 1:

- `order_details` behavior derived from `notification_type = order_placed`

## Backend APIs

### Register Device Token

`POST /api/notifications/device-tokens`

Authenticated mobile customers register:

- `installation_id`
- `fcm_token`
- `platform`

### Notification History

`GET /api/admin/notifications/history`

Stored history includes:

- title
- message
- audience
- notification type
- deep link type
- order id
- target user count
- sent count
- success count
- failure count
- creator
- created time

## Verification Notes

Backend verification completed for Phase 1:

- controlled `order_placed` notification succeeded against a live registered device token with:
  - `notification_type = order_placed`
  - `order_id`

Mobile compile verification completed:

- `./node_modules/.bin/tsc --noEmit` in `mobile`

Backend compile verification completed:

- `python3 -m compileall backend/app`

Foreground/background/killed-state routing is implemented in code, but final visual confirmation still depends on testing on real Android and iOS devices with live pushes.
