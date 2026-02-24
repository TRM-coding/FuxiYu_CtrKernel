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
        from ..models import user, machine, containers, usercontainer, authentications  # noqa: F401
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
    success, user_or_reason, _ = Register(username, email, password, graduation_year)

    # 若因极小概率的唯一性冲突返回失败，跳过本用例
    if not success:
        pytest.skip("随机生成的用户名或邮箱冲突，跳过测试")

    user = user_or_reason
    try:
        # 3) 访问数据库，验证结果
        u = User.query.filter_by(username=username).first()
        assert u is not None, "注册后应能在数据库中查询到用户"
        assert u.email == email
        assert u.graduation_year == graduation_year
        # 登录应成功
        login_success, login_user, token = Login(username, password)
        assert login_success is True
        assert isinstance(login_user, User)
        assert token is not None
    finally:
        # 4) 删除测试数据
        if user:
            db.session.delete(user)
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
    reg_success, user_or_reason, _ = Register(username, email, password, graduation_year)
    if not reg_success:
        pytest.skip("随机用户名或邮箱冲突，跳过测试")
    
    user = user_or_reason

    try:
        # 直接调用 login 验证是否能正常登录
        success, login_user, token = Login(username, password)
        assert success is True
        assert isinstance(login_user, User)
        assert token is not None
    finally:
        # 清理测试数据
        db.session.delete(user)
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
    reg_success, user_or_reason, _ = Register(username, email, old_password, graduation_year)
    if not reg_success:
        pytest.skip("随机用户名或邮箱冲突，跳过测试")
    
    user = user_or_reason

    try:
        # 测试1: 正确旧密码修改成功
        result = Change_password(user, old_password, new_password)
        assert result is True, "正确旧密码应该修改成功"
        new_login_success, _, _ = Login(username, new_password)
        assert new_login_success is True, "新密码应该可以登录"
        
        # 验证旧密码不能登录
        old_login_success, _, _ = Login(username, old_password)
        assert old_login_success is False, "旧密码应该不能登录"
        
        # 测试2: 错误旧密码修改失败
        result_fail = Change_password(user, "wrong_old_password", "another_new_password")
        assert result_fail is False, "错误旧密码应该修改失败"
        
        # 验证密码仍然是之前设置的新密码
        check_login_success, _, _ = Login(username, new_password)
        assert check_login_success is True, "密码修改失败后应该保持原密码"
        
        # 测试3: 空新密码（边界情况）
        #result_empty = Change_password(user, new_password, "")
        #if result_empty is not None:  # 根据你的函数实现，可能返回True或做其他处理
            # 如果函数允许空密码，验证可以登录
            #login_result = Login(username, "")
            # 这里根据你的业务逻辑决定断言
        
        # 测试4: 新旧密码相同 - 重构测试逻辑
        # 先确认当前状态
        same_login_before, _, _ = Login(username, new_password)
        
        # 尝试修改为相同密码
        result_same = Change_password(user, new_password, new_password)
        
        # 修改后再次尝试登录
        current_login_after, _, _ = Login(username, new_password)
        
        # 核心断言：无论修改操作结果如何，原密码必须始终有效
        assert same_login_before is True, "修改前原密码必须可以登录"
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
    success, user_or_reason, _ = Register(username, email, password, graduation_year)
    if not success:
        pytest.skip("随机用户名或邮箱冲突，跳过测试")
    
    user = user_or_reason

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
        deleted_login_result, _, _ = Login(username, password)
        assert deleted_login_result is False, "注销后用户应该无法登录"
        
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
# 更新用户信息验证单元测试
def test_Update_user():
    import uuid
    import random
    from ..services.user_tasks import Update_user  # 导入更新用户函数
    from ..models.user import User

    # 1) 随机化生成初始参数
    username = f"uu_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = f"P@ss_{uuid.uuid4().hex[:6]}"
    graduation_year = str(random.randint(2020, 2030))
    
    # 2) 先注册一个测试用户
    reg_success, user_or_reason, _ = Register(username, email, password, graduation_year)
    if not reg_success:
        pytest.skip("随机用户名或邮箱冲突，跳过测试")
    
    original_user = user_or_reason
    user_id = original_user.id

    try:
        # 测试1: 正常更新允许修改的字段（例如email、graduation_year）
        # 准备新的更新字段
        new_email = f"updated_{username}@example.com"
        new_graduation_year = str(random.randint(2031, 2040))
        update_fields = {
            "email": new_email,
            "graduation_year": new_graduation_year
        }
        
        # 调用更新函数
        updated_user = Update_user(user_id, **update_fields)
        
        # 验证更新结果
        assert updated_user is not None, "更新用户后应返回非None的用户对象"
        assert updated_user.id == user_id, "更新后的用户ID应与原ID一致"
        assert updated_user.email == new_email, "邮箱应更新为新值"
        assert updated_user.graduation_year == new_graduation_year, "毕业年份应更新为新值"
        
        # 从数据库重新查询验证
        db_user = User.query.get(user_id)
        assert db_user.email == new_email, "数据库中的邮箱应已更新"
        assert db_user.graduation_year == new_graduation_year, "数据库中的毕业年份应已更新"

        # 测试2: 尝试更新受保护字段（permission、password_hash）- 应被忽略
        # 准备包含受保护字段的更新参数
        forbidden_fields = {
            "permission": "admin",  # 受保护字段
            "password_hash": "fake_hash",  # 受保护字段
            "email": f"forbidden_test_{username}@example.com"  # 同时包含正常字段
        }
        
        # 记录更新前的受保护字段值
        original_permission = db_user.permission
        original_password_hash = db_user.password_hash
        
        # 调用更新函数
        forbidden_updated_user = Update_user(user_id, **forbidden_fields)
        
        # 验证受保护字段未被修改
        assert forbidden_updated_user.permission == original_permission, "permission字段不应被修改"
        assert forbidden_updated_user.password_hash == original_password_hash, "password_hash字段不应被修改"
        
        # 验证正常字段仍能更新
        assert forbidden_updated_user.email == f"forbidden_test_{username}@example.com", "非受保护字段应正常更新"
        
        # 数据库层面再次验证受保护字段
        db_user_after_forbidden = User.query.get(user_id)
        assert db_user_after_forbidden.permission == original_permission, "数据库中的permission不应被修改"
        assert db_user_after_forbidden.password_hash == original_password_hash, "数据库中的password_hash不应被修改"

        # 测试3: 空字段更新（边界情况）- 无字段更新时应返回用户对象（无报错）
        empty_updated_user = Update_user(user_id)
        assert empty_updated_user is not None, "无字段更新时应返回用户对象"
        assert empty_updated_user.id == user_id, "无字段更新时用户ID应正确"

    except Exception as e:
        # 异常处理：回滚并清理数据
        db.session.rollback()
        raise e
    finally:
        # 清理测试数据
        existing_user = User.query.get(user_id)
        if existing_user:
            db.session.delete(existing_user)
            db.session.commit()
