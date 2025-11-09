import pytest
from ..services.container_tasks import remove_container, add_collaborator, remove_collaborator
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
        result = remove_container(container_id=container_id)
        
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
# add_collaborator 单元测试
def test_add_collaborator():
    import uuid
    import random
    
    # 1) 创建测试数据：机器、用户、容器
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    
    # 创建机器
    machine = Machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=random.choice(list(MachineTypes)),
        machine_status=random.choice(list(MachineStatus)),
        cpu_core_number=random.randint(1, 16),
        gpu_number=random.randint(0, 4),
        gpu_type=f"GPU_{random.randint(1000, 5000)}",
        memory_size_gb=random.randint(4, 128),
        disk_size_gb=random.randint(100, 2000),
        machine_description="Test machine for add_collaborator"
    )
    db.session.add(machine)
    db.session.commit()
    
    # 创建两个用户：一个作为容器所有者，一个作为要添加的协作者
    owner_username = f"owner_{uuid.uuid4().hex[:8]}"
    collaborator_username = f"collab_{uuid.uuid4().hex[:8]}"
    
    owner_user = User(
        username=owner_username,
        email=f"{owner_username}@test.com",
        password_hash="test_hash",
        graduation_year="2024"
    )
    
    collaborator_user = User(
        username=collaborator_username,
        email=f"{collaborator_username}@test.com", 
        password_hash="test_hash",
        graduation_year="2024"
    )
    
    db.session.add_all([owner_user, collaborator_user])
    db.session.commit()
    
    # 创建容器
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
    
    # 建立所有者绑定（初始绑定）
    owner_binding = UserContainer(
        user_id=owner_user.id,
        container_id=container.id,
        username=owner_username,
        public_key="ssh-rsa AAAAB3NzaC1yc2E...",
        role=ROLE.ADMIN
    )
    db.session.add(owner_binding)
    db.session.commit()
    
    try:
        # 2) 验证初始状态：应该只有所有者绑定
        initial_bindings = UserContainer.query.filter_by(container_id=container.id).all()
        assert len(initial_bindings) == 1, "初始状态下应该只有所有者绑定"
        assert initial_bindings[0].user_id == owner_user.id, "初始绑定应该是所有者"
        
        # 3) 调用 add_collaborator 函数
        result = add_collaborator(
            container_id=container.id,
            user_id=collaborator_user.id,
            role=ROLE.COLLABORATOR
        )
        
        # 4) 验证函数返回结果
        assert result is True, "add_collaborator 应该返回 True"
        
        # 5) 验证数据库状态：现在应该有两个绑定
        updated_bindings = UserContainer.query.filter_by(container_id=container.id).all()
        assert len(updated_bindings) == 2, "添加协作者后应该有两个绑定"
        
        # 找到新添加的协作者绑定
        collaborator_binding = None
        for binding in updated_bindings:
            if binding.user_id == collaborator_user.id:
                collaborator_binding = binding
                break
        
        # 6) 验证协作者绑定的详细信息
        assert collaborator_binding is not None, "应该找到协作者的绑定记录"
        assert collaborator_binding.user_id == collaborator_user.id, "绑定用户ID应该匹配"
        assert collaborator_binding.container_id == container.id, "绑定容器ID应该匹配"
        assert collaborator_binding.username == collaborator_username, "绑定用户名应该匹配"
        assert collaborator_binding.role == ROLE.COLLABORATOR, "绑定角色应该是 COLLABORATOR"
        assert collaborator_binding.public_key is None, "协作者绑定的公钥应该为 None"
        
        # 7) 验证所有者绑定没有被修改
        owner_binding_after = UserContainer.query.filter_by(
            user_id=owner_user.id, 
            container_id=container.id
        ).first()
        assert owner_binding_after is not None, "所有者绑定应该仍然存在"
        assert owner_binding_after.role == ROLE.ADMIN, "所有者角色应该保持 ADMIN"
        assert owner_binding_after.public_key == "ssh-rsa AAAAB3NzaC1yc2E...", "所有者公钥应该保持不变"
        
        print("add_collaborator 测试通过")
        
    finally:
        # 8) 清理测试数据
        UserContainer.query.filter_by(container_id=container.id).delete()
        Container.query.filter_by(id=container.id).delete()
        User.query.filter(User.username.in_([owner_username, collaborator_username])).delete()
        Machine.query.filter_by(id=machine.id).delete()
        db.session.commit()

