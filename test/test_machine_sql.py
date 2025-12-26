#machine_tasks.py 单元测试
import pytest
from ..services.machine_tasks import Add_machine, Remove_machine, Update_machine, Get_detail_information, List_all_machine_bref_information
from ..models.machine import Machine, MachineTypes, MachineStatus
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


# 每个测试文件统一使用同一个 token，作用域为 module
@pytest.fixture(scope="module")
def auth_token(app):
    import secrets
    from datetime import datetime, timedelta
    from ..repositories import authentications_repo

    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=24)
    authentications_repo.create_auth(token, expires_at)
    yield token
    # 清理
    authentications_repo.delete_auth(token)
##################################

##################################
#机器添加单元测试

def test_Add_machine():
    import uuid
    import random
    # 1) 随机化生成参数 - 使用正确的参数名
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    machine_type = random.choice(list(MachineTypes))
    machine_description = f"Test machine {uuid.uuid4().hex[:8]}"
    cpu_core_number = random.randint(1, 16)
    gpu_number = random.randint(0, 4)
    gpu_type = f"GPU_{random.randint(1000, 5000)}"
    memory_size = random.randint(4, 128)
    disk_size = random.randint(100, 2000)

    # 2) 调用 Add_machine 执行
    result = Add_machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=machine_type,
        machine_description=machine_description,
        cpu_core_number=cpu_core_number,
        gpu_number=gpu_number,
        gpu_type=gpu_type,
        memory_size=memory_size,
        disk_size=disk_size,
        token=auth_token
    )

    # 检查函数返回结果（现在返回字典，包含 status 字段）
    assert isinstance(result, dict) and result.get("status") is not None, "Add_machine 应该返回包含 'status' 的字典"

    target = None
    try:
        # 3) 访问数据库，验证结果
        machine = Machine.query.filter_by(machine_name=machine_name).first()
        target = machine
        
        assert machine is not None, "添加机器后应能在数据库中查询到机器"
        assert machine.machine_name == machine_name
        assert machine.machine_ip == machine_ip
        assert machine.machine_type == machine_type
        assert machine.machine_status == MachineStatus.MAINTENANCE  # 默认状态
        assert machine.cpu_core_number == cpu_core_number
        assert machine.memory_size_gb == memory_size
        assert machine.gpu_number == gpu_number
        assert machine.gpu_type == gpu_type
        assert machine.disk_size_gb == disk_size
        assert machine.machine_description == machine_description
        
    finally:
        leftovers = Machine.query.filter(Machine.machine_name.like("test_machine_%")).all()
        for m in leftovers:
            db.session.delete(m)
        db.session.commit()

##################################


##################################
#机器删除单元测试
def test_Remove_machine():
    import uuid
    import random
    # 1) 先创建几个测试机器
    machine_ids = []
    test_machines = []
    
    try:
        # 创建2个测试机器
        for i in range(2):
            machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
            machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
            machine_type = random.choice(list(MachineTypes))
            
            machine = Machine(
                machine_name=machine_name,
                machine_ip=machine_ip,
                machine_type=machine_type,
                machine_status=MachineStatus.MAINTENANCE,
                cpu_core_number=random.randint(1, 16),
                gpu_number=random.randint(0, 4),
                gpu_type=f"GPU_{random.randint(1000, 5000)}",
                memory_size_gb=random.randint(4, 128),
                disk_size_gb=random.randint(100, 2000),
                machine_description=f"Test machine for deletion {i+1}"
            )
            
            db.session.add(machine)
            db.session.commit()
            
            machine_ids.append(machine.id)
            test_machines.append(machine)
        
        # 验证机器已成功创建
        for machine_id in machine_ids:
            machine = Machine.query.get(machine_id)
            assert machine is not None, f"机器 {machine_id} 应该存在于数据库中"
        
        # 2) 调用 Remove_machine 执行删除
        result = Remove_machine(machine_ids, token=auth_token)
        
        # 检查函数返回结果（现在返回字典，包含 status 字段）
        assert isinstance(result, dict) and result.get("status") is not None, "Remove_machine 应该返回包含 'status' 的字典"
        
        # 3) 验证机器已被删除
        for machine_id in machine_ids:
            machine = Machine.query.get(machine_id)
            assert machine is None, f"机器 {machine_id} 应该已被删除"
            
    finally:
        # 双保险清理：重新查询再删
        remaining = Machine.query.filter(Machine.machine_name.like("test_machine_%")).all()
        for m in remaining:
            db.session.delete(m)
        db.session.commit()
