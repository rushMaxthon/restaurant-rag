from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize

TWO_PLACES = Decimal("0.01")
logger = logging.getLogger(__name__)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _safe_decimal(value: Decimal | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return _quantize(value)
    return _quantize(Decimal(str(value)))


@dataclass(slots=True)
class SelectedCustomizationOptionInput:
    option_id: uuid.UUID
    quantity: int = 1


@dataclass(slots=True)
class ResolvedCustomizationOption:
    group_id: uuid.UUID
    group_title: str
    selection_type: str
    option_id: uuid.UUID
    option_name: str
    extra_price: Decimal
    quantity: int
    is_countable: bool

    def to_snapshot(self) -> dict[str, object]:
        return {
            "group_id": str(self.group_id),
            "group_title": self.group_title,
            "selection_type": self.selection_type,
            "option_id": str(self.option_id),
            "option_name": self.option_name,
            "extra_price": str(self.extra_price),
            "quantity": self.quantity,
            "is_countable": self.is_countable,
        }


@dataclass(slots=True)
class ResolvedMenuItemSelection:
    menu_item: MenuItem
    size_id: uuid.UUID | None
    size_name: str | None
    base_unit_price: Decimal
    customization_total_price: Decimal
    unit_price: Decimal
    selected_options: list[ResolvedCustomizationOption]

    def selected_options_snapshot(self) -> list[dict[str, object]]:
        return [option.to_snapshot() for option in self.selected_options]


def menu_item_query_with_customizations() -> Select[tuple[MenuItem]]:
    return select(MenuItem).options(
        selectinload(MenuItem.sizes)
        .selectinload(MenuItemSize.customization_groups)
        .selectinload(MenuItemCustomizationGroup.options),
        selectinload(MenuItem.customization_groups).selectinload(
            MenuItemCustomizationGroup.options
        ),
    )


def _get_active_customization_groups(
    menu_item: MenuItem,
    *,
    selected_size: MenuItemSize | None,
) -> list[MenuItemCustomizationGroup]:
    item_level_groups = [
        group
        for group in menu_item.customization_groups
        if group.menu_item_size_id is None and group.is_active
    ]
    size_groups = (
        [group for group in selected_size.customization_groups if group.is_active]
        if selected_size is not None
        else []
    )

    deduped_groups: list[MenuItemCustomizationGroup] = []
    seen_group_ids: set[uuid.UUID] = set()
    for group in [*item_level_groups, *size_groups]:
        if group.id in seen_group_ids:
            continue
        deduped_groups.append(group)
        seen_group_ids.add(group.id)
    return deduped_groups


def fetch_menu_items_for_customized_order(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID,
    menu_item_ids: list[uuid.UUID],
) -> dict[uuid.UUID, MenuItem]:
    if len(set(menu_item_ids)) != len(menu_item_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate menu items are not allowed in the cart",
        )

    menu_items = db.scalars(
        menu_item_query_with_customizations().where(
            MenuItem.restaurant_id == restaurant_id,
            MenuItem.restaurant_location_id == restaurant_location_id,
            MenuItem.id.in_(menu_item_ids),
        )
    ).all()
    found = {menu_item.id: menu_item for menu_item in menu_items}
    if len(found) != len(menu_item_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more menu items were not found for this restaurant",
        )

    unavailable = [menu_item.name for menu_item in found.values() if not menu_item.is_available]
    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unavailable items in cart: {', '.join(sorted(unavailable))}",
        )
    return found


