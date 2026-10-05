import { BadgeCheck, MapPin, Store, User } from "lucide-react";

import { AddressAutocomplete, type PickedAddress } from "@/components/AddressAutocomplete";
import { AddressField } from "@/components/checkout/address-field";
import { StepHeader } from "@/components/checkout/step-header";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { RestaurantLocation } from "@/lib/bangkok-data";
import type { AddressFields, AddressProblems } from "@/lib/delivery-address";

/** A saved address as the picker needs to show it. */
export type SavedAddressOption = {
  id: string;
  label: string;
  formatted_address: string;
};

type TouchableField = keyof AddressFields | "phone" | "name";

/**
 * Step one: who this is for and where it is going.
 *
 * **Every rule lives in the checkout, not here.** This component holds no
 * state and decides nothing — what counts as a valid phone number, when an
 * error is shown, what a picked address overwrites — all of that stays in
 * `routes/checkout.tsx`, which is the one place that can keep the form, the
 * quote and the submit handler agreeing. This is the markup of one step, with
 * everything it needs arriving as props, so the 1,600-line route can be read
 * as three steps and a summary rather than as one page.
 *
 * The labels are the contract. The end-to-end suite fills these fields by
 * their labels ("Full name", "Phone number", /^Address line 1/, "City",
 * "State", and whatever `postalName` resolves to), so a rename here is a
 * suite-wide change rather than a local one.
 */
