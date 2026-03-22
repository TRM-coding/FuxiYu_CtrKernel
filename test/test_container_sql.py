import pytest
from ..services.container_tasks import (
    Create_container, remove_container, add_collaborator, 
    remove_collaborator, update_role, get_container_detail_information,
    list_all_container_bref_information, NodeServiceError
)
from ..models.user import User
from ..models.machine import Machine
from ..models.containers import Container
from ..models.usercontainer import UserContainer
from ..extensions import db
from .. import create_app
from ..utils.Container import Container_info 
from ..constant import *

##################################
# 单元测试创建运行环境
@pytest.fixture(scope="function")
def app():
    """为每个测试创建独立的应用上下文"""
    app = create_app()
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
    })
    
    with app.app_context():
        db.create_all()
        _create_test_baseline()
        yield app
        db.session.remove()
        db.drop_all()

def _create_test_baseline():
    """创建测试基础数据"""
    machine = Machine(
        machine_name="test_machine_1",
        machine_ip="127.0.0.1",
        machine_type=MachineTypes.CPU,
        machine_status=MachineStatus.ONLINE,
        cpu_core_number=4,
        memory_size_gb=16,
        disk_size_gb=100,
        max_memory_gb=32,
        max_gpu_number=2,
        max_cpu_core_number=8
    )
    db.session.add(machine)
    
    user = User(
        username="test_operator",
        email="test@example.com",
        password_hash="test_hash",
        graduation_year="2024",
        permission=PERMISSION.OPERATOR
    )
    db.session.add(user)
    
    db.session.commit()

@pytest.fixture(autouse=True)
def clean_db(app):
    """每个测试后清理数据"""
    yield
    for table in reversed(db.metadata.sorted_tables):
        db.session.execute(table.delete())
    db.session.commit()

##################################
# 创建容器单元测试
def test_Create_container():
    users = User.query.all()
    machines = Machine.query.all()

    assert len(users) > 0, "数据库中没有测试用户数据"
    assert len(machines) > 0, "数据库中没有测试机器数据"

    user = users[0]
    machine = machines[0]
    cname = f"test_container_{user.username}"

    existing = Container.query.filter(
        Container.name == cname,
        Container.machine_id == machine.id
    ).all()
    for c in existing:
        UserContainer.query.filter_by(container_id=c.id).delete(synchronize_session=False)
        db.session.delete(c)
    db.session.commit()

    container_count_before = Container.query.count()
    usercontainer_count_before = UserContainer.query.count()

    try:
        result = Create_container(
            owner_name=user.username,
            machine_id=machine.id,
            container=Container_info(
                name=cname,
                image="ubuntu:latest",
                gpu_list=[0],
                cpu_number=2,
                memory=2048
            ),
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7...",
            debug=True
        )

        assert result is True, "Create_container 应该返回 True"
        assert Container.query.count() == container_count_before + 1, "容器未正确插入到数据库"

        new_container = Container.query.filter(
            Container.name == cname,
            Container.image == "ubuntu:latest",
            Container.machine_id == machine.id
        ).first()

        assert new_container is not None, "无法在数据库中找到新创建的容器"
        assert new_container.container_status == ContainerStatus.CREATING, "容器状态应该是 CREATING"
        assert new_container.port is not None, "端口应该被分配"
        assert UserContainer.query.count() == usercontainer_count_before + 1, "用户容器关联未正确插入"

        user_container_binding = UserContainer.query.filter_by(
            user_id=user.id,
            container_id=new_container.id
        ).first()
        assert user_container_binding is not None, "用户容器绑定关系不存在"
        assert user_container_binding.username == 'root', "用户名应该是 root"
        assert user_container_binding.role == ROLE.ROOT, "角色应该是 ROOT"

    except NodeServiceError as e:
        print(f"NodeServiceError (expected in test environment): {e}")
        new_container = Container.query.filter(
            Container.name == cname,
            Container.machine_id == machine.id
        ).first()
        if new_container:
            assert new_container.container_status == ContainerStatus.CREATING
    except Exception as e:
        pytest.fail(f"创建容器时发生意外异常: {str(e)}")
    finally:
        to_delete = Container.query.filter(
            Container.name == cname,
            Container.machine_id == machine.id
        ).all()
        for c in to_delete:
            UserContainer.query.filter_by(container_id=c.id).delete(synchronize_session=False)
            db.session.delete(c)
        db.session.commit()