##################################


##################################
#机器更新单元测试
def test_Update_machine():
    import uuid
    import random
    
    # 1) 首先创建一个测试机器
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    machine_type = random.choice(list(MachineTypes))
    machine_description = f"Test machine {uuid.uuid4().hex[:8]}"
    cpu_core_number = random.randint(1, 16)
    gpu_number = random.randint(0, 4)
    gpu_type = f"GPU_{random.randint(1000, 5000)}"
    memory_size = random.randint(4, 128)
    disk_size = random.randint(100, 2000)

    # 创建测试机器
    machine = Machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=machine_type,
        machine_description=machine_description,
        cpu_core_number=cpu_core_number,
        gpu_number=gpu_number,
        gpu_type=gpu_type,
        memory_size_gb=memory_size,
        disk_size_gb=disk_size
    )
    
    db.session.add(machine)
    db.session.commit()
    
    target_machine_id = machine.id
    
    try:
        # 2) 准备更新数据 - 先验证原始数据
        original_machine = Machine.query.get(target_machine_id)
        print(f"Original CPU cores: {original_machine.cpu_core_number}")
        
        new_machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
        new_machine_ip = f"10.0.{random.randint(1, 255)}.{random.randint(1, 255)}"
        
        # 选择不同的机器类型
        available_types = list(MachineTypes)
        new_machine_type = random.choice([t for t in available_types if t != machine_type])
        
        new_machine_status = MachineStatus.MAINTENANCE
        new_cpu_core_number = random.randint(17, 32)
        new_memory_size = random.randint(129, 256)
        new_gpu_number = random.randint(5, 8)
        new_gpu_type = f"GPU_{random.randint(5001, 9000)}"
        new_disk_size = random.randint(2001, 4000)
        new_machine_description = f"test_machine_{uuid.uuid4().hex[:8]}"

        print(f"Updating CPU cores from {original_machine.cpu_core_number} to {new_cpu_core_number}")
        
        # 3) 调用 Update_machine 执行更新
        result = Update_machine(
            machine_id=target_machine_id,
            token=auth_token,
            machine_name=new_machine_name,
            machine_ip=new_machine_ip,
            machine_type=new_machine_type,
            machine_status=new_machine_status,
            cpu_core_number=new_cpu_core_number,
            memory_size_gb=new_memory_size,
            gpu_number=new_gpu_number,
            gpu_type=new_gpu_type,
            disk_size_gb=new_disk_size,
            machine_description=new_machine_description
        )

        # 检查函数返回结果（现在返回字典，包含 status 字段）
        assert isinstance(result, dict) and result.get("status") is not None, "Update_machine 应该返回包含 'status' 的字典"

        # 刷新session以确保获取最新数据
        db.session.expire_all()
        
        # 4) 验证数据库中的更新结果
        updated_machine = Machine.query.get(target_machine_id)

        assert updated_machine is not None, "更新后机器应该仍然存在"
        assert updated_machine.machine_name == new_machine_name, f"机器名称更新失败: {updated_machine.machine_name} != {new_machine_name}"
        assert updated_machine.machine_ip == new_machine_ip, f"机器IP更新失败: {updated_machine.machine_ip} != {new_machine_ip}"
        assert updated_machine.machine_type == new_machine_type, f"机器类型更新失败: {updated_machine.machine_type} != {new_machine_type}"
        assert updated_machine.machine_status == new_machine_status, f"机器状态更新失败: {updated_machine.machine_status} != {new_machine_status}"
        assert updated_machine.cpu_core_number == new_cpu_core_number, f"CPU核心数更新失败: {updated_machine.cpu_core_number} != {new_cpu_core_number}"
        assert updated_machine.memory_size_gb == new_memory_size, f"内存大小更新失败: {updated_machine.memory_size_gb} != {new_memory_size}"
        assert updated_machine.gpu_number == new_gpu_number, f"GPU数量更新失败: {updated_machine.gpu_number} != {new_gpu_number}"
        assert updated_machine.gpu_type == new_gpu_type, f"GPU类型更新失败: {updated_machine.gpu_type} != {new_gpu_type}"
        assert updated_machine.disk_size_gb == new_disk_size, f"磁盘大小更新失败: {updated_machine.disk_size_gb} != {new_disk_size}"
        assert updated_machine.machine_description == new_machine_description, f"机器描述更新失败: {updated_machine.machine_description} != {new_machine_description}"
        
        # 5) 测试部分字段更新
        partial_new_name = f"test_machine_{uuid.uuid4().hex[:8]}"
        partial_new_cpu = random.randint(33, 64)
        
        result_partial = Update_machine(
            machine_id=target_machine_id,
            token=auth_token,
            machine_name=partial_new_name,
            cpu_core_number=partial_new_cpu
        )
        
        assert isinstance(result_partial, dict) and result_partial.get("status") is not None, "部分更新应该返回包含 'status' 的字典"
        
        # 刷新session
        db.session.expire_all()
        
        # 验证部分更新结果
        partially_updated_machine = Machine.query.get(target_machine_id)
        
        assert partially_updated_machine.machine_name == partial_new_name, f"部分更新名称失败: {partially_updated_machine.machine_name} != {partial_new_name}"
        assert partially_updated_machine.cpu_core_number == partial_new_cpu, f"部分更新CPU失败: {partially_updated_machine.cpu_core_number} != {partial_new_cpu}"
        # 其他字段应该保持不变
        assert partially_updated_machine.machine_ip == new_machine_ip, f"部分更新后IP被意外修改: {partially_updated_machine.machine_ip} != {new_machine_ip}"
        
        # 测试组合1：只更新机器状态和描述
        new_status = MachineStatus.ONLINE if new_machine_status == MachineStatus.MAINTENANCE else MachineStatus.MAINTENANCE
        new_desc = f"test_machine_{uuid.uuid4().hex[:4]}"
        
        result_combo1 = Update_machine(
            machine_id=target_machine_id,
            token=auth_token,
            machine_status=new_status,
            machine_description=new_desc
        )
        
        assert isinstance(result_combo1, dict) and result_combo1.get("status") is not None, "组合1部分更新应该返回包含 'status' 的字典"
        db.session.expire_all()
        
        combo1_machine = Machine.query.get(target_machine_id)
        assert combo1_machine.machine_status == new_status, f"组合1状态更新失败: {combo1_machine.machine_status} != {new_status}"
        assert combo1_machine.machine_description == new_desc, f"组合1描述更新失败: {combo1_machine.machine_description} != {new_desc}"
        # 验证其他字段未改变
        assert combo1_machine.machine_name == partial_new_name, f"组合1更新后名称被意外修改"
        assert combo1_machine.cpu_core_number == partial_new_cpu, f"组合1更新后CPU被意外修改"
        
        # 测试组合2：只更新硬件配置（CPU、内存、磁盘）
        new_cpu_combo = random.randint(1, 8)
        new_memory_combo = random.randint(8, 32)
        new_disk_combo = random.randint(500, 1000)
        
        result_combo2 = Update_machine(
            machine_id=target_machine_id,
            token=auth_token,
            cpu_core_number=new_cpu_combo,
            memory_size_gb=new_memory_combo,
            disk_size_gb=new_disk_combo
        )
        
        assert isinstance(result_combo2, dict) and result_combo2.get("status") is not None, "组合2部分更新应该返回包含 'status' 的字典"
        db.session.expire_all()
        
        combo2_machine = Machine.query.get(target_machine_id)
        assert combo2_machine.cpu_core_number == new_cpu_combo, f"组合2 CPU更新失败: {combo2_machine.cpu_core_number} != {new_cpu_combo}"
        assert combo2_machine.memory_size_gb == new_memory_combo, f"组合2 内存更新失败: {combo2_machine.memory_size_gb} != {new_memory_combo}"
        assert combo2_machine.disk_size_gb == new_disk_combo, f"组合2 磁盘更新失败: {combo2_machine.disk_size_gb} != {new_disk_combo}"
        # 验证其他字段未改变
        assert combo2_machine.machine_status == new_status, f"组合2更新后状态被意外修改"
        assert combo2_machine.machine_description == new_desc, f"组合2更新后描述被意外修改"

    finally:
        # 清理所有测试机器
        leftovers = Machine.query.filter(Machine.machine_name.like("test_machine_%")).all()
        for m in leftovers:
            db.session.delete(m)
        db.session.commit()
