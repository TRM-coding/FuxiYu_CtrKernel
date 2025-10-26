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

    # 使用第一台机器的 IP 地址
    machine = machines[0]

    for user in users:
        # 使用固定的容器名称
        cname = f"test_container_{user.username}"

        # 测试前先清理可能存在的同名容器
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
            # 创建容器
            Create_container(
                user_name=user.username,
                machine_ip=machine.machine_ip,
                container=Container_info(
                    name=cname,
                    image="ubuntu:latest",
                    gpu_list=[0],
                    cpu_number=2,
                    memory=2048
                ),
                public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7..."
            )

            # 验证插入
            assert Container.query.count() == container_count_before + 1, "容器未正确插入到数据库"

            new_container = Container.query.filter(
                Container.name == cname,
                Container.image == "ubuntu:latest",
                Container.machine_id == machine.id
            ).first()

            assert new_container is not None, "无法在数据库中找到新创建的容器"

            assert UserContainer.query.count() == usercontainer_count_before + 1, "用户容器关联未正确插入"

            user_container_binding = UserContainer.query.filter_by(
                user_id=user.id,
                container_id=new_container.id
            ).first()
            assert user_container_binding is not None, "用户容器绑定关系不存在"
            assert user_container_binding.username == user.username, "用户名不匹配"
            assert user_container_binding.public_key == "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7...", "公钥不匹配"

        finally:
            db.session.rollback()
            # 无论上面是否报错，均清理本轮创建的数据
            to_delete = Container.query.filter(
                Container.name == cname,
                Container.machine_id == machine.id
            ).all()

            for c in to_delete:
                UserContainer.query.filter_by(container_id=c.id).delete(synchronize_session=False)
                db.session.delete(c)

            db.session.commit()

            # 可选：不影响原始失败原因的情况下做软校验
            try:
                assert Container.query.count() == container_count_before
                assert UserContainer.query.count() == usercontainer_count_before
            except AssertionError:
                pass
##################################