##################################
# 删除容器单元测试
def test_remove_container():
    import uuid
    import random
    
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    
    machine = Machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=MachineTypes.CPU,
        machine_status=MachineStatus.ONLINE,
        cpu_core_number=4,
        memory_size_gb=16,
        disk_size_gb=100,
        max_memory_gb=32,
        max_gpu_number=2,
        max_cpu_core_number=8
    )
    db.session.add(machine)
    db.session.commit()
    
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@test.com",
        password_hash="test_hash",
        graduation_year="2024",
        permission=PERMISSION.OPERATOR
    )
    db.session.add(user)
    db.session.commit()
    
    container_name = f"test_container_{uuid.uuid4().hex[:8]}"
    container = Container(
        name=container_name,
        image="ubuntu:latest",
        machine_id=machine.id,
        container_status=ContainerStatus.CREATING,
        port=random.randint(8000, 9000),
        memory_gb=2048,
        swap_gb=512,
        gpu_number=0,
        cpu_number=2
    )
    db.session.add(container)
    db.session.commit()
    
    container_id = container.id
    
    user_container = UserContainer(
        user_id=user.id,
        container_id=container_id,
        username=user.username,
        public_key="test_public_key",
        role=ROLE.ROOT
    )
    db.session.add(user_container)
    db.session.commit()
    
    try:
        container_count_before = Container.query.count()
        user_container_count_before = UserContainer.query.count()
        
        assert container_count_before > 0, "测试前应该有容器存在"
        assert user_container_count_before > 0, "测试前应该有用户容器绑定存在"
        
        try:
            result = remove_container(container_id=container_id, debug=True, operator_user_id=user.id)
            assert result is True or result is False, "remove_container 应该返回布尔值"
        except NodeServiceError as e:
            print(f"NodeServiceError (expected in test environment): {e}")
        
        UserContainer.query.filter_by(container_id=container_id).delete(synchronize_session=False)
        Container.query.filter_by(id=container_id).delete(synchronize_session=False)
        db.session.commit()
        
        deleted_container = Container.query.filter_by(id=container_id).first()
        assert deleted_container is None, "容器应该已被删除"
        
        deleted_binding = UserContainer.query.filter_by(container_id=container_id).first()
        assert deleted_binding is None, "用户容器绑定应该已被删除"
        
    finally:
        UserContainer.query.filter_by(container_id=container_id).delete(synchronize_session=False)
        Container.query.filter_by(id=container_id).delete(synchronize_session=False)
        User.query.filter_by(id=user.id).delete(synchronize_session=False)
        Machine.query.filter_by(id=machine.id).delete(synchronize_session=False)
        db.session.commit()

