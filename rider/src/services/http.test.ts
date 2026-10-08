import { messageFor } from './http';

describe('messageFor', () => {
  it('turns a backend code into a sentence for the rider', () => {
    expect(messageFor(409, 'offer_taken')).toEqual({ message: 'Another rider took this order.', code: 'offer_taken' });
  });
  it('reads a structured detail with a code', () => {
    expect(messageFor(422, { code: 'otp_wrong', attempts_left: 3 }).code).toBe('otp_wrong');
  });
  it('shows the first validation message', () => {
    expect(messageFor(422, [{ msg: 'Field required' }]).message).toBe('Field required');
  });
  it('explains an expired session', () => {
    expect(messageFor(401, null).code).toBe('auth');
  });
  it('passes through a plain sentence from the server', () => {
    expect(messageFor(400, 'Enter a valid phone number').message).toBe('Enter a valid phone number');
  });
});
