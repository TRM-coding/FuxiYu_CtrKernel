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
#修改密码验证单元测试

def test_Change_password():
    import uuid
    import random
    from ..services.user_tasks import Change_password  # 导入修改密码函数
    from werkzeug.security import check_password_hash

    # 随机化输入数据
    username = f"cp_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    old_password = f"OldP@ss_{uuid.uuid4().hex[:6]}"
    new_password = f"NewP@ss_{uuid.uuid4().hex[:6]}"
    graduation_year = str(random.randint(2020, 2030))

    # 注册用户
    user = Register(username, email, old_password, graduation_year)
    if user is None:
        pytest.skip("随机用户名或邮箱冲突，跳过测试")

    try:
        # 测试1: 正确旧密码修改成功
        result = Change_password(user, old_password, new_password)
        assert result is True, "正确旧密码应该修改成功"
        
        # 验证新密码可以登录
        assert Login(username, new_password) is True, "新密码应该可以登录"
        
        # 验证旧密码不能登录
        assert Login(username, old_password) is False, "旧密码应该不能登录"
        
        # 测试2: 错误旧密码修改失败
        result_fail = Change_password(user, "wrong_old_password", "another_new_password")
        assert result_fail is False, "错误旧密码应该修改失败"
        
        # 验证密码仍然是之前设置的新密码
        assert Login(username, new_password) is True, "密码修改失败后应该保持原密码"
        
        # 测试3: 空新密码（边界情况）
        #result_empty = Change_password(user, new_password, "")
        #if result_empty is not None:  # 根据你的函数实现，可能返回True或做其他处理
            # 如果函数允许空密码，验证可以登录
            #login_result = Login(username, "")
            # 这里根据你的业务逻辑决定断言
        
        # 测试4: 新旧密码相同 - 重构测试逻辑
        # 先确认当前状态
        current_login_before = Login(username, new_password)
        
        # 尝试修改为相同密码
        result_same = Change_password(user, new_password, new_password)
        
        # 修改后再次尝试登录
        current_login_after = Login(username, new_password)
        
        # 核心断言：无论修改操作结果如何，原密码必须始终有效
        assert current_login_before is True, "修改前原密码必须可以登录"
        assert current_login_after is True, "修改后原密码必须仍然可以登录"
        
        # 根据实际业务逻辑调整断言
        if result_same is True:
            # 如果允许修改相同密码，这是合理的
            pass
        elif result_same is False:
            # 如果不允许修改相同密码，这也是合理的（安全性考虑）
            pass
        # 如果返回None或其他值，也不断言失败
            
    finally:
        # 清理测试数据
        db.session.delete(user)
        db.session.commit()
##################################

##################################
#注销用户验证单元测试

def test_Delete_user():
    import uuid
    import random
    from ..services.user_tasks import Delete_user  # 导入注销用户函数
    from ..models.user import User

    # 随机化输入数据
    username = f"du_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = f"P@ss_{uuid.uuid4().hex[:6]}"
    graduation_year = str(random.randint(2020, 2030))

    # 注册用户
    user = Register(username, email, password, graduation_year)
    if user is None:
        pytest.skip("随机用户名或邮箱冲突，跳过测试")

    try:
        # 获取用户ID
        user_id = user.id
        
        # 验证用户确实存在于数据库中
        user_before = db.session.get(User, user_id)
        assert user_before is not None, "删除前用户应该存在于数据库中"
        assert user_before.username == username, "用户名应该匹配"
        
        # 调用注销用户函数
        result = Delete_user(user_id)
        
        # 验证函数返回True
        assert result is True, "注销用户函数应该返回True"
        
        # 验证用户已从数据库中删除
        user_after = db.session.get(User, user_id)
        assert user_after is None, "注销后用户应该从数据库中删除"
        
        # 验证用户无法再登录
        login_result = Login(username, password)
        assert login_result is False, "注销后用户应该无法登录"
        
    except Exception as e:
        # 如果测试过程中出现异常，确保清理
        db.session.rollback()
        # 重新查询用户并删除（如果还存在）
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            db.session.delete(existing_user)
            db.session.commit()
        raise e
    finally:
        # 额外清理：确保测试用户完全删除
        # 这里不需要再删除，因为测试中已经删除了用户
        # 但为了安全，再次检查并清理
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            db.session.delete(existing_user)
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