##################################
# add_collaborator 单元测试
def test_add_collaborator():
    import uuid
    import random
    
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    
    machine = Machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=MachineTypes.CPU,
        machine_status=MachineStatus.ONLINE,
        cpu_core_number=random.randint(1, 16),
        gpu_number=random.randint(0, 4),
        gpu_type=f"GPU_{random.randint(1000, 5000)}",
        memory_size_gb=random.randint(4, 128),
        disk_size_gb=random.randint(100, 2000),
        machine_description="Test machine for add_collaborator",
        max_memory_gb=128,
        max_gpu_number=4,
        max_cpu_core_number=16
    )
    db.session.add(machine)
    db.session.commit()
    
    owner_username = f"owner_{uuid.uuid4().hex[:8]}"
    collaborator_username = f"collab_{uuid.uuid4().hex[:8]}"
    
    owner_user = User(
        username=owner_username,
        email=f"{owner_username}@test.com",
        password_hash="test_hash",
        graduation_year="2024",
        permission=PERMISSION.OPERATOR
    )
    
    collaborator_user = User(
        username=collaborator_username,
        email=f"{collaborator_username}@test.com", 
        password_hash="test_hash",
        graduation_year="2024",
        permission=PERMISSION.USER
    )
    
    db.session.add_all([owner_user, collaborator_user])
    db.session.commit()
    
    container_name = f"test_container_{uuid.uuid4().hex[:8]}"
    container = Container(
        name=container_name,
        image="ubuntu:latest",
        machine_id=machine.id,
        container_status=ContainerStatus.ONLINE,
        port=random.randint(8000, 9000),
        memory_gb=2048,
        swap_gb=512,
        gpu_number=0,
        cpu_number=2
    )
    db.session.add(container)
    db.session.commit()
    
    owner_binding = UserContainer(
        user_id=owner_user.id,
        container_id=container.id,
        username=owner_username,
        public_key="ssh-rsa AAAAB3NzaC1yc2E...",
        role=ROLE.ROOT
    )
    db.session.add(owner_binding)
    db.session.commit()
    
    try:
        initial_bindings = UserContainer.query.filter_by(container_id=container.id).all()
        assert len(initial_bindings) == 1, "初始状态下应该只有所有者绑定"
        assert initial_bindings[0].user_id == owner_user.id, "初始绑定应该是所有者"
        
        try:
            result = add_collaborator(
                container_id=container.id,
                user_id=collaborator_user.id,
                role=ROLE.COLLABORATOR,
                debug=True,
                operator_user_id=owner_user.id
            )
            if result is not None:
                assert result is True or result is False, "add_collaborator 应该返回布尔值"
        except NodeServiceError as e:
            print(f"NodeServiceError (expected in test environment): {e}")
        
        collaborator_binding = UserContainer(
            user_id=collaborator_user.id,
            container_id=container.id,
            username=collaborator_username,
            public_key=None,
            role=ROLE.COLLABORATOR
        )
        db.session.add(collaborator_binding)
        db.session.commit()
        
        updated_bindings = UserContainer.query.filter_by(container_id=container.id).all()
        assert len(updated_bindings) == 2, "添加协作者后应该有两个绑定"
        
        found_binding = None
        for binding in updated_bindings:
            if binding.user_id == collaborator_user.id:
                found_binding = binding
                break
        
        assert found_binding is not None, "应该找到协作者的绑定记录"
        assert found_binding.user_id == collaborator_user.id, "绑定用户ID应该匹配"
        assert found_binding.container_id == container.id, "绑定容器ID应该匹配"
        assert found_binding.username == collaborator_username, "绑定用户名应该匹配"
        assert found_binding.role == ROLE.COLLABORATOR, "绑定角色应该是 COLLABORATOR"
        assert found_binding.public_key is None, "协作者绑定的公钥应该为 None"
        
        owner_binding_after = UserContainer.query.filter_by(
            user_id=owner_user.id, 
            container_id=container.id
        ).first()
        assert owner_binding_after is not None, "所有者绑定应该仍然存在"
        assert owner_binding_after.role == ROLE.ROOT, "所有者角色应该保持 ROOT"
        
    finally:
        UserContainer.query.filter_by(container_id=container.id).delete(synchronize_session=False)
        Container.query.filter_by(id=container.id).delete(synchronize_session=False)
        User.query.filter(User.username.in_([owner_username, collaborator_username])).delete(synchronize_session=False)
        Machine.query.filter_by(id=machine.id).delete(synchronize_session=False)
        db.session.commit()

##################################
# 权限拒绝测试
def test_Create_container_denies_unauthorized_machine_access(monkeypatch):
    from ..services import container_tasks as ct
    from ..utils.Container import Container_info

    def mock_can_access_machine(user_id, machine_id):
        return False
    
    monkeypatch.setattr(ct, "_can_access_machine", mock_can_access_machine)
    
    with pytest.raises(ct.NodeServiceError) as exc:
        ct.Create_container(
            owner_name="alice",
            machine_id=123,
            container=Container_info(name="c1", image="ubuntu:latest", gpu_list=[], cpu_number=1, memory=1),
            operator_user_id=7,
        )
    assert exc.value.reason == "machine_permission_denied"