def resolve_menu_item_selection(
    menu_item: MenuItem,
    *,
    menu_item_size_id: uuid.UUID | None,
    selected_options: list[SelectedCustomizationOptionInput],
) -> ResolvedMenuItemSelection:
    selected_size: MenuItemSize | None = None
    if menu_item.has_sizes:
        if menu_item_size_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Select a size for {menu_item.name}.",
            )
        selected_size = next(
            (
                size
                for size in menu_item.sizes
                if size.id == menu_item_size_id and size.is_active
            ),
            None,
        )
        if selected_size is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"The selected size is unavailable for {menu_item.name}.",
            )
    elif menu_item_size_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{menu_item.name} does not support size selection.",
        )

    base_unit_price = (
        _safe_decimal(selected_size.price)
        if selected_size is not None
        else _safe_decimal(menu_item.price)
    )
    active_groups = _get_active_customization_groups(
        menu_item,
        selected_size=selected_size,
    )

    if not menu_item.has_customizations and selected_options:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{menu_item.name} does not support customization choices.",
        )

    active_options_by_id: dict[uuid.UUID, tuple[MenuItemCustomizationGroup, MenuItemCustomizationOption]] = {}
    for group in active_groups:
        for option in group.options:
            if option.is_active:
                active_options_by_id[option.id] = (group, option)

    selected_by_group: dict[uuid.UUID, list[ResolvedCustomizationOption]] = {}
    customization_total = Decimal("0.00")
    seen_option_ids: set[uuid.UUID] = set()

    for selection in selected_options:
        if selection.option_id in seen_option_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate customization choices were selected for {menu_item.name}.",
            )
        seen_option_ids.add(selection.option_id)
        resolved = active_options_by_id.get(selection.option_id)
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"An unavailable customization was selected for {menu_item.name}.",
            )
        group, option = resolved
        quantity = selection.quantity
        if quantity < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Customization quantities must be at least 1 for {menu_item.name}.",
            )
        if not option.is_countable and quantity != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{option.name} cannot use quantities greater than 1.",
            )
        selected_option = ResolvedCustomizationOption(
            group_id=group.id,
            group_title=group.title,
            selection_type=group.selection_type.value,
            option_id=option.id,
            option_name=option.name,
            extra_price=_safe_decimal(option.extra_price),
            quantity=quantity,
            is_countable=option.is_countable,
        )
        selected_by_group.setdefault(group.id, []).append(selected_option)
        customization_total += _quantize(selected_option.extra_price * quantity)

    logger.info(
        "Customization resolve payload menu_item_id=%s menu_item_name=%s selected_size_id=%s active_group_ids=%s selected_option_ids=%s selected_group_ids=%s",
        menu_item.id,
        menu_item.name,
        selected_size.id if selected_size is not None else None,
        [str(group.id) for group in active_groups],
        [str(selection.option_id) for selection in selected_options],
        [str(group_id) for group_id in selected_by_group.keys()],
    )

    for group in active_groups:
        selections = selected_by_group.get(group.id, [])
        selection_count = len(selections)
        logger.info(
            "Customization validation group_id=%s title=%s required=%s min=%s max=%s selection_type=%s selection_count=%s",
            group.id,
            group.title,
            group.is_required,
            group.min_selection,
            group.max_selection,
            group.selection_type.value,
            selection_count,
        )
        if group.selection_type.value == "SINGLE" and selection_count > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{group.title} only allows one selection.",
            )
        if group.is_required and selection_count < max(group.min_selection, 1):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{group.title} requires at least one selection.",
            )
        if selection_count < group.min_selection:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{group.title} requires at least {group.min_selection} selections.",
            )
        if selection_count > group.max_selection:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{group.title} allows at most {group.max_selection} selections.",
            )

    customization_total = _quantize(customization_total)
    unit_price = _quantize(base_unit_price + customization_total)
    flattened_options = [
        option
        for group in active_groups
        for option in selected_by_group.get(group.id, [])
    ]

    return ResolvedMenuItemSelection(
        menu_item=menu_item,
        size_id=selected_size.id if selected_size is not None else None,
        size_name=selected_size.name if selected_size is not None else None,
        base_unit_price=base_unit_price,
        customization_total_price=customization_total,
        unit_price=unit_price,
        selected_options=flattened_options,
    )
