"""一次性 schema 增差比对：以指定数据库为基准，与当前代码模型做 diff，输出补齐/清理 SQL。

用法：
    # 以本地 sqlite 开发库为基准（预演用）
    python scripts/diff_schema_to_sql.py --baseline "sqlite:////path/to/dev_database.db" -o fix.sql
    # 以远端生产 MySQL 为基准（只读比对，不写库）
    python scripts/diff_schema_to_sql.py --baseline "mysql+pymysql://user:pass@host:3306/fuxi" -o fix.sql

输出为 MySQL 方言的一次性迁移脚本：
    - 代码有、基准没有的表      → CREATE TABLE
    - 代码有、基准表没有的列    → ALTER TABLE ... ADD COLUMN
    - 基准有、代码已移除的列    → ALTER TABLE ... DROP COLUMN（附注释）
    - 缺索引                    → CREATE INDEX（附注释；MySQL 无 IF NOT EXISTS，重跑需人工确认）

脚本只读基准库（inspector 查询），不写任何数据。
"""

import argparse
import os
import sys

# 与 run.py 相同的包路径处理：仓库根目录本身就是 FuxiYu_CtrKernel 包，
# sys.path 需插入仓库根的上级（e:/AI/Fuxi），import FuxiYu_CtrKernel 才能生效。
pkg_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(pkg_dir)
workspace = os.path.dirname(repo_root)
if workspace not in sys.path:
    sys.path.insert(0, workspace)


def _load_models():
    """导入全部模型注册到 Base.metadata。"""
    from FuxiYu_CtrKernel import models  # noqa: F401
    from FuxiYu_CtrKernel.extensions import Base
    return Base


def _mysql_dialect():
    from sqlalchemy.dialects import mysql
    return mysql.dialect()


def _column_ddl(col) -> str:
    """单个列渲染为 MySQL 方言 DDL（name TYPE [NOT NULL] [DEFAULT ...]）。"""
    from sqlalchemy.schema import CreateColumn
    return str(CreateColumn(col).compile(dialect=_mysql_dialect())).strip()


def _collect_columns(metadata, table_name):
    return {c.name: c for c in metadata.tables[table_name].columns}


def diff(baseline_url: str, out_path: str) -> None:
    from sqlalchemy import create_engine, inspect

    from sqlalchemy.schema import CreateTable

    Base = _load_models()
    metadata = Base.metadata

    engine = create_engine(baseline_url)
    inspector = inspect(engine)

    baseline_tables = set(inspector.get_table_names())
    model_tables = set(metadata.tables.keys())

    lines: list[str] = []
    lines.append("-- 一次性 schema 增差迁移（由 scripts/diff_schema_to_sql.py 生成）")
    lines.append("-- 基准库: %s" % baseline_url.split("@")[-1])
    lines.append("-- 原则：只做与代码声明对齐所需的 DDL；列删除前请人工确认无历史数据依赖。")
    lines.append("-- 建议：执行前备份（mysqldump --no-data），执行后重跑本脚本应输出空差异。")
    lines.append("")

    # 1) 缺表 → CREATE TABLE
    missing_tables = sorted(model_tables - baseline_tables)
    if missing_tables:
        lines.append("-- ── 代码有、基准没有的表 ──")
        for tname in missing_tables:
            lines.append("-- [TABLE] %s" % tname)
            lines.append(str(CreateTable(metadata.tables[tname]).compile(dialect=_mysql_dialect())) + ";")
            lines.append("")
    else:
        lines.append("-- 无缺表")

    # 2/3) 缺列 / 残留列
    common_tables = sorted(model_tables & baseline_tables)
    any_column_change = False
    for tname in common_tables:
        baseline_cols = {c["name"] for c in inspector.get_columns(tname)}
        model_cols = _collect_columns(metadata, tname)

        add = sorted(set(model_cols) - baseline_cols)
        drop = sorted(baseline_cols - set(model_cols))

        if not add and not drop:
            continue
        any_column_change = True
        lines.append("-- ── 表 %s ──" % tname)
        for cname in add:
            lines.append("-- [ADD COLUMN] %s.%s" % (tname, cname))
            lines.append("ALTER TABLE `%s` ADD COLUMN %s;" % (tname, _column_ddl(model_cols[cname])))
            lines.append("")
        for cname in drop:
            lines.append("-- [DROP COLUMN] %s.%s（代码已移除该字段；确认无引用后放开下行）" % (tname, cname))
            lines.append("-- ALTER TABLE `%s` DROP COLUMN `%s`;" % (tname, cname))
            lines.append("")
    if not any_column_change:
        lines.append("-- 无列级差异")

    # 4) 缺索引（只提示，不自动生成 DROP）
    any_index_change = False
    for tname in common_tables:
        try:
            baseline_indexes = {ix["name"] for ix in inspector.get_indexes(tname)}
        except Exception:
            baseline_indexes = set()
        for idx in metadata.tables[tname].indexes:
            if idx.name in baseline_indexes:
                continue
            any_index_change = True
            lines.append("-- [ADD INDEX] %s（MySQL 无 IF NOT EXISTS，确认缺失后手动执行）" % idx.name)
            lines.append("-- CREATE INDEX `%s` ON `%s` (%s);" % (
                idx.name, tname, ", ".join("`%s`" % c for c in idx.columns.keys())))
            lines.append("")
    if not any_index_change:
        lines.append("-- 无索引级差异")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("diff done -> %s" % out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="schema 增差比对生成一次性迁移 SQL")
    parser.add_argument("--baseline", required=True, help="基准库连接串（sqlite:/// 或 mysql+pymysql://）")
    parser.add_argument("-o", "--output", required=True, help="输出 SQL 文件路径")
    args = parser.parse_args()
    diff(args.baseline, args.output)