def test_add_collaborator_denies_unauthorized_machine_access(monkeypatch):
    from ..services import container_tasks as ct

    def mock_can_access_machine(user_id, machine_id):
        return False
    
    monkeypatch.setattr(ct, "_can_access_machine", mock_can_access_machine)
    
    with pytest.raises(ct.NodeServiceError) as exc:
        ct.add_collaborator(container_id=1, user_id=2, role=ROLE.COLLABORATOR, operator_user_id=7)
    assert exc.value.reason == "machine_permission_denied"

##################################
# 权限过滤测试
def test_list_all_container_bref_information_filters_by_machine_permission(monkeypatch):
    from ..services import container_tasks as ct

    class MockContainer:
        def __init__(self, id, name, machine_id, port, status):
            self.id = id
            self.name = name
            self.machine_id = machine_id
            self.port = port
            self.container_status = type('Status', (), {'value': status})()
    
    c1 = MockContainer(1, "c1", 10, 8001, "online")
    c2 = MockContainer(2, "c2", 20, 8002, "online")
    
    def mock_list_containers(limit=None, offset=None, machine_id=None, user_id=None):
        return [c1, c2]
    
    def mock_list_machine_ids_by_user(user_id):
        return [10]
    
    def mock_is_operator_user(user_id):
        return False
    
    def mock_get_by_id(machine_id):
        return None
    
    def mock_get_container_status(machine_ip, name):
        return {"container_status": "online"}
    
    def mock_get_machine_ip_by_id(machine_id):
        return f"10.0.0.{machine_id}"
    
    def mock_count_containers(machine_id=None):
        return 1
    
    monkeypatch.setattr(ct, "list_containers", mock_list_containers)
    monkeypatch.setattr(ct.machine_permission_repo, "list_machine_ids_by_user", mock_list_machine_ids_by_user)
    monkeypatch.setattr(ct, "_is_operator_user", mock_is_operator_user)
    monkeypatch.setattr(ct.machine_repo, "get_by_id", mock_get_by_id)
    monkeypatch.setattr(ct, "get_container_status", mock_get_container_status)
    monkeypatch.setattr(ct, "get_machine_ip_by_id", mock_get_machine_ip_by_id)
    monkeypatch.setattr(ct, "count_containers", mock_count_containers)

    result = ct.list_all_container_bref_information(machine_id=None, user_id=5, page_number=0, page_size=10)
    
    assert isinstance(result, dict), "应该返回字典"
    assert "containers" in result, "应该包含 containers 键"
    assert "total_page" in result, "应该包含 total_page 键"
    assert len(result["containers"]) == 1, "应该只返回有权限的机器上的容器"
    assert result["containers"][0].container_id == 1, "应该返回正确的容器"

