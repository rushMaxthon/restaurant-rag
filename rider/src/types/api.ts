/**
 * The rider API's shapes, mirrored from the backend (`app/schemas/rider.py`).
 * Money arrives as decimal strings; it is never added up here.
 */

export type RiderStatus = 'OFFLINE' | 'ONLINE' | 'ON_TRIP';
/** EV_SCOOTER is a low-speed e-scooter: no RC, no licence. A registered one is SCOOTER. */
export type VehicleType = 'BIKE' | 'SCOOTER' | 'EV_SCOOTER' | 'CYCLE';
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
  /**
   * Only APPROVED may work. A self-signed-up rider is PENDING until an admin
   * approves the application; admin-made riders were always APPROVED.
   */
  onboarding: RiderOnboarding;
  /** Null for a rider an admin created: there is no application to show. */
  application_status: ApplicationStatus | null;
};

export type RiderOnboarding = 'PENDING' | 'APPROVED' | 'REJECTED';

// --- self sign-up (`app/schemas/rider_onboarding.py`) ------------------------

export type SignupCodeResponse = {
  sent: boolean;
  retry_after: number;
  /** The static code while sign-up runs without a real sender. */
  debug_code: string | null;
};

export type ApplicationStatus =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'CHANGES_NEEDED'
  | 'APPROVED'
  | 'REJECTED';

export type ItemStatus = 'MISSING' | 'PENDING' | 'ACCEPTED' | 'NEEDS_CHANGE';

export type SectionKey = 'personal' | 'vehicle' | 'documents' | 'bank';

export type PhotoKind =
  | 'SELFIE'
  | 'RC'
  | 'AADHAAR_FRONT'
  | 'AADHAAR_BACK'
  | 'PAN'
  | 'LICENCE_FRONT'
  | 'LICENCE_BACK'
  | 'BANK_PROOF';

export type ItemKind = PhotoKind | 'PERSONAL' | 'VEHICLE_DETAILS' | 'BANK_DETAILS';

export type ApplicationItem = {
  kind: ItemKind;
  status: ItemStatus;
  reason: string;
  section: SectionKey;
  required: boolean;
  has_photo: boolean;
  /** Whether the rider may change it right now (a draft, or flagged). */
  editable: boolean;
};

export type ApplicationView = {
  rider_user_id: string;
  status: ApplicationStatus;
  final_reason: string;
  submitted_at: string | null;
  decided_at: string | null;
  sections: {
    personal: {
      full_name: string;
      /** YYYY-MM-DD */
      date_of_birth: string | null;
      city: string;
      address_line: string;
      pincode: string;
      emergency_name: string;
      emergency_phone: string;
    };
    vehicle: { vehicle_type: VehicleType | null; vehicle_number: string };
    documents: {
      aadhaar_last4: string;
      pan_last4: string;
      licence_last4: string;
      licence_expiry: string | null;
    };
    bank: {
      bank_holder: string;
      bank_account_last4: string;
      ifsc: string;
      upi_id: string;
    };
  };
  items: ApplicationItem[];
  required: ItemKind[];
  missing: ItemKind[];
};

/** A photo on the phone, ready to send as multipart `file`. */
export type UploadFile = { uri: string; type: string; name: string };

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
  /** When the kitchen expects the food to be ready; null when the restaurant
   * has no preparation time set (`utils/ready`). */
  ready_at?: string | null;
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
  /** When the kitchen expects the food to be ready; null when the restaurant
   * has no preparation time set (`utils/ready`). */
  ready_at?: string | null;
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
  /** When the kitchen expects the food to be ready; null when the restaurant
   * has no preparation time set (`utils/ready`). */
  ready_at?: string | null;
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