##################################


##################################
#机器的详细信息获取单元测试
def test_Get_detail_information():
    import uuid
    import random
    from ..models.containers import Container, ContainerStatus

    # 1) 创建一台测试机器
    machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
    machine_ip = f"10.10.{random.randint(1,255)}.{random.randint(1,255)}"
    machine_type = random.choice(list(MachineTypes))
    machine_status = random.choice(list(MachineStatus))
    cpu_core_number = random.randint(1, 16)
    gpu_number = random.randint(0, 4)
    gpu_type = f"GPU_{random.randint(1000, 5000)}"
    memory_size_gb = random.randint(8, 64)
    disk_size_gb = random.randint(100, 500)
    machine_description = "Test machine for detail check"

    test_machine = Machine(
        machine_name=machine_name,
        machine_ip=machine_ip,
        machine_type=machine_type,
        machine_status=machine_status,
        cpu_core_number=cpu_core_number,
        gpu_number=gpu_number,
        gpu_type=gpu_type,
        memory_size_gb=memory_size_gb,
        disk_size_gb=disk_size_gb,
        machine_description=machine_description
    )
    db.session.add(test_machine)
    db.session.commit()
    machine_id = test_machine.id

    try:
        # 2)  创建两个容器并关联机器
        container1 = Container(
            name=f"container_{uuid.uuid4().hex[:6]}",
            image="nginx:latest",
            machine_id=machine_id,
            container_status=random.choice(list(ContainerStatus)),
            port=random.randint(2000, 6000)
        )
        container2 = Container(
            name=f"container_{uuid.uuid4().hex[:6]}",
            image="redis:latest",
            machine_id=machine_id,
            container_status=random.choice(list(ContainerStatus)),
            port=random.randint(6001, 9000)
        )
        db.session.add_all([container1, container2])
        db.session.commit()

        # 3) 调用被测函数
        result = Get_detail_information(machine_id, token=auth_token)

        # 4) 验证返回类型与结构
        assert result is not None, "Get_detail_information 应该返回对象，而不是 None"
        assert isinstance(result.containers, list), "containers 字段应为列表"
        assert len(result.containers) == 2, f"应返回2个容器，实际返回 {len(result.containers)}"

        # 5) 验证字段正确性
        assert result.machine_name == machine_name
        assert result.machine_ip == machine_ip
        assert result.machine_type == machine_type.value
        assert result.machine_status == machine_status.value
        assert result.cpu_core_number == cpu_core_number
        assert result.gpu_number == gpu_number
        assert result.gpu_type == gpu_type
        assert result.memory_size_gb == memory_size_gb
        assert result.disk_size_gb == disk_size_gb
        assert result.machine_description == machine_description

        # 验证容器ID匹配
        container_ids = {container1.id, container2.id}
        assert set(result.containers) == container_ids, f"返回的容器ID不匹配，应为 {container_ids}，实际为{result.containers}"

        # 6) 测试不存在的ID
        invalid_id = machine_id + 9999
        result_none = Get_detail_information(invalid_id, token=auth_token)
        assert result_none is None, "不存在的机器ID应返回 None"

        print("Get_detail_information 测试通过")

    finally:
        leftovers_containers = Container.query.filter(Container.machine_id == machine_id).all()
        for c in leftovers_containers:
            db.session.delete(c)
        leftovers_machines = Machine.query.filter(Machine.machine_name.like("test_machine_%")).all()
        for m in leftovers_machines:
            db.session.delete(m)
        db.session.commit()
