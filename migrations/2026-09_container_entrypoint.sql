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

-- ── 一次性数据收敛：清空构建标签缓存 ────────────────────────────────────────────
--
-- 为什么必须清：缓存行里存的标签是**旧公式**（f(归属, 模板版本)）算出来的，而宿主机上
-- 那个镜像的 Dockerfile 里**没有 ENTRYPOINT 行**（这次才加进渲染）。不清的话，缓存命中
-- 会把旧镜像继续复用下去——展示/留痕说它是按新配方建的，实际跑的是旧的，三处对不上。
--
-- 清掉之后：下次派发无行可命中 → 现造新标签 → 宿主机必然未命中 → 重建 → 三处一致。
--
-- ⚠ **一次性，只在本次上线执行。** 重放本文件会无端触发一次全量重建。迁移工具若会重复
--    执行本文件，请把这一段单独摘出来人工跑一次。
--
-- 注意它**不动** images.updated_at，因此不会让全部容器突然显示"落后于模板"——
-- 这正是"清缓存"比"顶模板时间戳"干净的地方。
DELETE FROM machine_image;
