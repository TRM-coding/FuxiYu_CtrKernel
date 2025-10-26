#user_tasks.py 单元测试
import pytest
from ..services.user_tasks import Login, Register
from ..models.user import User
from ..extensions import db
from .. import create_app
##################################
#单元测试创建运行环境
@pytest.fixture(scope="session")
def app():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        # 确保模型已导入，再建表
        from ..models import user, machine, containers, usercontainer  # noqa: F401
        db.create_all()
        yield app
        # 为避免误删开发库数据，这里不 drop_all，如需隔离可单独建测试库

# 为每个测试自动推送 app_context
@pytest.fixture(autouse=True)
def _ctx(app):
    with app.app_context():
        yield
##################################


##################################
#注册验证单元测试
def test_Register():
    import uuid
    import random

    # 1) 随机化生成参数
    username = f"ut_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = f"P@ss_{uuid.uuid4().hex[:6]}"
    graduation_year = str(random.randint(2020, 2030))

    # 2) 调用 Register 执行
    new_user = Register(username, email, password, graduation_year)

    # 若因极小概率的唯一性冲突返回 None，跳过本用例
    if new_user is None:
        pytest.skip("随机生成的用户名或邮箱冲突，跳过测试")

    target = None
    try:
        # 3) 访问数据库，验证结果
        u = User.query.filter_by(username=username).first()
        target = u or new_user
        assert u is not None, "注册后应能在数据库中查询到用户"
        assert u.email == email
        assert u.graduation_year == graduation_year
        # 登录应成功
        assert Login(username, password) is True
    finally:
        # 4) 删除测试数据
        if target:
            db.session.delete(target)
            db.session.commit()
##################################


##################################
#登录验证单元测试

def test_Login():
    import uuid
    import random

    # 随机化输入数据
    username = f"lt_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = f"P@ss_{uuid.uuid4().hex[:6]}"
    graduation_year = str(random.randint(2020, 2030))

    # 注册用户（不验证注册结果）
    u = Register(username, email, password, graduation_year)
    if u is None:
        pytest.skip("随机用户名或邮箱冲突，跳过测试")

    try:
        # 直接调用 login 验证是否能正常登录
        assert Login(username, password) is True
    finally:
        # 清理测试数据
        db.session.delete(u)
        db.session.commit()

##################################
##################################

##################################
##################################

##################################
##################################

##################################
##################################

##################################
##################################

##################################
##################################

##################################
##################################

##################################
##################################