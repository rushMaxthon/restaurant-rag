import type {
  CartSelectedOption,
  CartSelectedSize,
  DecimalValue,
  MenuItem,
  MenuItemCustomizationGroup,
  MenuItemCustomizationOption,
  MenuItemSize,
} from '@/types/app';

export function toNumber(value: DecimalValue): number {
  return typeof value === 'number' ? value : Number(value);
}

export function isCustomizableMenuItem(menuItem: MenuItem): boolean {
  return menuItem.has_sizes || menuItem.has_customizations;
}

export function getActiveSizes(menuItem: MenuItem): MenuItemSize[] {
  return (menuItem.sizes ?? []).filter(size => size.is_active);
}

export function getDefaultSelectedSize(menuItem: MenuItem): CartSelectedSize | null {
  const size = getActiveSizes(menuItem)[0];
  if (!size) {
    return null;
  }
  return {
    id: size.id,
    name: size.name,
    price: size.price,
  };
}

export function getActiveCustomizationGroups(
  menuItem: MenuItem,
  selectedSizeId: string | null,
): MenuItemCustomizationGroup[] {
  if (menuItem.has_sizes) {
    const size = (menuItem.sizes ?? []).find(
      entry => entry.id === selectedSizeId && entry.is_active,
    );
    return [
      ...(menuItem.customization_groups ?? []),
      ...(size?.customization_groups ?? []),
    ].filter(group => group.is_active);
  }
  return (menuItem.customization_groups ?? []).filter(group => group.is_active);
}

export function findCustomizationOption(
  menuItem: MenuItem,
  selectedSizeId: string | null,
  optionId: string,
): {group: MenuItemCustomizationGroup; option: MenuItemCustomizationOption} | null {
  const groups = getActiveCustomizationGroups(menuItem, selectedSizeId);
  for (const group of groups) {
    const option = group.options.find(entry => entry.id === optionId && entry.is_active);
    if (option) {
      return {group, option};
    }
  }
  return null;
}

export function buildLineItemId(input: {
  menuItemId: string;
  selectedSizeId: string | null;
  selectedOptions: CartSelectedOption[];
}): string {
  const optionSignature = [...input.selectedOptions]
    .sort((left, right) => left.optionId.localeCompare(right.optionId))
    .map(option => `${option.optionId}:${option.quantity}`)
    .join('|');
  return `${input.menuItemId}::${input.selectedSizeId ?? 'default'}::${optionSignature}`;
}

export function calculateUnitPrice(input: {
  menuItem: MenuItem;
  selectedSize: CartSelectedSize | null;
  selectedOptions: CartSelectedOption[];
}): number {
  const basePrice = input.selectedSize
    ? toNumber(input.selectedSize.price)
    : toNumber(input.menuItem.price);
  const optionTotal = input.selectedOptions.reduce(
    (total, option) => total + toNumber(option.extraPrice) * option.quantity,
    0,
  );
  return Number((basePrice + optionTotal).toFixed(2));
}

export function formatCustomizationSummary(
  selectedSize: CartSelectedSize | null,
  selectedOptions: CartSelectedOption[],
): string[] {
  const lines: string[] = [];
  if (selectedSize) {
    lines.push(selectedSize.name);
  }
  for (const option of selectedOptions) {
    lines.push(
      option.quantity > 1 ? `${option.optionName} x${option.quantity}` : option.optionName,
    );
  }
  return lines;
}

export function validateCustomizationSelection(input: {
  menuItem: MenuItem;
  selectedSize: CartSelectedSize | null;
  selectedOptions: CartSelectedOption[];
}): string | null {
  if (input.menuItem.has_sizes && !input.selectedSize) {
    return 'Please select a size.';
  }

  const groups = getActiveCustomizationGroups(
    input.menuItem,
    input.selectedSize?.id ?? null,
  );
  const optionsByGroup = new Map<string, CartSelectedOption[]>();
  for (const option of input.selectedOptions) {
    const current = optionsByGroup.get(option.groupId) ?? [];
    current.push(option);
    optionsByGroup.set(option.groupId, current);
    if (option.quantity < 1) {
      return `${option.optionName} quantity must be at least 1.`;
    }
    if (!option.isCountable && option.quantity !== 1) {
      return `${option.optionName} cannot use a quantity higher than 1.`;
    }
  }

  for (const group of groups) {
    const selections = optionsByGroup.get(group.id) ?? [];
    const count = selections.length;
    if (group.selection_type === 'SINGLE' && count > 1) {
      return `${group.title} allows only one selection.`;
    }
    if (group.is_required && count < Math.max(group.min_selection, 1)) {
      return `${group.title} requires at least one selection.`;
    }
    if (count < group.min_selection) {
      return `${group.title} requires at least ${group.min_selection} selections.`;
    }
    if (count > group.max_selection) {
      return `${group.title} allows at most ${group.max_selection} selections.`;
    }
  }
  return null;
}
