-- 容器的镜像归属改为外键 image_id（2026-09 决策）。
--
-- 背景：容器此前只有一列 image（字符串 tag），它同时兼职两件事——
--   1) 这个容器由哪个镜像模板而来（重建/恢复的依据）
--   2) 这个容器实际跑的是哪个制品（展示/溯源）
-- 兼职 1) 靠的是拿 tag 正则反解 id（services/container_module/utils.py），
-- 格式一变就断；更要命的是恢复链路直接拿 tag 回填、不再构建，于是 Node 上
-- 的 docker 制品一旦被 prune，恢复就永久失败。
--
-- 语义（两列分立，各司其职）：
-- - image_id    = 逻辑真源。指向 images.id，重建/恢复据此解析 tag 与 Dockerfile，
--                 因此不依赖 Node 上的旧制品。可空是 ondelete="SET NULL" 的要求：
--                 模板被删时容器解绑，而不是被连坐删掉，也不是留下悬挂指针。
-- - runtime_image = 纯展示。创建/恢复时物化的「本次实际跑的制品 tag」快照，
--                 旧列 image 经 RENAME 迁来（数据原地不动、NOT NULL 保留）。
--                 只允许进出参 dict、快照与审计 detail，不参与任何逻辑判断。
--
-- 顺序是硬约束：改名 → 加列 → 建索引 → 回填 → 清悬挂 → 加外键。
-- 清悬挂必须在加外键之前，否则存在指向已删模板的值时 ADD CONSTRAINT 直接失败。
-- （同族教训见 2026-09_drop_active_name.sql 的「必须先删索引再删列」。）
--
-- MySQL / MariaDB production path.
ALTER TABLE containers
    RENAME COLUMN image TO runtime_image;

ALTER TABLE containers
    ADD COLUMN image_id INTEGER NULL;

CREATE INDEX ix_containers_image_id ON containers(image_id);

-- 回填：只有 tag 形如 fuxi/image-<模板id>:<时间戳> 的才认得出归属。
-- 裸镜像 tag（如 ubuntu:24.04）无从推断，保持 NULL —— 不猜。
UPDATE containers
   SET image_id = CAST(
           SUBSTRING_INDEX(SUBSTRING_INDEX(runtime_image, '-', -1), ':', 1) AS UNSIGNED
       )
 WHERE image_id IS NULL
   AND runtime_image LIKE 'fuxi/image-%';

-- 模板行已被删的历史容器：回填出来的 id 是悬挂的，落库前清掉。
UPDATE containers
   SET image_id = NULL
 WHERE image_id IS NOT NULL
   AND image_id NOT IN (SELECT id FROM images);

ALTER TABLE containers
    ADD CONSTRAINT fk_containers_image_id
        FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE SET NULL;

-- 注：全新建的库由 create_all 建外键，名字是 MySQL 自动生成的 containers_ibfk_N，
-- 与本文件显式命名的 fk_containers_image_id 不同名。无代码引用该名字，无害。

-- SQLite notes:
-- 应用启动时的 _ensure_container_image_schema 会幂等完成改名/加列/建索引/清悬挂/
-- 回填（RENAME COLUMN 需 SQLite >= 3.25），因此 SQLite 侧无需手工执行本文件。
-- SQLite 无法 ALTER 加外键，旧库的 SET NULL 语义由两道闸补偿：
--   1) services/image_tasks.Delete_image 删模板后在同事务内调
--      containers_repo.detach_image_from_containers 主动解绑；
--   2) 启动自愈的「清悬挂」一步兜底（覆盖停机期间模板被删等漏网）。