##################################


##################################
#获取一批机器的概要信息
def test_List_all_machine_bref_information():
    import uuid
    import random

    # 1) 创建几个测试机器用于分页测试
    test_machines = []
    
    try:
        # 创建5个测试机器，确保有足够数据测试分页
        for i in range(5):
            machine_name = f"test_machine_{uuid.uuid4().hex[:8]}"
            machine_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
            machine_type = random.choice(list(MachineTypes))
            machine_status = random.choice(list(MachineStatus))
            
            machine = Machine(
                machine_name=machine_name,
                machine_ip=machine_ip,
                machine_type=machine_type,
                machine_status=machine_status,
                cpu_core_number=random.randint(1, 16),
                gpu_number=random.randint(0, 4),
                gpu_type=f"GPU_{random.randint(1000, 5000)}",
                memory_size_gb=random.randint(4, 128),
                disk_size_gb=random.randint(100, 2000),
                machine_description=f"Test machine for listing {i+1}"
            )
            
            db.session.add(machine)
            test_machines.append(machine)
        
        db.session.commit()
        
        # 2) 测试第一页，每页3条数据
        page_number = 0
        page_size = 3
        result_page1 = List_all_machine_bref_information(page_number, page_size, token=auth_token)
        
        # 检查返回结果
        assert result_page1 is not None, "函数应该返回列表，而不是None"
        assert isinstance(result_page1, list), "函数应该返回列表"
        assert len(result_page1) == page_size, f"第一页应该返回{page_size}条数据"
        
        # 检查返回的数据结构
        for machine_info in result_page1:
            assert hasattr(machine_info, 'machine_ip'), "机器概要信息应该包含machine_ip字段"
            assert hasattr(machine_info, 'machine_type'), "机器概要信息应该包含machine_type字段"
            assert hasattr(machine_info, 'machine_status'), "机器概要信息应该包含machine_status字段"
            
            # 验证字段值不为空
            assert machine_info.machine_ip is not None, "机器IP不应该为空"
            assert machine_info.machine_type is not None, "机器类型不应该为空"
            assert machine_info.machine_status is not None, "机器状态不应该为空"
            
            # 验证机器类型和状态是有效的枚举值
            assert machine_info.machine_type in [t.value for t in MachineTypes], f"机器类型 {machine_info.machine_type} 应该是有效的MachineTypes枚举值"
            assert machine_info.machine_status in [s.value for s in MachineStatus], f"机器状态 {machine_info.machine_status} 应该是有效的MachineStatus枚举值"
        
        # 3) 测试第二页，每页3条数据
        page_number = 1
        page_size = 3
        result_page2 = List_all_machine_bref_information(page_number, page_size, token=auth_token)
        
        total_count = Machine.query.count()
        assert result_page2 is not None, "第二页函数应该返回列表，而不是None"
        assert isinstance(result_page2, list), "第二页函数应该返回列表"
        # 第二页应该返回剩余的数据（5-3=2条）
        expected_page2_count = max(0, min(page_size, total_count - page_number * page_size))
        assert len(result_page2) == expected_page2_count, f"第二页应该返回{expected_page2_count}条数据，实际返回{len(result_page2)}条"
        
        # 4) 测试空页（超出数据范围）
        page_number = 2
        page_size = 3
        result_empty = List_all_machine_bref_information(page_number, page_size, token=auth_token)

        total_count = Machine.query.count()
        expected_count = max(0, min(page_size, total_count - page_number * page_size))

        assert result_empty is not None, "空页函数应该返回列表，而不是None"
        assert isinstance(result_empty, list), "空页函数应该返回列表"
        assert len(result_empty) == expected_count, f"页 {page_number} 应返回 {expected_count} 条数据，实际返回 {len(result_empty)} 条"
                
        # 5) 测试所有机器（大页面）
        page_number = 0
        page_size = 100  # 足够大的页面大小获取所有机器
        result_all = List_all_machine_bref_information(page_number, page_size, token=auth_token)

        # 动态计算预期数量（根据实际数据库）
        total_count = Machine.query.count()

        assert len(result_all) == total_count, \
            f"获取所有机器应该返回 {total_count} 条数据，实际返回 {len(result_all)} 条"
        
        # 6) 验证返回数据的正确性 - 检查第一台机器的数据是否与数据库匹配
        if len(result_page1) > 0:
            first_result = result_page1[0]
            # 根据IP查找对应的机器
            corresponding_machine = Machine.query.filter_by(machine_ip=first_result.machine_ip).first()
            
            assert corresponding_machine is not None, "返回的机器IP应该在数据库中存在对应机器"
            assert first_result.machine_type == corresponding_machine.machine_type.value, "返回的机器类型应该与数据库中的值匹配"
            assert first_result.machine_status == corresponding_machine.machine_status.value, "返回的机器状态应该与数据库中的值匹配"
        
        print("List_all_machine_bref_information 测试通过")
            
    finally:
        # 7) 清理测试数据
        for machine in test_machines:
            db.session.delete(machine)
        db.session.commit()