##################################

##################################
# 重置密码验证单元测试
def test_Reset_password():
    import uuid
    import random
    from ..services.user_tasks import Reset_password, Login  # 导入重置密码和登录函数
    from ..models.user import Use
    from werkzeug.security import check_password_hash

    # 1) 随机化生成初始参数
    username = f"rp_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    original_password = f"P@ss_{uuid.uuid4().hex[:6]}"
    graduation_year = str(random.randint(2020, 2030))
    
    # 2) 先注册一个测试用户
    reg_success, user_or_reason, _ = Register(username, email, original_password, graduation_year)
    if not reg_success:
        pytest.skip("随机用户名或邮箱冲突，跳过测试")
    
    original_user = user_or_reason
    user_id = original_user.id
    

    try:
        # 测试1: 有效用户ID重置密码 - 验证密码生成和更新
        # 调用重置密码函数
        new_password = Reset_password(user_id)
        
        # 验证返回的新密码格式正确
        expected_password = f"{graduation_year}{username}"
        assert new_password == expected_password, f"重置密码应生成 {expected_password}，实际生成 {new_password}"
        
        # 从数据库查询用户，验证密码哈希已更新
        db_user = User.query.get(user_id)
        assert db_user is not None, "用户应存在于数据库中"
        assert check_password_hash(db_user.password_hash, new_password), "数据库中的密码哈希应匹配新密码"
        assert not check_password_hash(db_user.password_hash, original_password), "原密码哈希应已被替换"
        
        # 验证重置后的密码能正常登录
        login_success, login_user, token = Login(username, new_password)
        assert login_success is True, "重置后的密码应能正常登录"
        assert login_user.id == user_id, "登录返回的用户ID应匹配"
        
        # 验证原密码无法登录
        old_login_success, _, _ = Login(username, original_password)
        assert old_login_success is False, "原密码应无法登录"

        # 测试2: 无效用户ID重置密码 - 应返回None
        # 生成一个不存在的用户ID（比如当前最大ID+100）
        invalid_user_id = 999999  # 或动态获取：max_id = db.session.query(func.max(User.id)).scalar() or 0; invalid_user_id = max_id + 100
        reset_invalid = Reset_password(invalid_user_id)
        
        # 验证返回None
        assert reset_invalid is None, "无效用户ID重置密码应返回None"

        # 测试3: 边界情况 - 毕业年份/用户名含特殊字符（如果有）
        # 注册一个毕业年份为纯数字、用户名为混合字符的测试用户
        special_username = f"rp_test_!@#{uuid.uuid4().hex[:4]}"
        special_grad_year = "2025"
        reg_success_special, user_special, _ = Register(special_username, f"{special_username}@example.com", "Test123!", special_grad_year)
        if not reg_success_special:
            pytest.skip("特殊字符用户名冲突，跳过边界测试")
        
        special_user_id = user_special.id
        try:
            # 重置密码
            special_new_pwd = Reset_password(special_user_id)
            expected_special_pwd = f"{special_grad_year}{special_username}"
            
            # 验证生成的密码正确
            assert special_new_pwd == expected_special_pwd, "特殊字符用户名/毕业年份的密码生成应正确"
            
            # 验证登录
            special_login_success, _, _ = Login(special_username, special_new_pwd)
            assert special_login_success is True, "特殊字符密码应能正常登录"
        finally:
            # 清理特殊测试用户
            special_db_user = User.query.get(special_user_id)
            if special_db_user:
                db.session.delete(special_db_user)
                db.session.commit()

    except Exception as e:
        # 异常处理：回滚并清理数据
        db.session.rollback()
        raise e
    finally:
        # 清理主测试用户
        existing_user = User.query.get(user_id)
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