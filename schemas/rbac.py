from pydantic import BaseModel, Field

from .common import SuccessMessageResponse


class RbacEntityItem(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None


class RbacGroupItem(BaseModel):
    id: int
    name: str
    description: str | None = None
    entity_codes: list[str] = Field(default_factory=list)
    locked_entity_codes: list[str] = Field(default_factory=list)


class RbacMatrixResponse(BaseModel):
    success: int | bool = 1
    entities: list[RbacEntityItem | dict]
    groups: list[RbacGroupItem | dict]


class UpdateRbacGroupEntitiesRequest(BaseModel):
    entity_codes: list[str] = Field(default_factory=list)


class UpdateRbacGroupEntitiesResponse(SuccessMessageResponse):
    group: RbacGroupItem | dict


class CreateRbacGroupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64)
    description: str | None = None
    entity_codes: list[str] = Field(default_factory=list)


class CreateRbacGroupResponse(SuccessMessageResponse):
    group: RbacGroupItem | dict
