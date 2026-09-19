-- 容器启动命令：templates 与 containers 各加一列 entrypoint（2026-09 决策）。
--
-- 背景：平台此前把容器的命令**硬编码**成 `tail -f /dev/null`（Node 侧），意图是
-- 「保证容器一直运行，等你 SSH 进来」。但 Docker 的 command **不覆盖**镜像自带的
-- ENTRYPOINT —— 镜像的入口会把这条命令当参数吃掉。实测（镜像入口为 /bin/echo）：
--
--     $ docker run ep-test:1 "tail -f /dev/null"
--     FROM-ENTRYPOINT tail -f /dev/null
--
-- 而 base_image 是自由字符串（无白名单），任何人填一个带 ENTRYPOINT 的镜像都会踩到；
-- 失败现象是"容器起来就死"，报错却是 `sshd gate failed` —— 完全无从归因。
--
-- 本次一并做三件事：
--   1. 把"容器里跑什么"变成**显式字段**：留空 = 平台默认（保持存活）；填了 = 跑它。
--   2. Node 一律以 `entrypoint=""` 建容器，使"这一条命令"成为唯一决定因素。
--   3. Dockerfile 与"落后"判定一概不涉及它——它是**运行期参数**，不是配方的一部分。
--
-- 两列都**可空且空即默认**，因此存量行无需回填、行为一字不变。
-- 默认值只写在 Node 一处，不冻进数据：否则将来改默认值要写迁移，而且"空"的语义会糊
-- （是用户没填，还是用户就想跑 tail？）。
--
-- MySQL / MariaDB production path.

ALTER TABLE images
    ADD COLUMN entrypoint VARCHAR(255) NULL;

ALTER TABLE containers
    ADD COLUMN entrypoint VARCHAR(255) NULL;

-- 语义说明（读侧一律归一，NULL 与 "" 都折成 None）：
--   images.entrypoint      建容器时的取值来源
--   containers.entrypoint  该容器**实际跑的那一份**留痕；恢复读它，不读模板
--                          否则模板改了启动命令之后，复活一个旧容器会换行为
--
-- 恢复路径刻意**不回落模板**：容器行记的是它自己那一份，与 base_image / dockerfile_body
-- 同一个道理。存量容器该列为 NULL → 走默认 → 与它当初的行为一致。

-- SQLite notes:
-- 应用启动时的 _ensure_image_template_schema / _ensure_container_image_schema 会幂等
-- 补上这两列，因此 SQLite 侧无需手工执行本文件。
