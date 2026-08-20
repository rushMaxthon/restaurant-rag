import { useEffect, useState, type ChangeEvent } from "react";
import { Plus } from "lucide-react";
import { Checkbox } from "./common/Checkbox";

import type {
  MenuItem,
  MenuItemCustomizationGroupPayload,
  MenuItemCustomizationOptionPayload,
  MenuItemCustomizationSelectionType,
  MenuItemSizePayload,
  MenuItemUpsertPayload,
} from "../types/app";

type MenuItemCustomizationOptionFormState = {
  id: string;
  name: string;
  extra_price: string;
  is_active: boolean;
  is_countable: boolean;
  sort_order: string;
};

type MenuItemCustomizationGroupFormState = {
  id: string;
  title: string;
  available_size_ids: string[];
  selection_type: MenuItemCustomizationSelectionType;
  is_required: boolean;
  min_selection: string;
  max_selection: string;
  is_active: boolean;
  sort_order: string;
  options: MenuItemCustomizationOptionFormState[];
};

type MenuItemSizeFormState = {
  id: string;
  name: string;
  price: string;
  is_active: boolean;
  sort_order: string;
  customization_groups: MenuItemCustomizationGroupFormState[];
};

export type MenuItemFormState = {
  name: string;
  category: string;
  cuisine_type: string;
  description: string;
  price: string;
  launched_at: string;
  is_veg: boolean;
  is_available: boolean;
  image_url: string;
  is_new_launch: boolean;
  has_sizes: boolean;
  has_customizations: boolean;
  sizes: MenuItemSizeFormState[];
  customization_groups: MenuItemCustomizationGroupFormState[];
};

type MenuItemCustomizationEditorProps = {
  form: MenuItemFormState;
  onChange: (nextForm: MenuItemFormState) => void;
};

function createId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function normalizeSizeName(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

type MenuItemCustomizationGroupDraftState = {
  title: string;
  available_size_ids: string[];
  selection_type: MenuItemCustomizationSelectionType;
  min_selection: string;
  max_selection: string;
  is_required: boolean;
  is_active: boolean;
};

type MenuItemCustomizationOptionDraftState = {
  name: string;
  extra_price: string;
  is_countable: boolean;
  is_active: boolean;
};

function toDateTimeLocalValue(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function toApiDateTimeValue(value: string): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toISOString();
}

function toStringNumber(value: number | string): string {
  return typeof value === "number" ? String(value) : value;
}

function createEmptyOption(): MenuItemCustomizationOptionFormState {
  return {
    id: createId("option"),
    name: "",
    extra_price: "0",
    is_active: true,
    is_countable: false,
    sort_order: "0",
  };
}

function createEmptyGroup(): MenuItemCustomizationGroupFormState {
  return {
    id: createId("group"),
    title: "",
    available_size_ids: [],
    selection_type: "MULTI",
    is_required: false,
    min_selection: "0",
    max_selection: "1",
    is_active: true,
    sort_order: "0",
    options: [],
  };
}

function createEmptySize(): MenuItemSizeFormState {
  return {
    id: createId("size"),
    name: "",
    price: "",
    is_active: true,
    sort_order: "0",
    customization_groups: [],
  };
}

function createEmptyGroupDraftState(): MenuItemCustomizationGroupDraftState {
  return {
    title: "",
    available_size_ids: [],
    selection_type: "MULTI",
    min_selection: "0",
    max_selection: "1",
    is_required: false,
    is_active: true,
  };
}

function createGroupDraftStateFromGroup(
  group: MenuItemCustomizationGroupFormState,
): MenuItemCustomizationGroupDraftState {
  return {
    title: group.title,
    available_size_ids: [...group.available_size_ids],
    selection_type: group.selection_type,
    min_selection: group.min_selection,
    max_selection: group.max_selection,
    is_required: group.is_required,
    is_active: group.is_active,
  };
}

function createEmptyOptionDraftState(): MenuItemCustomizationOptionDraftState {
  return {
    name: "",
    extra_price: "0",
    is_countable: false,
    is_active: true,
  };
}

function createOptionDraftStateFromOption(
  option: MenuItemCustomizationOptionFormState,
): MenuItemCustomizationOptionDraftState {
  return {
    name: option.name,
    extra_price: option.extra_price,
    is_countable: option.is_countable,
    is_active: option.is_active,
  };
}

function mapOptionToForm(
  option: MenuItem["customization_groups"][number]["options"][number],
): MenuItemCustomizationOptionFormState {
  return {
    id: option.id,
    name: option.name,
    extra_price: toStringNumber(option.extra_price),
    is_active: option.is_active,
    is_countable: option.is_countable,
    sort_order: String(option.sort_order),
  };
}

function mapGroupToForm(
  group: MenuItem["customization_groups"][number],
  availableSizeIds: string[] = [],
): MenuItemCustomizationGroupFormState {
  return {
    id: group.id,
    title: group.title,
    available_size_ids: [...availableSizeIds],
    selection_type: group.selection_type,
    is_required: group.is_required,
    min_selection: String(group.min_selection),
    max_selection: String(group.max_selection),
    is_active: group.is_active,
    sort_order: String(group.sort_order),
    options: group.options.map(mapOptionToForm),
  };
}

function buildGroupMergeSignature(
  group: Pick<
    MenuItem["customization_groups"][number],
    | "title"
    | "selection_type"
    | "is_required"
    | "min_selection"
    | "max_selection"
    | "is_active"
    | "sort_order"
    | "options"
  >,
): string {
  return JSON.stringify({
    title: group.title.trim().toLowerCase(),
    selection_type: group.selection_type,
    is_required: group.is_required,
    min_selection: group.min_selection,
    max_selection: group.max_selection,
    is_active: group.is_active,
    sort_order: group.sort_order,
    options: group.options.map((option) => ({
      name: option.name.trim().toLowerCase(),
      extra_price: String(option.extra_price),
      is_active: option.is_active,
      is_countable: option.is_countable,
      sort_order: option.sort_order,
    })),
  });
}

export function createEmptyMenuItemFormState(): MenuItemFormState {
  return {
    name: "",
    category: "",
    cuisine_type: "",
    description: "",
    price: "",
    launched_at: "",
    is_veg: true,
    is_available: true,
    image_url: "",
    is_new_launch: false,
    has_sizes: false,
    has_customizations: false,
    sizes: [],
    customization_groups: [],
  };
}

export function createMenuItemFormStateFromItem(item: MenuItem): MenuItemFormState {
  const sizeIds = item.sizes.map((size) => size.id);
  const mergedGroupsBySignature = new Map<string, MenuItemCustomizationGroupFormState>();
  const mergedGroups: MenuItemCustomizationGroupFormState[] = [];

  const upsertMergedGroup = (
    group: MenuItem["customization_groups"][number],
    availableSizeIds: string[],
  ) => {
    const signature = buildGroupMergeSignature(group);
    const existing = mergedGroupsBySignature.get(signature);
    if (existing) {
      existing.available_size_ids = Array.from(
        new Set([...existing.available_size_ids, ...availableSizeIds]),
      );
      return;
    }
    const nextGroup = mapGroupToForm(group, availableSizeIds);
    mergedGroupsBySignature.set(signature, nextGroup);
    mergedGroups.push(nextGroup);
  };

  if (item.has_sizes) {
    item.customization_groups.forEach((group) => {
      upsertMergedGroup(group, sizeIds);
    });
    item.sizes.forEach((size) => {
      size.customization_groups.forEach((group) => {
        upsertMergedGroup(group, [size.id]);
      });
    });
  }

  return {
    name: item.name,
    category: item.category,
    cuisine_type: item.cuisine_type ?? "",
    description: item.description ?? "",
    price: toStringNumber(item.price),
    launched_at: toDateTimeLocalValue(item.launched_at),
    is_veg: item.is_veg,
    is_available: item.is_available,
    image_url: item.image_url ?? "",
    is_new_launch: item.is_new_launch,
    has_sizes: item.has_sizes,
    has_customizations: item.has_customizations,
    sizes: item.sizes.map((size) => ({
      id: size.id,
      name: size.name,
      price: toStringNumber(size.price),
      is_active: size.is_active,
      sort_order: String(size.sort_order),
      customization_groups: [],
    })),
    customization_groups: item.has_sizes
      ? mergedGroups
      : item.customization_groups.map((group) => mapGroupToForm(group)),
  };
}

function parseInteger(value: string, fieldLabel: string): number {
  const number = Number.parseInt(value || "0", 10);
  if (!Number.isFinite(number) || number < 0) {
    throw new Error(`${fieldLabel} must be zero or greater.`);
  }
  return number;
}

function parsePrice(value: string, fieldLabel: string, allowZero = false): number {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0 || (!allowZero && number <= 0)) {
    throw new Error(
      allowZero
        ? `${fieldLabel} must be zero or greater.`
        : `${fieldLabel} must be greater than zero.`,
    );
  }
  return number;
}

