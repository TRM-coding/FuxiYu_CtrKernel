"""冒烟测试种子脚本：创建或重置一个 operator 用户。"""

import os
import secrets
import sys
from importlib import import_module
from pathlib import Path

from sqlalchemy import select
from werkzeug.security import generate_password_hash

_pkg_dir = Path(__file__).resolve().parent
_parent_dir = str(_pkg_dir.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
_package = import_module(_pkg_dir.name)

from FuxiYu_CtrKernel.config import AppConfig  # noqa: E402
from FuxiYu_CtrKernel.extensions import session_scope  # noqa: E402
from FuxiYu_CtrKernel.models.user import User  # noqa: E402

DEFAULT_USERNAME = "smoke_operator"
DEFAULT_EMAIL = "smoke_operator@bjtu.edu.cn"
_console = sys.__stdout__


def _get_password() -> str:
    pw = os.getenv("SEED_OPERATOR_PASSWORD")
    if pw:
        return pw
    import getpass

    try:
        pw = getpass.getpass("operator 密码（留空则随机生成）: ")
    except Exception:
        pw = ""
    if not pw.strip():
        pw = secrets.token_urlsafe(12)
    return pw


def _assert_dev_database() -> None:
    uri = str(getattr(AppConfig, "SQLALCHEMY_DATABASE_URI", ""))
    if uri.startswith("sqlite"):
        return
    if os.getenv("ALLOW_NON_SQLITE") != "1":
        _console.write(
            f"拒绝执行：目标库不是 SQLite（{uri}）。如确认执行，请设置 ALLOW_NON_SQLITE=1\n"
        )
        sys.exit(1)


def main() -> None:
    _package.create_app()
    _assert_dev_database()
    password = _get_password()
    password_hash = generate_password_hash(password)

    with session_scope() as session:
        user = session.scalars(select(User).where(User.username == DEFAULT_USERNAME)).first()
        if user:
            user.password_hash = password_hash
            session.flush()
            created = False
        else:
            user = User(
                username=DEFAULT_USERNAME,
                email=DEFAULT_EMAIL,
                password_hash=password_hash,
                graduation_year="2026",
            )
            session.add(user)
            session.flush()
            created = True
        # RBAC 组绑定：冒烟账号进 operator 组（通配权限点由组持有，不再有单字段）
        from FuxiYu_CtrKernel.repositories import auth_repo
        op_group = auth_repo.get_group("operator", session=session)
        if op_group is not None:
            auth_repo.ensure_user_group(user.id, op_group.id, session=session)

    if created:
        _console.write("[seed] 已创建 operator 用户（operator 组）\n")
    else:
        _console.write(f"[seed] 已重置 {DEFAULT_USERNAME} 密码（operator 组绑定保持）\n")

    _console.write(
        f"\n冒烟测试账号：\n"
        f"  username   {DEFAULT_USERNAME}\n"
        f"  password   {password}\n"
        f"  email      {DEFAULT_EMAIL}\n"
        f"  所属组     operator（通配权限）\n"
    )


if __name__ == "__main__":
    main()