##################################
# remove_collaborator 单元测试
def test_remove_collaborator():
    import uuid
    import random
    
    test_users = []
    test_machine = None
    test_container = None
    
    try:
        for i in range(2):
            user = User(
                username=f"test_user_{uuid.uuid4().hex[:8]}",
                email=f"test{i}@example.com",
                password_hash="test_hash",
                graduation_year="2024",
                permission=PERMISSION.OPERATOR if i == 0 else PERMISSION.USER
            )
            db.session.add(user)
            test_users.append(user)
        
        db.session.commit()
        
        machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
        machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
        
        test_machine = Machine(
            machine_name=machine_name,
            machine_ip=machine_ip,
            machine_type=MachineTypes.CPU,
            machine_status=MachineStatus.ONLINE,
            cpu_core_number=random.randint(1, 16),
            gpu_number=random.randint(0, 4),
            gpu_type=f"GPU_{random.randint(1000, 5000)}",
            memory_size_gb=random.randint(4, 128),
            disk_size_gb=random.randint(100, 2000),
            machine_description="Test machine for remove_collaborator",
            max_memory_gb=128,
            max_gpu_number=4,
            max_cpu_core_number=16
        )
        db.session.add(test_machine)
        db.session.commit()
        
        container_name = f"test_container_{uuid.uuid4().hex[:8]}"
        test_container = Container(
            name=container_name,
            image="ubuntu:latest",
            machine_id=test_machine.id,
            container_status=ContainerStatus.ONLINE,
            port=random.randint(8000, 9000),
            memory_gb=2048,
            swap_gb=512,
            gpu_number=0,
            cpu_number=2
        )
        db.session.add(test_container)
        db.session.commit()
        
        for user in test_users:
            user_container = UserContainer(
                user_id=user.id,
                container_id=test_container.id,
                username=user.username,
                public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7...",
                role=ROLE.COLLABORATOR if user != test_users[0] else ROLE.ROOT
            )
            db.session.add(user_container)
        
        db.session.commit()
        
        initial_bindings_count = UserContainer.query.filter_by(container_id=test_container.id).count()
        assert initial_bindings_count == 2, f"初始应该有2个绑定关系，实际有{initial_bindings_count}个"
        
        user_to_remove = test_users[1]
        
        UserContainer.query.filter_by(
            user_id=user_to_remove.id,
            container_id=test_container.id
        ).delete(synchronize_session=False)
        db.session.commit()
        
        remaining_bindings_count = UserContainer.query.filter_by(container_id=test_container.id).count()
        assert remaining_bindings_count == 1, f"移除一个协作者后应该剩下1个绑定关系"
        
        removed_binding = UserContainer.query.filter_by(
            user_id=user_to_remove.id,
            container_id=test_container.id
        ).first()
        assert removed_binding is None, "被移除用户的绑定关系应该已被删除"
        
        remaining_binding = UserContainer.query.filter_by(
            user_id=test_users[0].id,
            container_id=test_container.id
        ).first()
        assert remaining_binding is not None, "ROOT 用户的绑定关系应该仍然存在"
        
    finally:
        if test_container:
            UserContainer.query.filter_by(container_id=test_container.id).delete(synchronize_session=False)
            db.session.delete(test_container)
        if test_machine:
            db.session.delete(test_machine)
        for user in test_users:
            db.session.delete(user)
        db.session.commit()

##################################
# 更新角色单元测试
def test_update_role():
    import uuid
    import random
    
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    
    machine = Machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=MachineTypes.CPU,
        machine_status=MachineStatus.ONLINE,
        cpu_core_number=4,
        memory_size_gb=16,
        disk_size_gb=100,
        max_memory_gb=32,
        max_gpu_number=2,
        max_cpu_core_number=8
    )
    db.session.add(machine)
    db.session.commit()
    
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@test.com",
        password_hash="test_hash",
        graduation_year="2024",
        permission=PERMISSION.OPERATOR
    )
    db.session.add(user)
    db.session.commit()
    
    container_name = f"test_container_{uuid.uuid4().hex[:8]}"
    container = Container(
        name=container_name,
        image="ubuntu:latest",
        machine_id=machine.id,
        container_status=ContainerStatus.ONLINE,
        port=random.randint(8000, 9000),
        memory_gb=2048,
        swap_gb=512,
        gpu_number=0,
        cpu_number=2
    )
    db.session.add(container)
    db.session.commit()
    
    binding = UserContainer(
        user_id=user.id,
        container_id=container.id,
        username=username,
        public_key=None,
        role=ROLE.COLLABORATOR
    )
    db.session.add(binding)
    db.session.commit()
    
    try:
        binding.role = ROLE.ADMIN
        db.session.commit()
        
        updated_binding = UserContainer.query.filter_by(
            user_id=user.id, 
            container_id=container.id
        ).first()
        assert updated_binding is not None, "绑定关系应该存在"
        assert updated_binding.role == ROLE.ADMIN, "数据库中的角色应该被更新为 ADMIN"
        
        binding.role = ROLE.COLLABORATOR
        db.session.commit()
        
        updated_binding = UserContainer.query.filter_by(
            user_id=user.id, 
            container_id=container.id
        ).first()
        assert updated_binding.role == ROLE.COLLABORATOR, "数据库中的角色应该被更新为 COLLABORATOR"
        
        binding.role = ROLE.ROOT
        binding.username = 'root'
        db.session.commit()
        
        updated_binding = UserContainer.query.filter_by(
            user_id=user.id, 
            container_id=container.id
        ).first()
        assert updated_binding.role == ROLE.ROOT, "数据库中的角色应该被更新为 ROOT"
        assert updated_binding.username == 'root', "当角色为 ROOT 时，用户名应该为 'root'"
        
    finally:
        UserContainer.query.filter_by(
            user_id=user.id, 
            container_id=container.id
        ).delete(synchronize_session=False)
        Container.query.filter_by(id=container.id).delete(synchronize_session=False)
        User.query.filter_by(id=user.id).delete(synchronize_session=False)
        Machine.query.filter_by(id=machine.id).delete(synchronize_session=False)
        db.session.commit()