function buildOptionPayload(
  option: MenuItemCustomizationOptionFormState,
  groupTitle: string,
): MenuItemCustomizationOptionPayload {
  const name = option.name.trim();
  if (!name) {
    throw new Error(`Each option in ${groupTitle} needs a name.`);
  }
  return {
    name,
    extra_price: parsePrice(option.extra_price || "0", `${name} price`, true),
    is_active: option.is_active,
    is_countable: option.is_countable,
    sort_order: parseInteger(option.sort_order, `${name} sort order`),
  };
}

function buildGroupPayload(
  group: MenuItemCustomizationGroupFormState,
  scopeLabel: string,
): MenuItemCustomizationGroupPayload {
  const title = group.title.trim();
  if (!title) {
    throw new Error(`${scopeLabel} customization groups need a title.`);
  }
  const minSelection = parseInteger(group.min_selection, `${title} min selection`);
  const maxSelection = parseInteger(group.max_selection, `${title} max selection`);
  if (group.selection_type === "SINGLE" && maxSelection !== 1) {
    throw new Error(`${title} must use max selection 1 for single select.`);
  }
  if (maxSelection < minSelection) {
    throw new Error(`${title} max selection cannot be less than min selection.`);
  }
  if (group.is_required && minSelection < 1) {
    throw new Error(`${title} must require at least one selection.`);
  }
  const options = group.options.map((option) => buildOptionPayload(option, title));
  if (!options.length) {
    throw new Error(`${title} needs at least one option.`);
  }
  return {
    title,
    selection_type: group.selection_type,
    is_required: group.is_required,
    min_selection: minSelection,
    max_selection: maxSelection,
    is_active: group.is_active,
    sort_order: parseInteger(group.sort_order, `${title} sort order`),
    options,
  };
}

function buildSizePayload(
  size: MenuItemSizeFormState,
  customizationGroups: MenuItemCustomizationGroupPayload[] = [],
): MenuItemSizePayload {
  const name = size.name.trim();
  if (!name) {
    throw new Error("Each size needs a name.");
  }
  return {
    name,
    price: parsePrice(size.price, `${name} price`),
    is_active: size.is_active,
    sort_order: parseInteger(size.sort_order, `${name} sort order`),
    customization_groups: customizationGroups,
  };
}

export function buildMenuItemUpsertPayload(
  form: MenuItemFormState,
): MenuItemUpsertPayload {
  const name = form.name.trim();
  const category = form.category.trim();
  if (!name) {
    throw new Error("Item name is required.");
  }
  if (!category) {
    throw new Error("Category is required.");
  }

  let sizes: MenuItemSizePayload[] = [];
  let customizationGroups: MenuItemCustomizationGroupPayload[] = [];

  if (form.has_sizes) {
    const sizePayloadGroups = new Map<string, MenuItemCustomizationGroupPayload[]>();
    form.sizes.forEach((size) => {
      sizePayloadGroups.set(size.id, []);
    });

    if (form.has_customizations) {
      form.customization_groups.forEach((group) => {
        if (!group.available_size_ids.length) {
          throw new Error(`${group.title.trim() || "Each customization group"} must be linked to at least one size.`);
        }

        const missingSizeIds = group.available_size_ids.filter(
          (sizeId) => !sizePayloadGroups.has(sizeId),
        );
        if (missingSizeIds.length) {
          throw new Error("A customization group is linked to a size that no longer exists.");
        }

        const groupPayload = buildGroupPayload(group, name);
        group.available_size_ids.forEach((sizeId) => {
          sizePayloadGroups.get(sizeId)?.push(groupPayload);
        });
      });
    }

    sizes = form.sizes.map((size) =>
      buildSizePayload(size, sizePayloadGroups.get(size.id) ?? []),
    );
  } else {
    sizes = [];
  }

  if (form.has_sizes && !sizes.some((size) => size.is_active)) {
    throw new Error("At least one active size is required.");
  }

  if (form.has_customizations && !form.has_sizes) {
    customizationGroups = form.customization_groups.map((group) => buildGroupPayload(group, name));
  }

  const sizeCustomizationCount = sizes.reduce(
    (count, size) => count + size.customization_groups.filter((group) => group.is_active).length,
    0,
  );
  if (
    form.has_customizations &&
    !customizationGroups.some((group) => group.is_active) &&
    sizeCustomizationCount === 0
  ) {
    throw new Error("Add at least one active customization group.");
  }

  const fallbackPrice = form.has_sizes
    ? Math.min(...sizes.filter((size) => size.is_active).map((size) => size.price))
    : parsePrice(form.price, "Price");

  return {
    name,
    category,
    cuisine_type: form.cuisine_type.trim() || null,
    description: form.description.trim() || null,
    price: fallbackPrice,
    is_veg: form.is_veg,
    is_available: form.is_available,
    is_new_launch: form.is_new_launch,
    image_url: form.image_url.trim() || null,
    launched_at: toApiDateTimeValue(form.launched_at),
    has_sizes: form.has_sizes,
    has_customizations: form.has_customizations,
    sizes,
    customization_groups: customizationGroups,
  };
}

function updateSizeAt(
  sizes: MenuItemSizeFormState[],
  sizeId: string,
  updater: (size: MenuItemSizeFormState) => MenuItemSizeFormState,
): MenuItemSizeFormState[] {
  return sizes.map((size) => (size.id === sizeId ? updater(size) : size));
}

function updateGroupAt(
  groups: MenuItemCustomizationGroupFormState[],
  groupId: string,
  updater: (group: MenuItemCustomizationGroupFormState) => MenuItemCustomizationGroupFormState,
): MenuItemCustomizationGroupFormState[] {
  return groups.map((group) => (group.id === groupId ? updater(group) : group));
}

function updateOptionAt(
  options: MenuItemCustomizationOptionFormState[],
  optionId: string,
  updater: (
    option: MenuItemCustomizationOptionFormState,
  ) => MenuItemCustomizationOptionFormState,
): MenuItemCustomizationOptionFormState[] {
  return options.map((option) => (option.id === optionId ? updater(option) : option));
}

function updateTextField<T extends keyof MenuItemFormState>(
  event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  form: MenuItemFormState,
  onChange: (nextForm: MenuItemFormState) => void,
  key: T,
): void {
  onChange({ ...form, [key]: event.target.value });
}

