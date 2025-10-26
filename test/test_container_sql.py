import pytest
from ..services.container_tasks import Create_container
from ..models.user import User
from ..models.machine import Machine
from ..models.containers import Container
from ..models.usercontainer import UserContainer
from ..extensions import db
from .. import create_app
from ..utils.Container import Container_info 
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
#创建容器单元测试
def test_Create_container():
    users = User.query.all()
    machines = Machine.query.all()
    
    assert len(users) > 0, "数据库中没有测试用户数据"
    assert len(machines) > 0, "数据库中没有测试机器数据"
    
    for user in users:
        for machine in machines:
            # 记录操作前的数据库状态
            container_count_before = Container.query.count()
            usercontainer_count_before = UserContainer.query.count()
            
            # 创建容器
            Create_container(
                user_name=user.username,
                machine_ip=machine.machine_ip,
                container=Container_info(
                    user_name="test_container",
                    image="ubuntu:latest",
                    gpu_list=[0],
                    cpu_number=2,
                    memory=2048
                ),
                public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7..."
            )
            
            # 验证 container 表是否正确插入了新容器
            container_count_after = Container.query.count()
            assert container_count_after == container_count_before + 1, "容器未正确插入到数据库"
            
            # 查询刚创建的容器
            new_container = Container.query.filter_by(
                name="test_container",
                image="ubuntu:latest",
                machine_id=machine.id
            ).first()
            assert new_container is not None, "无法在数据库中找到新创建的容器"
            assert new_container.status.value == "running", "容器状态不正确"
            
            # 验证 usercontainer 表是否正确维护了容器使用者和用户名
            usercontainer_count_after = UserContainer.query.count()
            assert usercontainer_count_after == usercontainer_count_before + 1, "用户容器关联未正确插入"
            
            user_container_binding = UserContainer.query.filter_by(
                user_id=user.id,
                container_id=new_container.id
            ).first()
            assert user_container_binding is not None, "用户容器绑定关系不存在"
            assert user_container_binding.username == user.username, "用户名不匹配"
            assert user_container_binding.public_key == "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7...", "公钥不匹配"
            
            # 回滚数据库
            db.session.delete(user_container_binding)
            db.session.delete(new_container)
            db.session.commit()
            
            # 验证回滚成功
            assert Container.query.count() == container_count_before, "容器回滚失败"
            assert UserContainer.query.count() == usercontainer_count_before, "用户容器关联回滚失败"
##################################