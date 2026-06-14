from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _empty_to_none(value: Any) -> Any:
    return None if value == "" else value


OptionalInt = Annotated[int | None, BeforeValidator(_empty_to_none)]
OptionalFloat = Annotated[float | None, BeforeValidator(_empty_to_none)]


class ApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def payload(self, *, patch: bool = False) -> dict[str, Any]:
        return self.model_dump(exclude_unset=patch)


class LoginRequest(ApiRequest):
    username: str = ""
    password: str = ""


class PasswordChangeRequest(ApiRequest):
    old_password: str = ""
    new_password: str = ""


class OrderCreateRequest(ApiRequest):
    name: str = ""
    category: str = ""
    brand: str = ""
    catalog_no: str = ""
    amount: OptionalFloat = None
    amount_unit: str = ""
    quantity: OptionalFloat = 1
    price: OptionalFloat = None
    reason: str = ""


class OrderUpdateRequest(ApiRequest):
    status: Literal["已订购", "停用"]


class ArrivalCreateRequest(ApiRequest):
    order_id: int
    entry_date: str = ""
    arrival_quantity: OptionalInt = 1
    separate_items: bool = True
    expiration_date: str = ""
    storage_node_id: OptionalInt = None
    position_in_box: str = ""
    note: str = ""


class ValidationImageUploadRequest(ApiRequest):
    data_url: str
    code: str = "item"
    method: str = "method"
    validation_date: str = ""


class ValidationCreateRequest(ApiRequest):
    catalog_no: str = ""
    validation_date: str = ""
    method: str = ""
    result: str = ""
    description: str = ""
    image_path: str = ""


class StorageTargetRequest(ApiRequest):
    storage_node_id: OptionalInt = None
    position_in_box: str = ""


class InventoryItemCreateRequest(StorageTargetRequest):
    item_type: Literal["sample", "reagent"]
    code: str = ""
    source_code: str = ""
    name: str = ""
    category: str = ""
    brand: str = ""
    catalog_no: str = ""
    amount: OptionalFloat = None
    amount_unit: str = ""
    quantity: OptionalFloat = None
    tube_count: OptionalInt = 1
    separate_items: bool = True
    status: str = ""
    entry_date: str = ""
    expiration_date: str = ""
    validation_status: str = ""
    note: str = ""


class InventoryItemUpdateRequest(StorageTargetRequest):
    code: str | None = None
    source_code: str | None = None
    name: str | None = None
    category: str | None = None
    brand: str | None = None
    catalog_no: str | None = None
    amount: OptionalFloat = None
    amount_unit: str | None = None
    quantity: OptionalFloat = None
    status: str | None = None
    entry_date: str | None = None
    expiration_date: str | None = None
    validation_status: str | None = None
    note: str | None = None
    storage_node_id: OptionalInt = Field(default=None)
    position_in_box: str | None = None


class AliquotCreateRequest(StorageTargetRequest):
    item_type: Literal["sample", "reagent"]
    source_item_id: int
    tube_count: OptionalInt = 1
    quantity: OptionalFloat = None
    amount: OptionalFloat = None
    amount_unit: str = ""
    entry_date: str = ""
    note: str = ""


class MovementCreateRequest(ApiRequest):
    item_type: Literal["sample", "reagent"]
    item_id: int
    to_storage_node_id: OptionalInt = None
    position_in_box: str = ""
    reason: str = ""
    note: str = ""


class CheckoutCreateRequest(ApiRequest):
    item_type: Literal["sample", "reagent"]
    item_id: int
    reason: str = "出库"
    note: str = ""


class StorageNodeCreateRequest(ApiRequest):
    parent_id: OptionalInt = None
    name: str = ""
    node_type: Literal["space"] = "space"
    location_code: str = ""
    rows: OptionalInt = None
    cols: OptionalInt = None
    grid_row: OptionalInt = None
    grid_col: OptionalInt = None
    note: str = ""
    sort_order: OptionalInt = 0


class StorageNodeUpdateRequest(ApiRequest):
    parent_id: OptionalInt = None
    name: str | None = None
    node_type: Literal["space"] | None = None
    location_code: str | None = None
    rows: OptionalInt = None
    cols: OptionalInt = None
    grid_row: OptionalInt = None
    grid_col: OptionalInt = None
    note: str | None = None
    sort_order: OptionalInt = None


class DropdownSettingsRequest(ApiRequest):
    categories: list[str]
    brands: list[str]
    reagent_statuses: list[str]
    validation_statuses: list[str]
    validation_methods: list[str]
    sample_prefixes: list[str]
    sample_names: list[str]
    amount_units: list[str]
    sample_statuses: list[str]


class UserCreateRequest(ApiRequest):
    username: str = ""
    password: str = ""
    display_name: str = ""
    role: Literal["user", "admin"] = "user"
    permissions: dict[str, bool] = Field(default_factory=dict)


class UserUpdateRequest(ApiRequest):
    display_name: str | None = None
    role: Literal["user", "admin"] | None = None
    is_active: bool | None = None
    permissions: dict[str, bool] | None = None
    password: str | None = None


class ExcelImportRequest(ApiRequest):
    scope: Literal["single", "workbook"] = "single"
    table: str = ""
    mode: Literal["append", "upsert"] = "append"
    sheet: str = ""
    data_url: str


class BackupCreateRequest(ApiRequest):
    reason: str = "manual"


class BackupCleanupRequest(ApiRequest):
    days: OptionalInt = 30


class BackupSettingsRequest(ApiRequest):
    enabled: bool = False
    interval_hours: OptionalInt = 24
    retention_days: OptionalInt = 30
    cleanup_on_schedule: bool = True


class BulkExcelParseRequest(ApiRequest):
    sheet: str = ""
    data_url: str


class BulkOperationRequest(ApiRequest):
    operation: Literal["import", "edit", "move", "checkout"] = "import"
    item_type: Literal["sample", "reagent"] = "reagent"
    mode: Literal["insert", "update", "upsert"] = "upsert"
    rows: list[dict[str, Any]] = Field(default_factory=list)