export function ContactStep({
  isDelivery,
  isAuthenticated,
  filledFromAccount,
  savedAddresses,
  addressId,
  onPickSavedAddress,
  fullName,
  onFullNameChange,
  phone,
  onPhoneChange,
  phoneCountryCode,
  phoneProblem,
  address,
  addressProblems,
  onEditAddress,
  onPickAddress,
  onTouch,
  show,
  branch,
  postalName,
  saveAddress,
  onSaveAddressChange,
}: {
  isDelivery: boolean;
  isAuthenticated: boolean;
  filledFromAccount: boolean;
  savedAddresses: SavedAddressOption[];
  addressId: string | null;
  onPickSavedAddress: (id: string) => void;
  fullName: string;
  onFullNameChange: (next: string) => void;
  phone: string;
  onPhoneChange: (next: string) => void;
  phoneCountryCode: string | undefined;
  phoneProblem: string | null;
  address: AddressFields;
  addressProblems: AddressProblems;
  onEditAddress: (part: keyof AddressFields, next: string) => void;
  onPickAddress: (picked: PickedAddress) => void;
  /** Mark a field as left, so its error may now be shown. */
  onTouch: (field: TouchableField) => void;
  /** Whether a field's problem should be visible yet. */
  show: (field: TouchableField) => boolean;
  branch: RestaurantLocation | undefined;
  postalName: string;
  saveAddress: boolean;
  onSaveAddressChange: (next: boolean) => void;
}) {
  return (
    <section className="elevated-panel step-panel">
      <StepHeader
        number={1}
        title={<>Contact &amp; {isDelivery ? "delivery" : "pickup"}</>}
        blurb="We use this to reach you if the rider needs directions."
      >
        {/* Said out loud. Fields that fill themselves without a word read as
            the form having got something wrong, and the customer re-reads
            all of them looking for it. */}
        {filledFromAccount && (
          <p className="prefill-note mt-3">
            <BadgeCheck className="size-4 shrink-0" />
            Filled in from your account — change anything that has moved.
          </p>
        )}
      </StepHeader>

      {isDelivery && savedAddresses.length > 1 && (
        <div className="saved-address-picker mt-4">
          {savedAddresses.map((entry) => (
            <button
              type="button"
              key={entry.id}
              className="saved-address"
              data-on={addressId === entry.id}
              onClick={() => onPickSavedAddress(entry.id)}
            >
              <span className="saved-address__label">
                {entry.label === "HOME" ? "Home" : entry.label === "WORK" ? "Work" : "Other"}
              </span>
              <span className="saved-address__line">{entry.formatted_address}</span>
            </button>
          ))}
        </div>
      )}

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="full_name">Full name</Label>
          <div className="field-wrap">
            <User className="size-4" />
            <Input
              id="full_name"
              required
              autoComplete="name"
              placeholder="Your name"
              value={fullName}
              onChange={(e) => onFullNameChange(e.target.value)}
              className="h-12"
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="phone">Phone number</Label>
          <div className="field-wrap" data-invalid={Boolean(show("phone") && phoneProblem)}>
            {/* The country code is shown, not typed, and comes from the server
                rather than a literal here: this said "+1" while the server
                prepended something else, so the code the customer was shown
                and the code their number was stored under could differ with
                nothing to say so. */}
            {phoneCountryCode && <span className="country-code">{phoneCountryCode}</span>}
            <Input
              id="phone"
              required
              type="tel"
              inputMode="tel"
              autoComplete="tel-national"
              placeholder="Mobile number"
              value={phone}
              onChange={(e) => onPhoneChange(e.target.value)}
              onBlur={() => onTouch("phone")}
              aria-invalid={Boolean(show("phone") && phoneProblem)}
              aria-describedby={show("phone") && phoneProblem ? "phone-error" : undefined}
              className="h-12"
            />
          </div>
          {show("phone") && phoneProblem && (
            <p className="field-error" id="phone-error">
              {phoneProblem}
            </p>
          )}
        </div>
        {isDelivery && (
          <>
            <AddressField
              autoComplete="address-line1"
              className="sm:col-span-2"
              hint="Optional"
              icon={<MapPin className="size-4" />}
              id="house"
              label="Flat, house or block number"
              onBlur={() => onTouch("house")}
              onChange={(next) => onEditAddress("house", next)}
              placeholder="A-31, 3rd floor"
              problem={undefined}
              value={address.house}
            />
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="line1">
                Address line 1
                <span className="ml-1.5 text-xs font-medium text-muted">
                  Start typing and pick your building
                </span>
              </Label>
              <AddressAutocomplete
                autoComplete="address-line1"
                icon={<MapPin className="size-4" />}
                inputId="line1"
                invalid={Boolean(show("line1") && addressProblems.line1)}
                locationId={branch?.id ?? null}
                onBlur={() => onTouch("line1")}
                onPick={onPickAddress}
                onTextChange={(next) => onEditAddress("line1", next)}
                placeholder="Society, building or street"
                value={address.line1}
              />
              {show("line1") && addressProblems.line1 && (
                <p className="field-error" id="line1-error">
                  {addressProblems.line1}
                </p>
              )}
            </div>
            <AddressField
              id="line2"
              label="Address line 2"
              hint="Optional"
              placeholder="Apartment, suite, floor"
              autoComplete="address-line2"
              className="sm:col-span-2"
              value={address.line2}
              problem={show("line2") ? addressProblems.line2 : undefined}
              onChange={(next) => onEditAddress("line2", next)}
              onBlur={() => onTouch("line2")}
            />
            <AddressField
              id="landmark"
              label="Landmark"
              hint="Optional"
              placeholder="Opposite the park"
              autoComplete="off"
              className="sm:col-span-2"
              value={address.landmark}
              problem={show("landmark") ? addressProblems.landmark : undefined}
              onChange={(next) => onEditAddress("landmark", next)}
              onBlur={() => onTouch("landmark")}
            />
            {/* City, state and the postal code share one row from `sm` up.
                They are the three short answers at the end of an address and
                were stacked as three full-width boxes, which put the save
                checkbox and the next step a screen further down than the
                address needed. */}
            <div className="grid gap-4 sm:col-span-2 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)]">
              <AddressField
                id="city"
                label="City"
                placeholder="City"
                autoComplete="address-level2"
                value={address.city}
                problem={show("city") ? addressProblems.city : undefined}
                onChange={(next) => onEditAddress("city", next)}
                onBlur={() => onTouch("city")}
              />
              <AddressField
                id="state"
                label="State"
                placeholder="State"
                autoComplete="address-level1"
                value={address.state}
                problem={show("state") ? addressProblems.state : undefined}
                onChange={(next) => onEditAddress("state", next)}
                onBlur={() => onTouch("state")}
              />
              <AddressField
                id="zip"
                label={postalName}
                placeholder="00000"
                autoComplete="postal-code"
                inputMode="numeric"
                value={address.zip}
                problem={show("zip") ? addressProblems.zip : undefined}
                onChange={(next) => onEditAddress("zip", next)}
                onBlur={() => onTouch("zip")}
              />
            </div>
          </>
        )}
      </div>

      {/* Offered, not assumed, and only when this is a new address: the
          prefill is worth nothing to a customer whose first order never left
          anything behind to prefill FROM. */}
      {isDelivery && isAuthenticated && !addressId && (
        <label className="save-address mt-4">
          <input
            type="checkbox"
            checked={saveAddress}
            onChange={(e) => onSaveAddressChange(e.target.checked)}
          />
          <span>Save this address to my account for next time</span>
        </label>
      )}

      {!isDelivery && branch && (
        <div className="pickup-branch mt-5">
          <Store className="mt-0.5 size-5 shrink-0 text-primary" />
          <div>
            <p className="font-bold">{branch.branch_name}</p>
            <p className="text-sm text-muted">
              {branch.address_line_1}, {branch.city}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
