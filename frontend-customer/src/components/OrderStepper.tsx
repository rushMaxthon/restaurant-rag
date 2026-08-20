import type { OrderStatus } from '../types/app';

const steps: OrderStatus[] = ['PLACED', 'ACCEPTED', 'PREPARING', 'OUT_FOR_DELIVERY', 'DELIVERED'];

interface OrderStepperProps {
  status: OrderStatus;
}

export function OrderStepper({ status }: OrderStepperProps) {
  const activeIndex = steps.indexOf(status);

  return (
    <ol className="order-stepper">
      {steps.map((step, index) => {
        const state =
          index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending';
        return (
          <li className={`order-step order-step--${state}`} key={step}>
            <span className="order-step__dot">{state === 'done' ? '✓' : ''}</span>
            <div>
              <strong>{step.replaceAll('_', ' ')}</strong>
              <span>{state === 'active' ? 'In progress' : state === 'done' ? 'Completed' : 'Pending'}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