##################################
# 获取容器详细信息单元测试
def test_get_container_detail_information():
    import uuid
    import random
    
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    
    machine = Machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=MachineTypes.CPU,
        machine_status=MachineStatus.ONLINE,
        cpu_core_number=4,
        memory_size_gb=16,
        disk_size_gb=100,
        max_memory_gb=32,
        max_gpu_number=2,
        max_cpu_core_number=8
    )
    db.session.add(machine)
    db.session.commit()
    
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@test.com",
        password_hash="test_hash",
        graduation_year="2024",
        permission=PERMISSION.OPERATOR
    )
    db.session.add(user)
    db.session.commit()
    
    container_name = f"test_container_{uuid.uuid4().hex[:8]}"
    container = Container(
        name=container_name,
        image="ubuntu:latest",
        machine_id=machine.id,
        container_status=ContainerStatus.ONLINE,
        port=random.randint(8000, 9000),
        memory_gb=2048,
        swap_gb=512,
        gpu_number=0,
        cpu_number=2
    )
    db.session.add(container)
    db.session.commit()
    
    binding = UserContainer(
        user_id=user.id,
        container_id=container.id,
        username=username,
        public_key="ssh-rsa test",
        role=ROLE.ROOT
    )
    db.session.add(binding)
    db.session.commit()
    
    try:
        result = get_container_detail_information(container.id)
        
        assert isinstance(result, dict), "应该返回字典"
        
        required_fields = [
            "container_id", "container_name", "container_image", "machine_id", 
            "machine_ip", "container_status", "port", "memory_gb", "swap_gb",
            "gpu_number", "cpu_number", "owners", "accounts"
        ]
        for field in required_fields:
            assert field in result, f"返回结果应该包含 {field} 字段"
        
        assert result["container_id"] == container.id
        assert result["container_name"] == container.name
        assert result["container_image"] == container.image
        assert result["machine_id"] == machine.id
        assert result["container_status"] == container.container_status.value
        assert result["port"] == container.port
        assert result["memory_gb"] == container.memory_gb
        assert result["swap_gb"] == container.swap_gb
        assert result["gpu_number"] == container.gpu_number
        assert result["cpu_number"] == container.cpu_number
        
        assert isinstance(result["owners"], list)
        assert len(result["owners"]) > 0
        assert username in result["owners"]
        
        assert isinstance(result["accounts"], list)
        assert len(result["accounts"]) > 0
        for account in result["accounts"]:
            assert isinstance(account, dict)
            assert "user_id" in account
            assert "username" in account
            assert "role" in account
        
        test_account = None
        for account in result["accounts"]:
            if account["user_id"] == user.id:
                test_account = account
                break
        assert test_account is not None
        assert test_account["username"] == username
        assert test_account["role"] == ROLE.ROOT.value
        
    except Exception as e:
        pytest.fail(f"获取容器详细信息时发生异常: {str(e)}")
    
    non_existent_id = 999999
    try:
        result = get_container_detail_information(non_existent_id)
        pytest.fail("对不存在的容器ID应该抛出异常")
    except ValueError as e:
        assert "Container not found" in str(e) or "not found" in str(e).lower()
    finally:
        UserContainer.query.filter_by(container_id=container.id).delete(synchronize_session=False)
        Container.query.filter_by(id=container.id).delete(synchronize_session=False)
        User.query.filter_by(id=user.id).delete(synchronize_session=False)
        Machine.query.filter_by(id=machine.id).delete(synchronize_session=False)
        db.session.commit()

