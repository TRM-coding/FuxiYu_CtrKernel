from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import PageRequest, SuccessMessageResponse


PermissionValue = Literal["user", "operator"]


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    graduation_year: int | None = None
    registration_code: str | None = None


class RegisterResponse(SuccessMessageResponse):
    user_id: int
    username: str
    email: str


class RequestRegisterCodeRequest(BaseModel):
    email: str


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False


class LoginResponse(SuccessMessageResponse):
    user_id: int
    username: str
    email: str
    permission: PermissionValue | str


class UserIdRequest(BaseModel):
    user_id: int = Field(..., ge=1)


class UserBriefItem(BaseModel):
    user_id: int
    username: str
    email: str
    graduation_year: int | None = None
    containers: list[int] = Field(default_factory=list)
    amount_of_container: int = 0
    amount_of_functional_container: int = 0
    amount_of_managed_container: int = 0
    amount_of_long_term_container: int = 0


class UserDetailInfo(UserBriefItem):
    permission: PermissionValue | str | None = None


class UserDetailResponse(BaseModel):
    success: int | bool = 1
    user_info: UserDetailInfo | dict[str, Any]


class ListUserBriefRequest(PageRequest):
    page_number: int = Field(default=1, ge=1)


class ListUserBriefResponse(BaseModel):
    success: int | bool = 1
    users: list[UserBriefItem | dict[str, Any]]


class ChangePasswordRequest(UserIdRequest):
    old_password: str
    new_password: str


class DeleteUserResponse(SuccessMessageResponse):
    wild_containers: list[dict[str, Any]] | None = None


class UpdateUserFields(BaseModel):
    username: str | None = None
    email: str | None = None
    graduation_year: int | None = None


class UpdateUserRequest(UserIdRequest):
    fields: UpdateUserFields = Field(default_factory=UpdateUserFields)


class UpdateUserResponse(SuccessMessageResponse):
    user: str | dict[str, Any] | None = None


class ResetPasswordResponse(SuccessMessageResponse):
    new_password: str
