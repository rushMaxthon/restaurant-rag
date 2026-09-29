export function VegMark({ veg }: { veg: boolean }) {
  return (
    <span
      className={veg ? "veg-mark" : "nonveg-mark"}
      aria-label={veg ? "Vegetarian" : "Non-vegetarian"}
    >
      <i />
    </span>
  );
}
