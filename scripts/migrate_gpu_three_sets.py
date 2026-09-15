"""GPU 三集合迁移 · 数据回填脚本（幂等，只补 NULL）。

背景（见 FuxiYu_Global 速查 · 决策备忘「GPU 分配 · 决策」）：
    migrations/2026-08_gpu_three_sets.sql / _ensure_gpu_columns() 负责加列；
    本脚本负责老数据回填：
    - machines.gpu_allow_list：回填 [0..gpu_number-1]（老机器显式全量许可）
    - containers.gpu_chosen_list：回填占位 [0..gpu_number-1]（按申请数量重建；
      真实卡归属需停机修正，见决策 3）
    - machines.gpu_list：无需回填（事实字段，sys_snapshot 下一帧自动写入）

用法：
    python scripts/migrate_gpu_three_sets.py                # 默认 DATABASE_URL / sqlite dev_database.db
    python scripts/migrate_gpu_three_sets.py --url "mysql+pymysql://user:pass@host:3306/fuxi"

幂等：只补 NULL 行；重复执行不重复写。执行前建议备份。
"""

import argparse
import os
import sys

pkg_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(pkg_dir)
workspace = os.path.dirname(repo_root)
if workspace not in sys.path:
    sys.path.insert(0, workspace)


def migrate(url: str) -> None:
    from sqlalchemy import create_engine, select

    from FuxiYu_CtrKernel.models.containers import Container
    from FuxiYu_CtrKernel.models.machine import Machine

    engine = create_engine(url)
    machines_fixed = containers_fixed = 0
    with engine.begin() as conn:
        # machines.gpu_allow_list：NULL 且 gpu_number > 0 → 全量许可
        for machine in conn.execute(
            select(Machine.id, Machine.gpu_number, Machine.gpu_allow_list)
        ).mappings():
            if machine["gpu_allow_list"] is None and (machine["gpu_number"] or 0) > 0:
                conn.execute(
                    Machine.__table__.update()
                    .where(Machine.id == machine["id"])
                    .values(gpu_allow_list=list(range(machine["gpu_number"])))
                )
                machines_fixed += 1
        # containers.gpu_chosen_list：NULL 且 gpu_number > 0 → 占位 [0..n-1]
        for container in conn.execute(
            select(Container.id, Container.gpu_number, Container.gpu_chosen_list)
        ).mappings():
            if container["gpu_chosen_list"] is None and (container["gpu_number"] or 0) > 0:
                conn.execute(
                    Container.__table__.update()
                    .where(Container.id == container["id"])
                    .values(gpu_chosen_list=list(range(container["gpu_number"])))
                )
                containers_fixed += 1
    print("gpu three-sets backfill done: machines=%d containers=%d" % (machines_fixed, containers_fixed))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPU 三集合迁移数据回填（幂等，只补 NULL）")
    parser.add_argument("--url", default=None, help="数据库连接串（默认 DATABASE_URL 或 sqlite dev_database.db）")
    args = parser.parse_args()
    url = args.url or os.getenv("DATABASE_URL") or "sqlite:///dev_database.db"
    migrate(url)
