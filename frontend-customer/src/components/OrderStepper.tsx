import type { OrderStatus } from '../types/app';

const steps: OrderStatus[] = ['PLACED', 'ACCEPTED', 'PREPARING', 'OUT_FOR_DELIVERY', 'DELIVERED'];

interface OrderStepperProps {
  status: OrderStatus;
}

/** `mobile/src/components/OrderStepper.tsx`. */
export function OrderStepper({ status }: OrderStepperProps) {
  // Neither state belongs on the fulfillment rail: an unpaid order has not
  // started, and a cancelled one never will. Without this they both fell
  // through `indexOf` to -1 and rendered five "Pending" steps, which reads as
  // "about to be cooked" for an order that will never be.
  if (status === 'PAYMENT_PENDING' || status === 'CANCELLED') {
    const isPending = status === 'PAYMENT_PENDING';
    return (
      <div
        className={
          isPending ? 'order-notice order-notice--pending' : 'order-notice order-notice--cancelled'
        }
      >
        <strong>{isPending ? 'Waiting for payment' : 'Order cancelled'}</strong>
        <span>
          {isPending
            ? 'The restaurant starts preparing this order as soon as the payment is confirmed.'
            : 'This order was cancelled and will not be prepared.'}
        </span>
      </div>
    );
  }

  const activeIndex = steps.indexOf(status);

  return (
    <ol className="order-stepper">
      {steps.map((step, index) => {
        const state = index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending';
        return (
          <li className={`order-step order-step--${state}`} key={step}>
            <span className="order-step__dot">{state === 'done' ? '✓' : ''}</span>
            <div>
              <strong>{step.replaceAll('_', ' ')}</strong>
              <span>
                {state === 'active' ? 'In progress' : state === 'done' ? 'Completed' : 'Pending'}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
