"""冒烟测试种子脚本：创建/重置一个 operator 用户。

用法：
    python seed.py                                  # 交互输入密码（空则随机生成）
    SEED_OPERATOR_PASSWORD=xxx python seed.py       # 指定密码
    ALLOW_NON_SQLITE=1 python seed.py               # 显式允许在生产库执行（危险）

安全考量：
- 默认拒绝非 SQLite 目标库，防止把已知密码种进生产
- 密码不写死：env > 交互输入 > 随机生成
- 幂等：用户已存在时只重置密码和权限，不重复创建
"""
import os
import secrets
import sys
from importlib import import_module
from pathlib import Path

# 与 run.py 相同：把仓库的父目录放进 sys.path，按目录名导入包
_pkg_dir = Path(__file__).resolve().parent
_parent_dir = str(_pkg_dir.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
_package = import_module(_pkg_dir.name)

from werkzeug.security import generate_password_hash  # noqa: E402

from FuxiYu_CtrKernel.constant import PERMISSION  # noqa: E402
from FuxiYu_CtrKernel.extensions import db  # noqa: E402
from FuxiYu_CtrKernel.models.user import User  # noqa: E402

DEFAULT_USERNAME = "smoke_operator"
DEFAULT_EMAIL = "smoke_operator@bjtu.edu.cn"

# create_app 会把 stdout 重定向进 ctrl.log，这里先留住真实终端
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


def _assert_dev_database(app) -> None:
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if uri.startswith("sqlite"):
        return
    if os.getenv("ALLOW_NON_SQLITE") != "1":
        _console.write(f"拒绝执行：目标库不是 SQLite（{uri}）。防止把已知密码种进生产。\n"
                       f"若确要执行，请显式设置 ALLOW_NON_SQLITE=1\n")
        sys.exit(1)


def main() -> None:
    app = _package.create_app()
    _assert_dev_database(app)
    password = _get_password()

    with app.app_context():
        user = User.query.filter_by(username=DEFAULT_USERNAME).first()
        password_hash = generate_password_hash(password)
        if user:
            user.password_hash = password_hash
            user.permission = PERMISSION.OPERATOR
            db.session.commit()
            _console.write(f"[seed] 已重置 {DEFAULT_USERNAME}（权限提升为 operator）\n")
        else:
            user = User(
                username=DEFAULT_USERNAME,
                email=DEFAULT_EMAIL,
                password_hash=password_hash,
                graduation_year="2026",
                permission=PERMISSION.OPERATOR,
            )
            db.session.add(user)
            db.session.commit()
            _console.write(f"[seed] 已创建 operator 用户\n")

    _console.write(
        f"\n冒烟测试账号：\n"
        f"  username   {DEFAULT_USERNAME}\n"
        f"  password   {password}\n"
        f"  email      {DEFAULT_EMAIL}\n"
        f"  permission operator\n"
        f"\n浏览器打开 https://127.0.0.1:5173 登录即可。\n"
    )


if __name__ == "__main__":
    main()
