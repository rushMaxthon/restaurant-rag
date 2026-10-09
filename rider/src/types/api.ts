/**
 * The rider API's shapes, mirrored from the backend (`app/schemas/rider.py`).
 * Money arrives as decimal strings; it is never added up here.
 */

export type RiderStatus = 'OFFLINE' | 'ONLINE' | 'ON_TRIP';
export type VehicleType = 'BIKE' | 'SCOOTER' | 'CYCLE';
export type TripStep =
  | 'to_pickup'
  | 'at_pickup'
  | 'to_drop'
  | 'at_drop'
  | 'done';
export type TripAction =
  | 'arrived-pickup'
  | 'picked-up'
  | 'arrived-drop'
  | 'delivered'
  | 'unavailable'
  | 'call-logged';

export type SessionUser = {
  id: string;
  full_name: string;
  phone_number: string | null;
  role: string;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  role: string;
  user: SessionUser;
};

export type RiderMe = {
  user_id: string;
  full_name: string;
  phone_number: string | null;
  vehicle_type: VehicleType;
  vehicle_number: string;
  city: string;
  status: RiderStatus;
  today_trips: number;
  today_earnings: string;
  fleet_enabled: boolean;
  /** What a delivery pays right now (admin-set): base + per km, never under minimum. */
  pay: { base: string; per_km: string; minimum: string };
};

export type Offer = {
  id: string;
  expires_at: string;
  seconds_left: number;
  total_seconds: number;
  restaurant_name: string;
  branch: string;
  pickup_address: string;
  pickup_distance_m: number | null;
  trip_distance_km: number;
  earning_estimate: string;
  drop_area: string;
  item_count: number;
};

/** An order a free rider may take from the list (backend `OpenOrderView`). */
export type OpenOrder = {
  order_id: string;
  restaurant_name: string;
  branch: string;
  pickup_address: string;
  pickup_distance_m: number | null;
  trip_distance_km: number;
  earning_estimate: string;
  drop_area: string;
  item_count: number;
  /** Until a courier is booked instead. */
  minutes_left: number;
  /** Offered to this rider first, and they let it run out or declined it. */
  missed: boolean;
};

export type TripStop = {
  name: string;
  address: string;
  phone: string;
  lat: number | null;
  lng: number | null;
  branch?: string | null;
  instructions?: string | null;
};

export type Trip = {
  id: string;
  order_id: string;
  order_code: string;
  step: TripStep;
  accepted_at: string;
  arrived_pickup_at: string | null;
  picked_up_at: string | null;
  arrived_drop_at: string | null;
  delivered_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
  call_attempts: number;
  distance_km: number;
  earning: string;
  otp_locked: boolean;
  otp_attempts_left: number;
  pickup: TripStop;
  drop: TripStop;
  items: { name: string; quantity: number }[];
  item_count: number;
};

export type EarningDay = { date: string; trips: number; amount: string };

export type Earnings = {
  today: string;
  today_trips: number;
  period_total: string;
  period_trips: number;
  unpaid: string;
  paid_total: string;
  days: EarningDay[];
};

/** A payment the admin recorded against this rider's trips (bank transfer, outside the app). */
export type Payout = {
  id: string;
  period_from: string;
  period_to: string;
  amount: string;
  trips: number;
  reference: string;
  paid_at: string;
};

export type LocationFix = {
  lat: number;
  lng: number;
  accuracy_m?: number | null;
  at: string;
};
