import { nextSlide, stepProgress } from './tripSteps';

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

describe('the trip progress line', () => {
  it('names where the rider is, counting from one', () => {
    expect(stepProgress('to_pickup')).toEqual({ current: 1, total: 4, label: 'Going to the restaurant' });
    expect(stepProgress('at_pickup')).toEqual({ current: 2, total: 4, label: 'At the restaurant' });
    expect(stepProgress('to_drop')).toEqual({ current: 3, total: 4, label: 'Going to the customer' });
    expect(stepProgress('at_drop')).toEqual({ current: 4, total: 4, label: 'At the door' });
  });

  it('is full once delivered', () => {
    expect(stepProgress('done')).toEqual({ current: 4, total: 4, label: 'Delivered' });
  });
});
