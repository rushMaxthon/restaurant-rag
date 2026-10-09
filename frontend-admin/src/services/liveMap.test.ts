import { describe, expect, it } from 'vitest';

import { bearingDeg, branchPins, fitView, glideAt, groupByPickup, metresToPixels, readyLine, nearestRiders, project, riderPinTone, tilesFor, unproject } from './liveMap';
import type { Rider } from '../types/app';

const rider = (over: Partial<Rider>): Rider => ({
  user_id: 'r',
  full_name: 'Ravi',
  phone_number: null,
  is_active: true,
  vehicle_type: 'BIKE',
  vehicle_number: '',
  city: 'Surat',
  status: 'ONLINE',
  last_latitude: 21.17,
  last_longitude: 72.83,
  last_location_at: new Date().toISOString(),
  active_order_id: null,
  notes: '',
  ...over,
});

describe('projection', () => {
  it('round-trips a point through world pixels', () => {
    const p = project(21.17, 72.83, 13);
    const back = unproject(p.x, p.y, 13);
    expect(back.lat).toBeCloseTo(21.17, 6);
    expect(back.lng).toBeCloseTo(72.83, 6);
  });

  it('puts 0,0 in the middle of the world', () => {
    expect(project(0, 0, 1)).toEqual({ x: 256, y: 256 });
  });
});

describe('fitView', () => {
  it('zooms in as far as it can while every pin stays on screen', () => {
    const view = fitView(
      [
        { lat: 21.15, lng: 72.8 },
        { lat: 21.2, lng: 72.86 },
      ],
      800,
      600,
    );
    expect(view.zoom).toBeGreaterThanOrEqual(12);
    expect(view.zoom).toBeLessThanOrEqual(14);
    expect(view.center.lat).toBeCloseTo(21.175, 2);
  });

  it('falls back to a city view with nothing to show', () => {
    expect(fitView([], 800, 600).zoom).toBe(12);
  });

  it('does not zoom to street level on a single pin', () => {
    expect(fitView([{ lat: 21.17, lng: 72.83 }], 800, 600).zoom).toBe(15);
  });
});

describe('tilesFor', () => {
  it('covers the whole viewport and nothing far outside it', () => {
    const tiles = tilesFor({ lat: 21.17, lng: 72.83 }, 13, 800, 600);
    expect(tiles.length).toBeGreaterThanOrEqual(12);
    expect(tiles.length).toBeLessThanOrEqual(25);
    for (const t of tiles) {
      expect(t.left).toBeGreaterThan(-256);
      expect(t.left).toBeLessThan(800);
      expect(t.top).toBeGreaterThan(-256);
      expect(t.top).toBeLessThan(600);
    }
  });
});

describe('nearestRiders', () => {
  it('puts free online riders first, nearest first, and leaves out the busy and the unplaced', () => {
    const near = rider({ user_id: 'near', last_latitude: 21.171, last_longitude: 72.831 });
    const far = rider({ user_id: 'far', last_latitude: 21.25, last_longitude: 72.9 });
    const busy = rider({ user_id: 'busy', status: 'ON_TRIP', active_order_id: 'o' });
    const lost = rider({ user_id: 'lost', last_latitude: null, last_longitude: null });
    const rows = nearestRiders([far, busy, near, lost], { lat: 21.17, lng: 72.83 });
    expect(rows.map(r => r.rider.user_id)).toEqual(['near', 'far']);
    expect(rows[0].metres).toBeLessThan(200);
  });

  it('leaves out a rider whose position has gone stale - they may be anywhere now', () => {
    const now = new Date('2026-10-08T12:00:00Z');
    const fresh = rider({ user_id: 'fresh', last_location_at: '2026-10-08T11:59:00Z' });
    const quiet = rider({ user_id: 'quiet', last_location_at: '2026-10-08T11:30:00Z' });
    expect(nearestRiders([quiet, fresh], { lat: 21.17, lng: 72.83 }, now).map(r => r.rider.user_id)).toEqual(['fresh']);
  });
});

describe('groupByPickup', () => {
  const order = (id: string, lat: number | null) =>
    ({ order_id: id, pickup_lat: lat, pickup_lng: lat == null ? null : 72.8 }) as never;

  it('stacks orders from one kitchen into one pin, oldest first', () => {
    const groups = groupByPickup([order('a', 21.2), order('b', 21.2), order('c', 21.3)]);
    expect(groups.map(g => g.orders.map(o => o.order_id))).toEqual([['a', 'b'], ['c']]);
  });

  it('skips a branch with no map pin', () => {
    expect(groupByPickup([order('x', null)])).toEqual([]);
  });
});