##################################


##################################
# remove_collaborator 单元测试
def test_remove_collaborator():
    import uuid
    import random
    
    # 1) 创建测试数据：用户、机器、容器和绑定关系
    test_users = []
    test_machine = None
    test_container = None
    
    try:
        # 创建两个测试用户
        for i in range(2):
            user = User(
                username=f"test_user_{uuid.uuid4().hex[:8]}",
                email=f"test{i}@example.com",
                password_hash="test_hash",
                graduation_year="2024"
            )
            db.session.add(user)
            test_users.append(user)
        
        db.session.commit()
        
        # 创建测试机器
        machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
        machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
        
        test_machine = Machine(
            machine_name=machine_name,
            machine_ip=machine_ip,
            machine_type=random.choice(list(MachineTypes)),
            machine_status=random.choice(list(MachineStatus)),
            cpu_core_number=random.randint(1, 16),
            gpu_number=random.randint(0, 4),
            gpu_type=f"GPU_{random.randint(1000, 5000)}",
            memory_size_gb=random.randint(4, 128),
            disk_size_gb=random.randint(100, 2000),
            machine_description="Test machine for remove_collaborator"
        )
        db.session.add(test_machine)
        db.session.commit()
        
        # 创建测试容器
        container_name = f"test_container_{uuid.uuid4().hex[:8]}"
        test_container = Container(
            name=container_name,
            image="ubuntu:latest",
            machine_id=test_machine.id,
            container_status=random.choice(list(ContainerStatus)),
            port=random.randint(8000, 9000)
        )
        db.session.add(test_container)
        db.session.commit()
        
        # 2) 为两个用户都创建容器绑定关系
        user_bindings = []
        for user in test_users:
            user_container = UserContainer(
                user_id=user.id,
                container_id=test_container.id,
                username=user.username,
                public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7...",
                role=ROLE.COLLABORATOR
            )
            db.session.add(user_container)
            user_bindings.append(user_container)
        
        db.session.commit()
        
        # 验证绑定关系已创建
        initial_bindings_count = UserContainer.query.filter_by(container_id=test_container.id).count()
        assert initial_bindings_count == 2, f"初始应该有2个绑定关系，实际有{initial_bindings_count}个"
        
        # 3) 调用 remove_collaborator 移除第一个用户的访问权
        user_to_remove = test_users[0]
        result = remove_collaborator(
            container_id=test_container.id,
            user_id=user_to_remove.id
        )
        
        # 检查函数返回结果
        assert result is True, "remove_collaborator 应该返回 True"
        
        # 4) 验证绑定关系已被删除
        remaining_bindings_count = UserContainer.query.filter_by(container_id=test_container.id).count()
        assert remaining_bindings_count == 1, f"移除一个协作者后应该剩下1个绑定关系，实际有{remaining_bindings_count}个"
        
        # 验证被移除用户的绑定关系不存在
        removed_binding = UserContainer.query.filter_by(
            user_id=user_to_remove.id,
            container_id=test_container.id
        ).first()
        assert removed_binding is None, "被移除用户的绑定关系应该已被删除"
        
        # 验证另一个用户的绑定关系仍然存在
        remaining_binding = UserContainer.query.filter_by(
            user_id=test_users[1].id,
            container_id=test_container.id
        ).first()
        assert remaining_binding is not None, "另一个用户的绑定关系应该仍然存在"
        
        # 5) 测试移除不存在的绑定关系（应该仍然返回True，但数据库不变）
        non_existent_user_id = 99999
        result_nonexistent = remove_collaborator(
            container_id=test_container.id,
            user_id=non_existent_user_id
        )
        
        assert result_nonexistent is True, "移除不存在的绑定关系也应该返回 True"
        
        # 验证绑定关系数量不变
        final_bindings_count = UserContainer.query.filter_by(container_id=test_container.id).count()
        assert final_bindings_count == 1, f"移除不存在的绑定关系后数量应该不变，实际有{final_bindings_count}个"
        
        print("remove_collaborator 测试通过")
        
    finally:
        # 6) 清理测试数据
        if test_container:
            UserContainer.query.filter_by(container_id=test_container.id).delete()
            db.session.delete(test_container)
        
        if test_machine:
            db.session.delete(test_machine)
        
        for user in test_users:
            db.session.delete(user)
        
        db.session.commit()
##################################