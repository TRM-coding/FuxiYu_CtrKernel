-- 每台机器可选的 Node 监听端口（2026-09）。
--
-- 背景：端口此前是全局的（CommsConfig.NODE_PORT，默认 5789）。但无法保证每台
-- 宿主机的该端口都可用——防火墙策略、NAT 映射、端口被占用，都会让某台机器
-- 必须换端口。本列让端口成为机器属性。
--
-- 语义：
-- - 留空回落全局默认（不固化），由 node_comms_modules.endpoint 统一解析
-- - machine_ip 仍是纯 IPv4，不承载端口（入口校验拒绝含 `:` 的地址）
-- - 可空、无回填：旧行 NULL 即「回落全局默认」，行为与改动前完全一致
--
-- MySQL / MariaDB production path.
ALTER TABLE machines
    ADD COLUMN port INTEGER NULL;

-- SQLite notes:
-- 应用启动时的 _ensure_machine_endpoint_schema 会用同一条语句幂等补列，
-- 因此 SQLite 侧无需手工执行本文件。