describe('riderPinTone', () => {
  const now = new Date('2026-10-08T12:00:00Z');
  it('is free, busy or stale', () => {
    expect(riderPinTone(rider({ last_location_at: '2026-10-08T11:59:00Z' }), now)).toBe('free');
    expect(riderPinTone(rider({ status: 'ON_TRIP', last_location_at: '2026-10-08T11:59:00Z' }), now)).toBe('busy');
    expect(riderPinTone(rider({ last_location_at: '2026-10-08T11:40:00Z' }), now)).toBe('stale');
  });
});

describe('glideAt', () => {
  const from = { lat: 21.0, lng: 72.0 };
  const to = { lat: 21.1, lng: 72.2 };
  it('starts where the pin was and ends where the rider is', () => {
    expect(glideAt(from, to, 0)).toEqual(from);
    expect(glideAt(from, to, 1)).toEqual(to);
  });
  it('eases: past the halfway point at half time, never overshooting', () => {
    const mid = glideAt(from, to, 0.5);
    expect(mid.lat).toBeGreaterThan(21.05);
    expect(mid.lat).toBeLessThan(21.1);
    expect(glideAt(from, to, 1.7)).toEqual(to);
  });
});

describe('bearingDeg', () => {
  it('points the way the rider is going, clockwise from north', () => {
    expect(Math.round(bearingDeg({ lat: 21, lng: 72 }, { lat: 21.01, lng: 72 }))).toBe(0);
    expect(Math.round(bearingDeg({ lat: 21, lng: 72 }, { lat: 21, lng: 72.01 }))).toBe(90);
    expect(Math.round(bearingDeg({ lat: 21, lng: 72 }, { lat: 20.99, lng: 72 }))).toBe(180);
    expect(Math.round(bearingDeg({ lat: 21, lng: 72 }, { lat: 21, lng: 71.99 }))).toBe(270);
  });
});

describe('metresToPixels', () => {
  it('turns a ground distance into screen pixels at this zoom and latitude', () => {
    // At the equator, zoom 0, one 256px tile spans the whole 40,075 km.
    expect(metresToPixels(40_075_016.7, 0, 0)).toBeCloseTo(256, 0);
    // Each zoom step doubles it; further from the equator a metre is more pixels.
    expect(metresToPixels(2000, 21.18, 14)).toBeCloseTo(2 * metresToPixels(2000, 21.18, 13), 6);
    expect(metresToPixels(2000, 21.18, 14)).toBeGreaterThan(metresToPixels(2000, 0, 14));
  });
});

describe('branchPins', () => {
  const branch = (id: string, lat: number) =>
    ({ id, restaurant_name: 'R', branch_name: 'Main', lat, lng: 72.8, on_fleet: true }) as never;
  const order = (lat: number) => ({ order_id: 'o', pickup_lat: lat, pickup_lng: 72.8 }) as never;

  it('leaves out a branch already drawn as an order pin', () => {
    const pins = branchPins([branch('a', 21.2), branch('b', 21.3)], groupByPickup([order(21.2)]));
    expect(pins.map(b => b.id)).toEqual(['b']);
  });
});

describe('readyLine', () => {
  const clock = (iso: string) => iso.slice(11, 16);
  const now = new Date('2026-10-10T14:00:00Z');

  it('says when the food is ready and when riders get it, while held', () => {
    expect(readyLine('2026-10-10T14:25:00Z', '2026-10-10T14:15:00Z', now, clock)).toBe(
      'Food ready 14:25 · riders get it at 14:15',
    );
  });
  it('says only the ready time once riders have it', () => {
    expect(readyLine('2026-10-10T14:05:00Z', null, now, clock)).toBe('Food ready 14:05');
  });
  it('says it should be ready once the time has passed', () => {
    expect(readyLine('2026-10-10T13:55:00Z', null, now, clock)).toBe('Food should be ready');
  });
  it('says nothing for a branch with no preparation time', () => {
    expect(readyLine(null, null, now, clock)).toBeNull();
    expect(readyLine(undefined, undefined, now, clock)).toBeNull();
  });
});
