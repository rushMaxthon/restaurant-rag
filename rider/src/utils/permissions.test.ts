import { firstMissing, gateReason, PERMISSION_ORDER } from './permissions';

const all = { location: true, notifications: true, battery: true };

describe('the permission gate', () => {
  it('lets a rider go online only when everything is allowed', () => {
    expect(firstMissing(all)).toBeNull();
    expect(gateReason(all)).toBeNull();
  });

  it('asks for location first: no location, no orders', () => {
    expect(firstMissing({ location: false, notifications: false, battery: false })).toBe('location');
  });

  it('names what is still missing, in the order the screen asks', () => {
    expect(firstMissing({ ...all, battery: false })).toBe('battery');
    expect(gateReason({ ...all, notifications: false })).toBe('Allow notifications to start getting orders');
    expect(gateReason({ ...all, battery: false })).toBe('Let the app run in the background to start getting orders');
  });

  it('treats a state not read yet as not allowed', () => {
    expect(firstMissing(null)).toBe('location');
  });

  it('asks in a fixed order', () => {
    expect(PERMISSION_ORDER).toEqual(['location', 'notifications', 'battery']);
  });
});