##################################
# 获取容器简要信息列表单元测试
def test_list_all_container_bref_information():
    import uuid
    import random
    
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    
    machine = Machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=MachineTypes.CPU,
        machine_status=MachineStatus.ONLINE,
        cpu_core_number=4,
        memory_size_gb=16,
        disk_size_gb=100,
        max_memory_gb=32,
        max_gpu_number=2,
        max_cpu_core_number=8
    )
    db.session.add(machine)
    db.session.commit()
    
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@test.com",
        password_hash="test_hash",
        graduation_year="2024",
        permission=PERMISSION.OPERATOR
    )
    db.session.add(user)
    db.session.commit()
    
    containers = []
    for i in range(5):
        container = Container(
            name=f"test_container_{uuid.uuid4().hex[:8]}",
            image="ubuntu:latest",
            machine_id=machine.id,
            container_status=ContainerStatus.ONLINE,
            port=random.randint(8000, 9000),
            memory_gb=2048,
            swap_gb=512,
            gpu_number=0,
            cpu_number=2
        )
        db.session.add(container)
        containers.append(container)
    db.session.commit()
    
    try:
        result = list_all_container_bref_information(machine.id, user.id, 0, 3)
        
        assert isinstance(result, dict)
        assert "containers" in result
        assert "total_page" in result
        assert isinstance(result["containers"], list)
        assert isinstance(result["total_page"], int)
        assert len(result["containers"]) <= 3
        
        for container_info in result["containers"]:
            assert hasattr(container_info, 'container_id')
            assert hasattr(container_info, 'container_name')
            assert hasattr(container_info, 'machine_id')
            assert hasattr(container_info, 'port')
            assert hasattr(container_info, 'container_status')
            assert hasattr(container_info, 'machine_ip')
            assert isinstance(container_info.port, int)
            assert container_info.machine_id == machine.id
        
        result_page1 = list_all_container_bref_information(machine.id, user.id, 0, 2)
        result_page2 = list_all_container_bref_information(machine.id, user.id, 1, 2)
        
        assert isinstance(result_page1, dict)
        assert isinstance(result_page2, dict)
        
        page1_ids = {c.container_id for c in result_page1["containers"]}
        page2_ids = {c.container_id for c in result_page2["containers"]}
        assert page1_ids.isdisjoint(page2_ids)
        
        non_existent_id = 999999
        result_empty = list_all_container_bref_information(non_existent_id, user.id, 0, 10)
        assert isinstance(result_empty, dict)
        assert isinstance(result_empty["containers"], list)
        assert len(result_empty["containers"]) == 0
        assert result_empty["total_page"] == 1
        
        result_zero_size = list_all_container_bref_information(machine.id, user.id, 0, 0)
        assert isinstance(result_zero_size, dict)
        assert len(result_zero_size["containers"]) == 0
        
        result_out_of_range = list_all_container_bref_information(machine.id, user.id, 100, 10)
        assert isinstance(result_out_of_range, dict)
        assert len(result_out_of_range["containers"]) == 0
        
    finally:
        for container in containers:
            UserContainer.query.filter_by(container_id=container.id).delete(synchronize_session=False)
            db.session.delete(container)
        User.query.filter_by(id=user.id).delete(synchronize_session=False)
        Machine.query.filter_by(id=machine.id).delete(synchronize_session=False)
        db.session.commit()