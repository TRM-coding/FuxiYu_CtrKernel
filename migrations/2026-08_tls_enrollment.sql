-- ─────────────────────────────────────────────────────────────
-- 现网迁移：TOFU 接入凭据字段（TLS 方案，2026-08）
-- 对应 models/machine.py 新增三列；create_all 只影响新库，现网用本脚本。
-- 双凭据：node_uid（应用层标识）+ node_cert_fingerprint（传输层凭证），
-- 均唯一、可独立吊销轮换；未接入（未首连）时为 NULL。
-- ─────────────────────────────────────────────────────────────

ALTER TABLE machines
  ADD COLUMN node_uid VARCHAR(128) NULL COMMENT 'Ctrl 首连颁发的高熵 UID（应用层标识）',
  ADD COLUMN node_cert_fingerprint VARCHAR(128) NULL COMMENT 'Node 自签证书 SHA-256 指纹（传输层凭证）',
  ADD COLUMN cert_pinned_at DATETIME NULL COMMENT 'TOFU 首连 pin 时间';

ALTER TABLE machines
  ADD UNIQUE INDEX uq_machines_node_uid (node_uid),
  ADD UNIQUE INDEX uq_machines_node_cert_fingerprint (node_cert_fingerprint);

-- 回滚：
--   ALTER TABLE machines DROP INDEX uq_machines_node_cert_fingerprint,
--                        DROP INDEX uq_machines_node_uid;
--   ALTER TABLE machines DROP COLUMN cert_pinned_at,
--                        DROP COLUMN node_cert_fingerprint,
--                        DROP COLUMN node_uid;
