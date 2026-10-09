import { nextSlide } from './tripSteps';

describe('the one big next step on a trip', () => {
  it('walks the stops in order, one action each', () => {
    expect(nextSlide('to_pickup')?.action).toBe('arrived-pickup');
    expect(nextSlide('at_pickup')?.action).toBe('picked-up');
    expect(nextSlide('to_drop')?.action).toBe('arrived-drop');
  });

  it('offers no slide at the door: delivery needs the 4-digit code instead', () => {
    expect(nextSlide('at_drop')).toBeNull();
  });

  it('offers nothing once the trip is done', () => {
    expect(nextSlide('done')).toBeNull();
  });

  it('labels each slide with what the rider has just done', () => {
    expect(nextSlide('to_pickup')?.label).toBe('Arrived at restaurant');
    expect(nextSlide('at_pickup')?.label).toBe('Picked up the order');
    expect(nextSlide('to_drop')?.label).toBe('Arrived at customer');
  });
});