export function MenuItemCustomizationEditor({
  form,
  onChange,
}: MenuItemCustomizationEditorProps) {
  const [sizeDraft, setSizeDraft] = useState({ name: "", price: "" });
  const [sizeDraftError, setSizeDraftError] = useState<string | null>(null);
  const [editingSizeId, setEditingSizeId] = useState<string | null>(null);
  const [editingSizeDraft, setEditingSizeDraft] = useState({ name: "", price: "" });
  const [editingSizeError, setEditingSizeError] = useState<string | null>(null);
  const [groupDrafts, setGroupDrafts] = useState<
    Record<string, MenuItemCustomizationGroupDraftState>
  >({});
  const [groupDraftErrors, setGroupDraftErrors] = useState<Record<string, string | null>>({});
  const [expandedGroupKey, setExpandedGroupKey] = useState<string | null>(null);
  const [editingGroupKey, setEditingGroupKey] = useState<string | null>(null);
  const [editingGroupDraft, setEditingGroupDraft] = useState<MenuItemCustomizationGroupDraftState>(
    createEmptyGroupDraftState,
  );
  const [editingGroupError, setEditingGroupError] = useState<string | null>(null);
  const [optionDrafts, setOptionDrafts] = useState<
    Record<string, MenuItemCustomizationOptionDraftState>
  >({});
  const [optionDraftErrors, setOptionDraftErrors] = useState<Record<string, string | null>>({});
  const [editingOptionKey, setEditingOptionKey] = useState<string | null>(null);
  const [editingOptionDraft, setEditingOptionDraft] = useState<MenuItemCustomizationOptionDraftState>(
    createEmptyOptionDraftState,
  );
  const [editingOptionError, setEditingOptionError] = useState<string | null>(null);

  const updateTopLevelField =
    (key: keyof MenuItemFormState) =>
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      updateTextField(event, form, onChange, key);
    };

  const getScopeKey = (scope: "item" | "size", sizeId?: string) =>
    scope === "item" ? "item" : `size:${sizeId ?? "unknown"}`;

  const getGroupKey = (scope: "item" | "size", groupId: string, sizeId?: string) =>
    `${getScopeKey(scope, sizeId)}::${groupId}`;

  const getOptionKey = (
    scope: "item" | "size",
    groupId: string,
    optionId: string,
    sizeId?: string,
  ) => `${getGroupKey(scope, groupId, sizeId)}::${optionId}`;

  const getGroupsForScope = (scope: "item" | "size", sizeId?: string) =>
    scope === "item"
      ? form.customization_groups
      : form.sizes.find((size) => size.id === sizeId)?.customization_groups ?? [];

  const setGroupsForScope = (
    scope: "item" | "size",
    updater: (
      groups: MenuItemCustomizationGroupFormState[],
    ) => MenuItemCustomizationGroupFormState[],
    sizeId?: string,
  ) => {
    if (scope === "item") {
      onChange({
        ...form,
        customization_groups: updater(form.customization_groups),
      });
      return;
    }

    onChange({
      ...form,
      sizes: updateSizeAt(form.sizes, sizeId ?? "", (size) => ({
        ...size,
        customization_groups: updater(size.customization_groups),
      })),
    });
  };

  const getOptionsForGroup = (
    scope: "item" | "size",
    groupId: string,
    sizeId?: string,
  ) => getGroupsForScope(scope, sizeId).find((group) => group.id === groupId)?.options ?? [];

  const getGroupDraftForScope = (scope: "item" | "size", sizeId?: string) =>
    groupDrafts[getScopeKey(scope, sizeId)] ?? createEmptyGroupDraftState();

  const getGroupDraftErrorForScope = (scope: "item" | "size", sizeId?: string) =>
    groupDraftErrors[getScopeKey(scope, sizeId)] ?? null;

  const getOptionDraftForGroup = (
    scope: "item" | "size",
    groupId: string,
    sizeId?: string,
  ) => optionDrafts[getGroupKey(scope, groupId, sizeId)] ?? createEmptyOptionDraftState();

  const getOptionDraftErrorForGroup = (
    scope: "item" | "size",
    groupId: string,
    sizeId?: string,
  ) => optionDraftErrors[getGroupKey(scope, groupId, sizeId)] ?? null;

  useEffect(() => {
    if (editingSizeId && !form.sizes.some((size) => size.id === editingSizeId)) {
      setEditingSizeId(null);
      setEditingSizeDraft({ name: "", price: "" });
      setEditingSizeError(null);
    }
  }, [editingSizeId, form.sizes]);

  useEffect(() => {
    const activeGroupKeys = new Set<string>();
    const activeOptionKeys = new Set<string>();

    form.customization_groups.forEach((group) => {
      const groupKey = getGroupKey("item", group.id);
      activeGroupKeys.add(groupKey);
      group.options.forEach((option) => {
        activeOptionKeys.add(getOptionKey("item", group.id, option.id));
      });
    });

    form.sizes.forEach((size) => {
      size.customization_groups.forEach((group) => {
        const groupKey = getGroupKey("size", group.id, size.id);
        activeGroupKeys.add(groupKey);
        group.options.forEach((option) => {
          activeOptionKeys.add(getOptionKey("size", group.id, option.id, size.id));
        });
      });
    });

    if (expandedGroupKey && !activeGroupKeys.has(expandedGroupKey)) {
      setExpandedGroupKey(null);
    }
    if (editingGroupKey && !activeGroupKeys.has(editingGroupKey)) {
      setEditingGroupKey(null);
      setEditingGroupDraft(createEmptyGroupDraftState());
      setEditingGroupError(null);
    }
    if (editingOptionKey && !activeOptionKeys.has(editingOptionKey)) {
      setEditingOptionKey(null);
      setEditingOptionDraft(createEmptyOptionDraftState());
      setEditingOptionError(null);
    }
  }, [editingGroupKey, editingOptionKey, expandedGroupKey, form.customization_groups, form.sizes]);

  useEffect(() => {
    if (!form.has_sizes) {
      return;
    }

    const validSizeIds = new Set(form.sizes.map((size) => size.id));

    setGroupDrafts((current) => {
      let hasChanged = false;
      const nextDrafts = Object.fromEntries(
        Object.entries(current).map(([key, draft]) => {
          const nextAvailableSizeIds = draft.available_size_ids.filter((entry) =>
            validSizeIds.has(entry),
          );
          if (nextAvailableSizeIds.length !== draft.available_size_ids.length) {
            hasChanged = true;
            return [key, { ...draft, available_size_ids: nextAvailableSizeIds }];
          }
          return [key, draft];
        }),
      );
      return hasChanged ? nextDrafts : current;
    });

    setEditingGroupDraft((current) => {
      const nextAvailableSizeIds = current.available_size_ids.filter((entry) =>
        validSizeIds.has(entry),
      );
      if (nextAvailableSizeIds.length === current.available_size_ids.length) {
        return current;
      }
      return {
        ...current,
        available_size_ids: nextAvailableSizeIds,
      };
    });
  }, [form.has_sizes, form.sizes]);

  const toggleHasSizes = (checked: boolean) => {
    const nextSizes = checked ? form.sizes : [];
    const availableSizeIds = checked ? nextSizes.map((size) => size.id) : [];
    const shouldTurnOffCustomizations = checked && nextSizes.length === 0;

    onChange({
      ...form,
      has_sizes: checked,
      sizes: nextSizes,
      has_customizations: shouldTurnOffCustomizations ? false : form.has_customizations,
      customization_groups: shouldTurnOffCustomizations
        ? []
        : checked
        ? form.customization_groups.map((group) => ({
            ...group,
            available_size_ids:
              group.available_size_ids.length > 0
                ? group.available_size_ids.filter((sizeId) =>
                    availableSizeIds.includes(sizeId),
                  )
                : [...availableSizeIds],
          }))
        : form.customization_groups.map((group) => ({
            ...group,
            available_size_ids: [],
          })),
    });
  };

  const toggleHasCustomizations = (checked: boolean) => {
    onChange({
      ...form,
      has_customizations: checked,
      customization_groups: checked
        ? form.customization_groups
        : [],
      sizes: form.sizes.map((size) => ({ ...size, customization_groups: [] })),
    });
  };

  const validateSizeDraft = (
    name: string,
    price: string,
    excludeId?: string,
  ): string | null => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      return "Size name is required.";
    }
    if (!price.trim()) {
      return "Price is required.";
    }
    const numericPrice = Number(price);
    if (!Number.isFinite(numericPrice) || numericPrice <= 0) {
      return "Price must be a valid number greater than zero.";
    }
    const normalizedName = normalizeSizeName(trimmedName);
    const duplicateExists = form.sizes.some(
      (size) =>
        size.id !== excludeId && normalizeSizeName(size.name) === normalizedName,
    );
    if (duplicateExists) {
      return "Size name already exists.";
    }
    return null;
  };

  const addSize = () => {
    const error = validateSizeDraft(sizeDraft.name, sizeDraft.price);
    if (error) {
      setSizeDraftError(error);
      return;
    }

    const nextSortOrder = String(
      form.sizes.reduce((max, size) => Math.max(max, Number(size.sort_order) || 0), -1) + 1,
    );
    const nextSize = createEmptySize();
    nextSize.name = sizeDraft.name.trim();
    nextSize.price = sizeDraft.price.trim();
    nextSize.sort_order = nextSortOrder;
    onChange({
      ...form,
      sizes: [...form.sizes, nextSize],
    });
    setSizeDraft({ name: "", price: "" });
    setSizeDraftError(null);
  };

  const startEditingSize = (size: MenuItemSizeFormState) => {
    setEditingSizeId(size.id);
    setEditingSizeDraft({
      name: size.name,
      price: size.price,
    });
    setEditingSizeError(null);
  };

  const cancelEditingSize = () => {
    setEditingSizeId(null);
    setEditingSizeDraft({ name: "", price: "" });
    setEditingSizeError(null);
  };

  const saveEditingSize = (sizeId: string) => {
    const error = validateSizeDraft(
      editingSizeDraft.name,
      editingSizeDraft.price,
      sizeId,
    );
    if (error) {
      setEditingSizeError(error);
      return;
    }

    onChange({
      ...form,
      sizes: updateSizeAt(form.sizes, sizeId, (size) => ({
        ...size,
        name: editingSizeDraft.name.trim(),
        price: editingSizeDraft.price.trim(),
      })),
    });
    cancelEditingSize();
  };

  const removeSize = (sizeId: string) => {
    const nextSizes = form.sizes.filter((entry) => entry.id !== sizeId);
    const shouldTurnOffCustomizations = form.has_sizes && nextSizes.length === 0;

    const nextGroups = shouldTurnOffCustomizations
      ? []
      : form.customization_groups
          .map((group) => ({
            ...group,
            available_size_ids: group.available_size_ids.filter((entry) => entry !== sizeId),
          }))
          .filter((group) => !form.has_sizes || group.available_size_ids.length > 0);

    onChange({
      ...form,
      sizes: nextSizes,
      has_customizations: shouldTurnOffCustomizations ? false : form.has_customizations,
      customization_groups: nextGroups,
    });
    if (editingSizeId === sizeId) {
      cancelEditingSize();
    }
  };

  const toggleSizeActive = (sizeId: string) => {
    onChange({
      ...form,
      sizes: updateSizeAt(form.sizes, sizeId, (size) => ({
        ...size,
        is_active: !size.is_active,
      })),
    });
  };

  const validateGroupDraft = (
    draft: MenuItemCustomizationGroupDraftState,
    scope: "item" | "size",
    sizeId?: string,
  ): string | null => {
    const title = draft.title.trim();
    if (!title) {
      return "Group title is required.";
    }

    const minSelection = Number.parseInt(draft.min_selection || "0", 10);
    const maxSelection = Number.parseInt(draft.max_selection || "0", 10);
    if (!Number.isFinite(minSelection) || minSelection < 0) {
      return "Min selection must be zero or greater.";
    }
    if (!Number.isFinite(maxSelection) || maxSelection < 0) {
      return "Max selection must be zero or greater.";
    }
    if (draft.selection_type === "SINGLE" && maxSelection !== 1) {
      return "Single select groups must use max selection 1.";
    }
    if (maxSelection < minSelection) {
      return "Max selection cannot be less than min selection.";
    }
    if (draft.is_required && minSelection < 1) {
      return "Required groups must use min selection 1 or greater.";
    }

    if (scope === "item" && form.has_sizes && draft.available_size_ids.length === 0) {
      return "Select at least one size for this group.";
    }

    const duplicateExists = getGroupsForScope(scope, sizeId).some(
      (group) => normalizeSizeName(group.title) === normalizeSizeName(title),
    );
    if (duplicateExists) {
      return "Group title already exists in this section.";
    }

    return null;
  };

  const validateEditingGroupDraft = (
    draft: MenuItemCustomizationGroupDraftState,
    scope: "item" | "size",
    groupId: string,
    sizeId?: string,
  ): string | null => {
    const baseError = validateGroupDraft(draft, scope, sizeId);
    if (baseError && baseError !== "Group title already exists in this section.") {
      return baseError;
    }
    const duplicateExists = getGroupsForScope(scope, sizeId).some(
      (group) =>
        group.id !== groupId &&
        normalizeSizeName(group.title) === normalizeSizeName(draft.title),
    );
    if (duplicateExists) {
      return "Group title already exists in this section.";
    }
    return baseError === "Group title already exists in this section." ? null : baseError;
  };

  const addGroupFromDraft = (scope: "item" | "size", sizeId?: string) => {
    const sectionKey = getScopeKey(scope, sizeId);
    const draft = getGroupDraftForScope(scope, sizeId);
    const error = validateGroupDraft(draft, scope, sizeId);
    if (error) {
      setGroupDraftErrors((current) => ({ ...current, [sectionKey]: error }));
      return;
    }

    const nextSortOrder = String(
      getGroupsForScope(scope, sizeId).reduce(
        (max, group) => Math.max(max, Number(group.sort_order) || 0),
        -1,
      ) + 1,
    );
    const nextGroup = createEmptyGroup();
    nextGroup.title = draft.title.trim();
    nextGroup.available_size_ids = [...draft.available_size_ids];
    nextGroup.selection_type = draft.selection_type;
    nextGroup.min_selection = draft.min_selection;
    nextGroup.max_selection = draft.max_selection;
    nextGroup.is_required = draft.is_required;
    nextGroup.is_active = draft.is_active;
    nextGroup.sort_order = nextSortOrder;

    setGroupsForScope(
      scope,
      (groups) => [...groups, nextGroup],
      sizeId,
    );
    setGroupDrafts((current) => ({
      ...current,
      [sectionKey]: createEmptyGroupDraftState(),
    }));
    setGroupDraftErrors((current) => ({ ...current, [sectionKey]: null }));
  };

  const startEditingGroup = (
    scope: "item" | "size",
    group: MenuItemCustomizationGroupFormState,
    sizeId?: string,
  ) => {
    const groupKey = getGroupKey(scope, group.id, sizeId);
    setExpandedGroupKey(groupKey);
    setEditingGroupKey(groupKey);
    setEditingGroupDraft(createGroupDraftStateFromGroup(group));
    setEditingGroupError(null);
  };

  const cancelEditingGroup = () => {
    setEditingGroupKey(null);
    setEditingGroupDraft(createEmptyGroupDraftState());
    setEditingGroupError(null);
  };

  const saveEditingGroup = (
    scope: "item" | "size",
    groupId: string,
    sizeId?: string,
  ) => {
    const error = validateEditingGroupDraft(editingGroupDraft, scope, groupId, sizeId);
    if (error) {
      setEditingGroupError(error);
      return;
    }

    setGroupsForScope(
      scope,
      (groups) =>
        updateGroupAt(groups, groupId, (group) => ({
          ...group,
          title: editingGroupDraft.title.trim(),
          available_size_ids: [...editingGroupDraft.available_size_ids],
          selection_type: editingGroupDraft.selection_type,
          min_selection: editingGroupDraft.min_selection,
          max_selection: editingGroupDraft.max_selection,
          is_required: editingGroupDraft.is_required,
          is_active: editingGroupDraft.is_active,
        })),
      sizeId,
    );
    cancelEditingGroup();
  };

  const toggleGroupActive = (
    scope: "item" | "size",
    groupId: string,
    sizeId?: string,
  ) => {
    setGroupsForScope(
      scope,
      (groups) =>
        updateGroupAt(groups, groupId, (group) => ({
          ...group,
          is_active: !group.is_active,
        })),
      sizeId,
    );
  };

  const removeGroup = (scope: "item" | "size", groupId: string, sizeId?: string) => {
    const groupKey = getGroupKey(scope, groupId, sizeId);
    setGroupsForScope(
      scope,
      (groups) => groups.filter((group) => group.id !== groupId),
      sizeId,
    );
    if (expandedGroupKey === groupKey) {
      setExpandedGroupKey(null);
    }
    if (editingGroupKey === groupKey) {
      cancelEditingGroup();
    }
  };

  const validateOptionDraft = (
    draft: MenuItemCustomizationOptionDraftState,
    scope: "item" | "size",
    groupId: string,
    sizeId?: string,
    excludeOptionId?: string,
  ): string | null => {
    const name = draft.name.trim();
    if (!name) {
      return "Option name is required.";
    }
    const numericPrice = Number(draft.extra_price);
    if (!Number.isFinite(numericPrice) || numericPrice < 0) {
      return "Extra price must be a valid number.";
    }
    const duplicateExists = getOptionsForGroup(scope, groupId, sizeId).some(
      (option) =>
        option.id !== excludeOptionId &&
        normalizeSizeName(option.name) === normalizeSizeName(name),
    );
    if (duplicateExists) {
      return "Option name already exists in this group.";
    }
    return null;
  };

  const addOptionFromDraft = (
    scope: "item" | "size",
    groupId: string,
    sizeId?: string,
  ) => {
    const groupKey = getGroupKey(scope, groupId, sizeId);
    const draft = getOptionDraftForGroup(scope, groupId, sizeId);
    const error = validateOptionDraft(draft, scope, groupId, sizeId);
    if (error) {
      setOptionDraftErrors((current) => ({ ...current, [groupKey]: error }));
      return;
    }

    const nextSortOrder = String(
      getOptionsForGroup(scope, groupId, sizeId).reduce(
        (max, option) => Math.max(max, Number(option.sort_order) || 0),
        -1,
      ) + 1,
    );
    const nextOption = createEmptyOption();
    nextOption.name = draft.name.trim();
    nextOption.extra_price = draft.extra_price.trim();
    nextOption.is_countable = draft.is_countable;
    nextOption.is_active = draft.is_active;
    nextOption.sort_order = nextSortOrder;

    setGroupsForScope(
      scope,
      (groups) =>
        updateGroupAt(groups, groupId, (group) => ({
          ...group,
          options: [...group.options, nextOption],
        })),
      sizeId,
    );
    setOptionDrafts((current) => ({
      ...current,
      [groupKey]: createEmptyOptionDraftState(),
    }));
    setOptionDraftErrors((current) => ({ ...current, [groupKey]: null }));
  };

  const startEditingOption = (
    scope: "item" | "size",
    groupId: string,
    option: MenuItemCustomizationOptionFormState,
    sizeId?: string,
  ) => {
    setEditingOptionKey(getOptionKey(scope, groupId, option.id, sizeId));
    setEditingOptionDraft(createOptionDraftStateFromOption(option));
    setEditingOptionError(null);
  };

  const cancelEditingOption = () => {
    setEditingOptionKey(null);
    setEditingOptionDraft(createEmptyOptionDraftState());
    setEditingOptionError(null);
  };

  const saveEditingOption = (
    scope: "item" | "size",
    groupId: string,
    optionId: string,
    sizeId?: string,
  ) => {
    const error = validateOptionDraft(
      editingOptionDraft,
      scope,
      groupId,
      sizeId,
      optionId,
    );
    if (error) {
      setEditingOptionError(error);
      return;
    }

    setGroupsForScope(
      scope,
      (groups) =>
        updateGroupAt(groups, groupId, (group) => ({
          ...group,
          options: updateOptionAt(group.options, optionId, (option) => ({
            ...option,
            name: editingOptionDraft.name.trim(),
            extra_price: editingOptionDraft.extra_price.trim(),
            is_countable: editingOptionDraft.is_countable,
            is_active: editingOptionDraft.is_active,
          })),
        })),
      sizeId,
    );
    cancelEditingOption();
  };

  const toggleOptionActive = (
    scope: "item" | "size",
    groupId: string,
    optionId: string,
    sizeId?: string,
  ) => {
    setGroupsForScope(
      scope,
      (groups) =>
        updateGroupAt(groups, groupId, (group) => ({
          ...group,
          options: updateOptionAt(group.options, optionId, (option) => ({
            ...option,
            is_active: !option.is_active,
          })),
        })),
      sizeId,
    );
  };

  const removeOption = (
    scope: "item" | "size",
    groupId: string,
    optionId: string,
    sizeId?: string,
  ) => {
    setGroupsForScope(
      scope,
      (groups) =>
        updateGroupAt(groups, groupId, (group) => ({
          ...group,
          options: group.options.filter((option) => option.id !== optionId),
        })),
      sizeId,
    );
    if (editingOptionKey === getOptionKey(scope, groupId, optionId, sizeId)) {
      cancelEditingOption();
    }
  };

  const toggleGroupDraftSize = (
    currentSizeIds: string[],
    targetSizeId: string,
  ) =>
    currentSizeIds.includes(targetSizeId)
      ? currentSizeIds.filter((sizeId) => sizeId !== targetSizeId)
      : [...currentSizeIds, targetSizeId];

  const renderGroupManager = (
    scope: "item" | "size",
    groups: MenuItemCustomizationGroupFormState[],
    sizeId?: string,
  ) => {
    const scopeKey = getScopeKey(scope, sizeId);
    const draft = getGroupDraftForScope(scope, sizeId);
    const draftError = getGroupDraftErrorForScope(scope, sizeId);
    const sizeChoices = form.sizes.map((size) => ({
      id: size.id,
      name: size.name || "Untitled size",
    }));
    const showSizeAvailability = scope === "item" && form.has_sizes;

    return (
      <div className="menu-customization-stack">
        <div
          className={`menu-group-composer ${
            showSizeAvailability ? "menu-group-composer--with-sizes" : ""
          }`}
        >
          <label className="field">
            <span>Group title</span>
            <input
              placeholder="Choose crust"
              value={draft.title}
              onChange={(event) => {
                setGroupDrafts((current) => ({
                  ...current,
                  [scopeKey]: {
                    ...draft,
                    title: event.target.value,
                  },
                }));
                if (draftError) {
                  setGroupDraftErrors((current) => ({ ...current, [scopeKey]: null }));
                }
              }}
            />
          </label>
          <label className="field">
            <span>Selection type</span>
            <select
              value={draft.selection_type}
              onChange={(event) => {
                const nextSelectionType =
                  event.target.value as MenuItemCustomizationSelectionType;
                setGroupDrafts((current) => ({
                  ...current,
                  [scopeKey]: {
                    ...draft,
                    selection_type: nextSelectionType,
                    max_selection:
                      nextSelectionType === "SINGLE"
                        ? "1"
                        : draft.max_selection,
                  },
                }));
                if (draftError) {
                  setGroupDraftErrors((current) => ({ ...current, [scopeKey]: null }));
                }
              }}
            >
              <option value="SINGLE">Single</option>
              <option value="MULTI">Multi</option>
            </select>
          </label>
          <label className="field">
            <span>Min selection</span>
            <input
              min="0"
              step="1"
              type="number"
              value={draft.min_selection}
              onChange={(event) => {
                setGroupDrafts((current) => ({
                  ...current,
                  [scopeKey]: {
                    ...draft,
                    min_selection: event.target.value,
                  },
                }));
                if (draftError) {
                  setGroupDraftErrors((current) => ({ ...current, [scopeKey]: null }));
                }
              }}
            />
          </label>
          <label className="field">
            <span>Max selection</span>
            <input
              min="0"
              step="1"
              type="number"
              value={draft.max_selection}
              onChange={(event) => {
                setGroupDrafts((current) => ({
                  ...current,
                  [scopeKey]: {
                    ...draft,
                    max_selection: event.target.value,
                  },
                }));
                if (draftError) {
                  setGroupDraftErrors((current) => ({ ...current, [scopeKey]: null }));
                }
              }}
            />
          </label>
          <Checkbox
            checked={draft.is_required}
            label="Required"
            onChange={(checked) =>
              setGroupDrafts((current) => ({
                ...current,
                [scopeKey]: {
                  ...draft,
                  is_required: checked,
                },
              }))
            }
          />
          <Checkbox
            checked={draft.is_active}
            label="Active"
            onChange={(checked) =>
              setGroupDrafts((current) => ({
                ...current,
                [scopeKey]: {
                  ...draft,
                  is_active: checked,
                },
              }))
            }
          />
          {showSizeAvailability ? (
            <div className="menu-group-size-availability">
              <span>Available for sizes</span>
              <div className="menu-group-size-availability__list">
                {sizeChoices.length ? (
                  sizeChoices.map((sizeChoice) => (
                    <Checkbox
                      checked={draft.available_size_ids.includes(sizeChoice.id)}
                      key={sizeChoice.id}
                      label={sizeChoice.name}
                      onChange={() => {
                        setGroupDrafts((current) => ({
                          ...current,
                          [scopeKey]: {
                            ...draft,
                            available_size_ids: toggleGroupDraftSize(
                              draft.available_size_ids,
                              sizeChoice.id,
                            ),
                          },
                        }));
                        if (draftError) {
                          setGroupDraftErrors((current) => ({ ...current, [scopeKey]: null }));
                        }
                      }}
                      size="sm"
                      variant="ghost"
                    />
                  ))
                ) : (
                  <span className="hint-text">Add sizes first to map this group.</span>
                )}
              </div>
            </div>
          ) : null}
          <button
            className="secondary-button menu-group-composer__button"
            onClick={() => addGroupFromDraft(scope, sizeId)}
            type="button"
          >
            <Plus size={14} />
            Add group
          </button>
        </div>

        {draftError ? <p className="menu-size-inline-error">{draftError}</p> : null}

        {groups.length ? (
          <div
            className={`menu-group-list ${
              showSizeAvailability ? "menu-group-list--with-sizes" : ""
            }`}
          >
            <div className="menu-group-list__header">
              <span>Group title</span>
              {showSizeAvailability ? <span>Sizes</span> : null}
              <span>Type</span>
              <span>Required</span>
              <span>Min/Max</span>
              <span>Status</span>
              <span>Actions</span>
            </div>

            {groups.map((group) => {
              const groupKey = getGroupKey(scope, group.id, sizeId);
              const isEditingGroup = editingGroupKey === groupKey;
              const isExpanded = expandedGroupKey === groupKey;
              const optionDraft = getOptionDraftForGroup(scope, group.id, sizeId);
              const optionDraftError = getOptionDraftErrorForGroup(scope, group.id, sizeId);

              return (
                <div className="menu-group-list__item" key={group.id}>
                  {isEditingGroup ? (
                    <div className="menu-group-editor">
                      <div className="menu-group-editor__row">
                        <label className="field">
                          <span>Group title</span>
                          <input
                            placeholder="Choose crust"
                            value={editingGroupDraft.title}
                            onChange={(event) => {
                              setEditingGroupDraft((current) => ({
                                ...current,
                                title: event.target.value,
                              }));
                              if (editingGroupError) {
                                setEditingGroupError(null);
                              }
                            }}
                          />
                        </label>
                        <label className="field">
                          <span>Selection type</span>
                          <select
                            value={editingGroupDraft.selection_type}
                            onChange={(event) => {
                              const nextSelectionType =
                                event.target.value as MenuItemCustomizationSelectionType;
                              setEditingGroupDraft((current) => ({
                                ...current,
                                selection_type: nextSelectionType,
                                max_selection:
                                  nextSelectionType === "SINGLE"
                                    ? "1"
                                    : current.max_selection,
                              }));
                              if (editingGroupError) {
                                setEditingGroupError(null);
                              }
                            }}
                          >
                            <option value="SINGLE">Single</option>
                            <option value="MULTI">Multi</option>
                          </select>
                        </label>
                        <label className="field">
                          <span>Min selection</span>
                          <input
                            min="0"
                            step="1"
                            type="number"
                            value={editingGroupDraft.min_selection}
                            onChange={(event) => {
                              setEditingGroupDraft((current) => ({
                                ...current,
                                min_selection: event.target.value,
                              }));
                              if (editingGroupError) {
                                setEditingGroupError(null);
                              }
                            }}
                          />
                        </label>
                        <label className="field">
                          <span>Max selection</span>
                          <input
                            min="0"
                            step="1"
                            type="number"
                            value={editingGroupDraft.max_selection}
                            onChange={(event) => {
                              setEditingGroupDraft((current) => ({
                                ...current,
                                max_selection: event.target.value,
                              }));
                              if (editingGroupError) {
                                setEditingGroupError(null);
                              }
                            }}
                          />
                        </label>
                      </div>
                      {showSizeAvailability ? (
                        <div className="menu-group-size-availability">
                          <span>Available for sizes</span>
                          <div className="menu-group-size-availability__list">
                            {sizeChoices.length ? (
                              sizeChoices.map((sizeChoice) => (
                                <Checkbox
                                  checked={editingGroupDraft.available_size_ids.includes(
                                    sizeChoice.id,
                                  )}
                                  key={sizeChoice.id}
                                  label={sizeChoice.name}
                                  onChange={() =>
                                    setEditingGroupDraft((current) => ({
                                      ...current,
                                      available_size_ids: toggleGroupDraftSize(
                                        current.available_size_ids,
                                        sizeChoice.id,
                                      ),
                                    }))
                                  }
                                  size="sm"
                                  variant="ghost"
                                />
                              ))
                            ) : (
                              <span className="hint-text">Add sizes first to map this group.</span>
                            )}
                          </div>
                        </div>
                      ) : null}
                      <div className="menu-group-editor__toggles">
                        <Checkbox
                          checked={editingGroupDraft.is_required}
                          label="Required"
                          onChange={(checked) =>
                            setEditingGroupDraft((current) => ({
                              ...current,
                              is_required: checked,
                            }))
                          }
                        />
                        <Checkbox
                          checked={editingGroupDraft.is_active}
                          label="Active"
                          onChange={(checked) =>
                            setEditingGroupDraft((current) => ({
                              ...current,
                              is_active: checked,
                            }))
                          }
                        />
                      </div>
                      {editingGroupError ? (
                        <p className="menu-size-inline-error">{editingGroupError}</p>
                      ) : null}
                      <div className="menu-group-editor__actions">
                        <button
                          className="secondary-button"
                          onClick={() => saveEditingGroup(scope, group.id, sizeId)}
                          type="button"
                        >
                          Save
                        </button>
                        <button
                          className="secondary-button secondary-button--ghost"
                          onClick={cancelEditingGroup}
                          type="button"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="menu-group-list__row">
                      <div className="menu-group-list__cell menu-group-list__cell--name">
                        <span className="menu-size-list__cell-label">Group title</span>
                        <strong>{group.title || "Untitled group"}</strong>
                      </div>
                      {showSizeAvailability ? (
                        <div className="menu-group-list__cell">
                          <span className="menu-size-list__cell-label">Sizes</span>
                          <span>
                            {group.available_size_ids
                              .map(
                                (groupSizeId) =>
                                  sizeChoices.find((sizeChoice) => sizeChoice.id === groupSizeId)
                                    ?.name ?? "Removed size",
                              )
                              .join(", ")}
                          </span>
                        </div>
                      ) : null}
                      <div className="menu-group-list__cell">
                        <span className="menu-size-list__cell-label">Type</span>
                        <span>{group.selection_type === "SINGLE" ? "Single" : "Multi"}</span>
                      </div>
                      <div className="menu-group-list__cell">
                        <span className="menu-size-list__cell-label">Required</span>
                        <span>{group.is_required ? "Yes" : "No"}</span>
                      </div>
                      <div className="menu-group-list__cell">
                        <span className="menu-size-list__cell-label">Min/Max</span>
                        <span>
                          {group.min_selection}/{group.max_selection}
                        </span>
                      </div>
                      <div className="menu-group-list__cell">
                        <span className="menu-size-list__cell-label">Status</span>
                        <button
                          className={`menu-size-status-chip ${
                            group.is_active
                              ? "menu-size-status-chip--active"
                              : "menu-size-status-chip--inactive"
                          }`}
                          onClick={() => toggleGroupActive(scope, group.id, sizeId)}
                          type="button"
                        >
                          {group.is_active ? "Active" : "Inactive"}
                        </button>
                      </div>
                      <div className="menu-group-list__cell menu-group-list__cell--actions">
                        <span className="menu-size-list__cell-label">Actions</span>
                        <button
                          className="secondary-button secondary-button--ghost"
                          onClick={() => startEditingGroup(scope, group, sizeId)}
                          type="button"
                        >
                          Edit
                        </button>
                        <button
                          className="secondary-button secondary-button--ghost"
                          onClick={() => removeGroup(scope, group.id, sizeId)}
                          type="button"
                        >
                          Delete
                        </button>
                        <button
                          className="secondary-button secondary-button--ghost"
                          onClick={() =>
                            setExpandedGroupKey((current) =>
                              current === groupKey ? null : groupKey,
                            )
                          }
                          type="button"
                        >
                          {isExpanded ? "Hide Options" : "Manage Options"}
                        </button>
                      </div>
                    </div>
                  )}

                  {isExpanded ? (
                    <div className="menu-option-panel">
                      <div className="menu-option-panel__header">
                        <div>
                          <h4>Options for {group.title || "this group"}</h4>
                          <p className="hint-text">
                            Add extras, set prices, and mark countable options only when needed.
                          </p>
                        </div>
                      </div>

                      <div className="menu-option-composer">
                        <label className="field">
                          <span>Option name</span>
                          <input
                            placeholder="Cheese burst"
                            value={optionDraft.name}
                            onChange={(event) => {
                              setOptionDrafts((current) => ({
                                ...current,
                                [groupKey]: {
                                  ...optionDraft,
                                  name: event.target.value,
                                },
                              }));
                              if (optionDraftError) {
                                setOptionDraftErrors((current) => ({
                                  ...current,
                                  [groupKey]: null,
                                }));
                              }
                            }}
                          />
                        </label>
                        <label className="field">
                          <span>Extra price</span>
                          <input
                            min="0"
                            step="0.01"
                            type="number"
                            value={optionDraft.extra_price}
                            onChange={(event) => {
                              setOptionDrafts((current) => ({
                                ...current,
                                [groupKey]: {
                                  ...optionDraft,
                                  extra_price: event.target.value,
                                },
                              }));
                              if (optionDraftError) {
                                setOptionDraftErrors((current) => ({
                                  ...current,
                                  [groupKey]: null,
                                }));
                              }
                            }}
                          />
                        </label>
                        <Checkbox
                          checked={optionDraft.is_countable}
                          label="Countable"
                          onChange={(checked) =>
                            setOptionDrafts((current) => ({
                              ...current,
                              [groupKey]: {
                                ...optionDraft,
                                is_countable: checked,
                              },
                            }))
                          }
                        />
                        <Checkbox
                          checked={optionDraft.is_active}
                          label="Active"
                          onChange={(checked) =>
                            setOptionDrafts((current) => ({
                              ...current,
                              [groupKey]: {
                                ...optionDraft,
                                is_active: checked,
                              },
                            }))
                          }
                        />
                        <button
                          className="secondary-button menu-option-composer__button"
                          onClick={() => addOptionFromDraft(scope, group.id, sizeId)}
                          type="button"
                        >
                          <Plus size={14} />
                          Add option
                        </button>
                      </div>

                      {optionDraftError ? (
                        <p className="menu-size-inline-error">{optionDraftError}</p>
                      ) : null}

                      {group.options.length ? (
                        <div className="menu-option-list">
                          <div className="menu-option-list__header">
                            <span>Option name</span>
                            <span>Extra price</span>
                            <span>Countable</span>
                            <span>Status</span>
                            <span>Actions</span>
                          </div>
                          {group.options.map((option) => {
                            const isEditingOption =
                              editingOptionKey === getOptionKey(scope, group.id, option.id, sizeId);
                            return (
                              <div className="menu-option-list__item" key={option.id}>
                                {isEditingOption ? (
                                  <div className="menu-option-editor">
                                    <div className="menu-option-editor__row">
                                      <label className="field">
                                        <span>Option name</span>
                                        <input
                                          placeholder="Cheese burst"
                                          value={editingOptionDraft.name}
                                          onChange={(event) => {
                                            setEditingOptionDraft((current) => ({
                                              ...current,
                                              name: event.target.value,
                                            }));
                                            if (editingOptionError) {
                                              setEditingOptionError(null);
                                            }
                                          }}
                                        />
                                      </label>
                                      <label className="field">
                                        <span>Extra price</span>
                                        <input
                                          min="0"
                                          step="0.01"
                                          type="number"
                                          value={editingOptionDraft.extra_price}
                                          onChange={(event) => {
                                            setEditingOptionDraft((current) => ({
                                              ...current,
                                              extra_price: event.target.value,
                                            }));
                                            if (editingOptionError) {
                                              setEditingOptionError(null);
                                            }
                                          }}
                                        />
                                      </label>
                                    </div>
                                    <div className="menu-option-editor__toggles">
                                      <Checkbox
                                        checked={editingOptionDraft.is_countable}
                                        label="Countable"
                                        onChange={(checked) =>
                                          setEditingOptionDraft((current) => ({
                                            ...current,
                                            is_countable: checked,
                                          }))
                                        }
                                      />
                                      <Checkbox
                                        checked={editingOptionDraft.is_active}
                                        label="Active"
                                        onChange={(checked) =>
                                          setEditingOptionDraft((current) => ({
                                            ...current,
                                            is_active: checked,
                                          }))
                                        }
                                      />
                                    </div>
                                    {editingOptionError ? (
                                      <p className="menu-size-inline-error">{editingOptionError}</p>
                                    ) : null}
                                    <div className="menu-option-editor__actions">
                                      <button
                                        className="secondary-button"
                                        onClick={() =>
                                          saveEditingOption(scope, group.id, option.id, sizeId)
                                        }
                                        type="button"
                                      >
                                        Save
                                      </button>
                                      <button
                                        className="secondary-button secondary-button--ghost"
                                        onClick={cancelEditingOption}
                                        type="button"
                                      >
                                        Cancel
                                      </button>
                                    </div>
                                  </div>
                                ) : (
                                  <div className="menu-option-list__row">
                                    <div className="menu-option-list__cell menu-option-list__cell--name">
                                      <span className="menu-size-list__cell-label">Option name</span>
                                      <strong>{option.name || "Untitled option"}</strong>
                                    </div>
                                    <div className="menu-option-list__cell">
                                      <span className="menu-size-list__cell-label">Extra price</span>
                                      <span>₹{option.extra_price}</span>
                                    </div>
                                    <div className="menu-option-list__cell">
                                      <span className="menu-size-list__cell-label">Countable</span>
                                      <span>{option.is_countable ? "Yes" : "No"}</span>
                                    </div>
                                    <div className="menu-option-list__cell">
                                      <span className="menu-size-list__cell-label">Status</span>
                                      <button
                                        className={`menu-size-status-chip ${
                                          option.is_active
                                            ? "menu-size-status-chip--active"
                                            : "menu-size-status-chip--inactive"
                                        }`}
                                        onClick={() =>
                                          toggleOptionActive(scope, group.id, option.id, sizeId)
                                        }
                                        type="button"
                                      >
                                        {option.is_active ? "Active" : "Inactive"}
                                      </button>
                                    </div>
                                    <div className="menu-option-list__cell menu-option-list__cell--actions">
                                      <span className="menu-size-list__cell-label">Actions</span>
                                      <button
                                        className="secondary-button secondary-button--ghost"
                                        onClick={() =>
                                          startEditingOption(scope, group.id, option, sizeId)
                                        }
                                        type="button"
                                      >
                                        Edit
                                      </button>
                                      <button
                                        className="secondary-button secondary-button--ghost"
                                        onClick={() =>
                                          removeOption(scope, group.id, option.id, sizeId)
                                        }
                                        type="button"
                                      >
                                        Delete
                                      </button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <p className="hint-text">No options added yet for this group.</p>
                      )}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="hint-text">No customization groups added yet.</p>
        )}
      </div>
    );
  };

  return (
    <>
      <div className="form-grid__wide menu-customization-section">
        <div className="menu-customization-section__header">
          <div>
            <h3>Pricing setup</h3>
            <p className="hint-text">
              Keep the base item simple, or switch on sizes and customization groups.
            </p>
          </div>
        </div>
        <div className="menu-customization-toggle-row">
          <Checkbox
            checked={form.has_sizes}
            label="Has sizes?"
            onChange={toggleHasSizes}
          />
          {!form.has_sizes ? (
            <Checkbox
              checked={form.has_customizations}
              label="Has customizations/toppings?"
              onChange={toggleHasCustomizations}
            />
          ) : form.sizes.length > 0 ? (
            <Checkbox
              checked={form.has_customizations}
              label="Has customizations/toppings?"
              onChange={toggleHasCustomizations}
            />
          ) : (
            <span
              className="hint-text"
              style={{
                display: "inline-flex",
                alignItems: "center",
                minHeight: "42px",
                margin: 0,
              }}
            >
              Add at least one size to enable toppings/customizations.
            </span>
          )}
        </div>
      </div>

      {!form.has_sizes ? (
        <label className="field">
          <span>Price</span>
          <input
            min="1"
            step="0.01"
            type="number"
            required
            value={form.price}
            onChange={updateTopLevelField("price")}
          />
        </label>
      ) : null}

      {form.has_sizes ? (
        <div className="form-grid__wide menu-customization-section">
          <div className="menu-customization-section__header">
            <div>
              <h3>Sizes</h3>
              <p className="hint-text">
                Add one or more active sizes. The menu item price will follow the lowest active size.
              </p>
            </div>
          </div>

          <div className="menu-customization-stack">
            <div className="menu-size-composer">
              <label className="field">
                <span>Size name</span>
                <input
                  placeholder="Small"
                  value={sizeDraft.name}
                  onChange={(event) => {
                    setSizeDraft((current) => ({ ...current, name: event.target.value }));
                    if (sizeDraftError) {
                      setSizeDraftError(null);
                    }
                  }}
                />
              </label>
              <label className="field">
                <span>Price</span>
                <input
                  min="1"
                  step="0.01"
                  type="number"
                  placeholder="99"
                  value={sizeDraft.price}
                  onChange={(event) => {
                    setSizeDraft((current) => ({ ...current, price: event.target.value }));
                    if (sizeDraftError) {
                      setSizeDraftError(null);
                    }
                  }}
                />
              </label>
              <button className="secondary-button menu-size-composer__button" onClick={addSize} type="button">
                <Plus size={14} />
                Add
              </button>
            </div>
            {sizeDraftError ? (
              <p className="menu-size-inline-error">{sizeDraftError}</p>
            ) : null}

            {form.sizes.length ? (
              <div className="menu-size-list">
                <div className="menu-size-list__header">
                  <span>Size name</span>
                  <span>Price</span>
                  <span>Status</span>
                  <span>Actions</span>
                </div>
                {form.sizes.map((size) => {
                  const isEditingSize = editingSizeId === size.id;
                  return (
                    <div className="menu-size-list__item" key={size.id}>
                      {isEditingSize ? (
                        <div className="menu-size-editor">
                          <div className="menu-size-editor__row">
                            <label className="field">
                              <span>Size name</span>
                              <input
                                placeholder="Large"
                                value={editingSizeDraft.name}
                                onChange={(event) => {
                                  setEditingSizeDraft((current) => ({
                                    ...current,
                                    name: event.target.value,
                                  }));
                                  if (editingSizeError) {
                                    setEditingSizeError(null);
                                  }
                                }}
                              />
                            </label>
                            <label className="field">
                              <span>Price</span>
                              <input
                                min="1"
                                step="0.01"
                                type="number"
                                value={editingSizeDraft.price}
                                onChange={(event) => {
                                  setEditingSizeDraft((current) => ({
                                    ...current,
                                    price: event.target.value,
                                  }));
                                  if (editingSizeError) {
                                    setEditingSizeError(null);
                                  }
                                }}
                              />
                            </label>
                          </div>
                          {editingSizeError ? (
                            <p className="menu-size-inline-error">{editingSizeError}</p>
                          ) : null}
                          <div className="menu-size-editor__actions">
                            <button
                              className="secondary-button"
                              onClick={() => saveEditingSize(size.id)}
                              type="button"
                            >
                              Save
                            </button>
                            <button
                              className="secondary-button secondary-button--ghost"
                              onClick={cancelEditingSize}
                              type="button"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="menu-size-list__row">
                          <div className="menu-size-list__cell menu-size-list__cell--name">
                            <span className="menu-size-list__cell-label">Size name</span>
                            <strong>{size.name || "Untitled size"}</strong>
                          </div>
                          <div className="menu-size-list__cell">
                            <span className="menu-size-list__cell-label">Price</span>
                            <span>{size.price ? `₹${size.price}` : "Pending"}</span>
                          </div>
                          <div className="menu-size-list__cell">
                            <span className="menu-size-list__cell-label">Status</span>
                            <button
                              className={`menu-size-status-chip ${
                                size.is_active
                                  ? "menu-size-status-chip--active"
                                  : "menu-size-status-chip--inactive"
                              }`}
                              onClick={() => toggleSizeActive(size.id)}
                              type="button"
                            >
                              {size.is_active ? "Active" : "Inactive"}
                            </button>
                          </div>
                          <div className="menu-size-list__cell menu-size-list__cell--actions">
                            <span className="menu-size-list__cell-label">Actions</span>
                            <button
                              className="secondary-button secondary-button--ghost"
                              onClick={() => startEditingSize(size)}
                              type="button"
                            >
                              Edit
                            </button>
                            <button
                              className="secondary-button secondary-button--ghost"
                              onClick={() => removeSize(size.id)}
                              type="button"
                            >
                              Delete
                            </button>
                          </div>
                        </div>
                      )}

                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="hint-text">
                No sizes added yet. Add at least one active size before saving.
              </p>
            )}
          </div>
        </div>
      ) : null}

      {form.has_customizations ? (
        <div className="form-grid__wide menu-customization-section">
          <div className="menu-customization-section__header">
            <div>
              <h3>Customizations</h3>
              <p className="hint-text">
                {form.has_sizes
                  ? "Add topping groups once, then choose exactly which sizes should show them."
                  : "Add topping groups for this item. Use countable options for extras that may need quantities later."}
              </p>
            </div>
          </div>
          {renderGroupManager("item", form.customization_groups)}
        </div>
      ) : null}
    </>
  );
}
