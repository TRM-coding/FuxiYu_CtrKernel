import pytest
from ..services.container_tasks import Create_container, remove_container
from ..models.user import User
from ..models.machine import Machine, MachineTypes, MachineStatus, ROLE
from ..models.containers import Container, ContainerStatus
from ..models.usercontainer import UserContainer
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
#删除容器单元测试
def test_remove_container():
    import uuid
    import random
    
    # 1) 准备测试数据：创建机器、用户和容器
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    
    # 创建测试机器
    machine = Machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=random.choice(list(MachineTypes)), 
        machine_status=random.choice(list(MachineStatus)),
        cpu_core_number=4,
        memory_size_gb=16,
        disk_size_gb=100
    )
    db.session.add(machine)
    db.session.commit()
    
    # 创建测试用户
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@test.com",
        password_hash="test_hash",
        graduation_year="2024"
    )
    db.session.add(user)
    db.session.commit()
    
    # 创建测试容器
    container_name = f"test_container_{uuid.uuid4().hex[:8]}"
    container = Container(
        name=container_name,
        image="ubuntu:latest",
        machine_id=machine.id,
        container_status=random.choice(list(ContainerStatus)),
        port=random.randint(8000, 9000)
    )
    db.session.add(container)
    db.session.commit()
    
    # 创建用户-容器绑定关系
    user_container = UserContainer(
        user_id=user.id,
        container_id=container.id,
        username=user.username,
        public_key="test_public_key",
        role=ROLE.ADMIN
    )
    db.session.add(user_container)
    db.session.commit()
    
    container_id = str(container.id)  # 转换为字符串以匹配函数签名
    
    try:
        # 2) 验证测试数据已正确创建
        container_count_before = Container.query.count()
        user_container_count_before = UserContainer.query.count()
        
        assert container_count_before > 0, "测试前应该有容器存在"
        assert user_container_count_before > 0, "测试前应该有用户容器绑定存在"
        
        # 验证特定容器和绑定存在
        test_container = Container.query.filter_by(id=container.id).first()
        assert test_container is not None, "测试容器应该存在"
        
        test_binding = UserContainer.query.filter_by(container_id=container.id).first()
        assert test_binding is not None, "测试绑定应该存在"
        
        # 3) 调用被测试函数
        result = remove_container(machine_ip=machine_ip, container_id=container_id)
        
        # 4) 验证函数返回结果
        assert result is True, "remove_container 应该返回 True"
        
        # 5) 验证数据库状态
        # 检查容器是否被删除
        deleted_container = Container.query.filter_by(id=container.id).first()
        assert deleted_container is None, "容器应该已被删除"
        
        # 检查绑定关系是否被删除
        deleted_binding = UserContainer.query.filter_by(container_id=container.id).first()
        assert deleted_binding is None, "用户容器绑定应该已被删除"
        
        # 验证计数减少
        container_count_after = Container.query.count()
        user_container_count_after = UserContainer.query.count()
        
        assert container_count_after == container_count_before - 1, f"容器数量应该减少1，实际从 {container_count_before} 变为 {container_count_after}"
        assert user_container_count_after == user_container_count_before - 1, f"绑定数量应该减少1，实际从 {user_container_count_before} 变为 {user_container_count_after}"
        
        print("remove_container 测试通过")
        
    except Exception as e:
        db.session.rollback()
        raise e
        
    finally:
        # 6) 使用清理所有测试数据
        # 清理用户容器绑定
        test_bindings = UserContainer.query.filter(UserContainer.username.like("test_user_%")).all()
        for binding in test_bindings:
            db.session.delete(binding)
        
        # 清理容器
        test_containers = Container.query.filter(Container.name.like("test_container_%")).all()
        for container in test_containers:
            db.session.delete(container)
        
        # 清理用户
        test_users = User.query.filter(User.username.like("test_user_%")).all()
        for user in test_users:
            db.session.delete(user)
        
        # 清理机器
        test_machines = Machine.query.filter(Machine.machine_name.like("test_machine_%")).all()
        for machine in test_machines:
            db.session.delete(machine)
        
        db.session.commit()
##################################

##################################