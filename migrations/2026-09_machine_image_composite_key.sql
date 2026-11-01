-- machine_image 行身份：从 (machine_id, image_tag) 收敛到 (machine_id, image_id)（2026-09 决策）。
--
-- 背景：这张表记的是「Ctrl 把哪个模板的制品派发到了哪台机器」。它此前按
-- (machine_id, image_tag) 组织——**拿标签当身份**。而标签是派生值
-- （services/image_tasks.format_image_build_tag 由「归属标识 + 版本戳」算出），
-- 让它承担身份正是本次改造一路在消灭的模式：格式一变就断，检索也就跟着断。
--
-- 语义随之从「派发历史」变为「该 (机器, 模板) 当前物化的制品」：
--   - 检索一律走 (machine_id, image_id) 复合键
--   - image_tag 只作为**值**随行读回，MUST NOT 出现在任何查询谓词里
--   - 模板更新后新标签落到**同一行**（写点改写），不再产生新行
--
-- 顺序是硬约束：先补列 → 再回填 → 清掉回填不出来的行 → 最后才换唯一键。
-- 回填之前换键，(machine_id, image_id) 上的重复 NULL 会当场撞新约束。
--
-- MySQL / MariaDB production path.

-- ① 补列（可空：存量行还没有归属）
ALTER TABLE machine_image
    ADD COLUMN image_id INTEGER NULL;

-- ② 回填：存量行只有标签这一个载体，只能反解。只认 fuxi/image-<模板id>:… 这个形式。
--    反解只服务这一次性迁移——新代码一律按复合键检索，不再反解字符串。
--    （同族先例见 __init__._backfill_container_image_id。）
UPDATE machine_image
   SET image_id = CAST(
           SUBSTRING_INDEX(SUBSTRING_INDEX(image_tag, '-', -1), ':', 1) AS UNSIGNED
       )
 WHERE image_id IS NULL
   AND image_tag LIKE 'fuxi/image-%';

-- ③ 模板行已被删的历史行：回填出来的是悬挂值，且复合键语义下不会被任何检索命中。
UPDATE machine_image
   SET image_id = NULL
 WHERE image_id IS NOT NULL
   AND image_id NOT IN (SELECT id FROM images);

-- 现在仍为 NULL 的行：身份无从确定（标签不是本平台生成的格式）。删掉——它们的存在
-- 只会让新唯一键建不上，而新键建不上就是启动即崩。
-- 注：本表所有行都由 services/container_tasks._record_machine_image 写入，而它写的标签
-- 恒来自 format_image_build_tag，因此现实中这里应当是 0 行。
DELETE FROM machine_image WHERE image_id IS NULL;

-- ④ 换唯一键：旧键落在标签上。
ALTER TABLE machine_image
    DROP INDEX uq_machine_image_tag;

ALTER TABLE machine_image
    ADD UNIQUE KEY uq_machine_image_machine_id_image_id (machine_id, image_id);

-- ⑤ 收紧非空（回填与清理之后不该再有空值）。
ALTER TABLE machine_image
    MODIFY image_id INTEGER NOT NULL;

-- ⑥ 归属外键：与 containers.image_id 同款（模板只停用不删除，因此永不触发）。
--    全新建的库由 create_all 建出，名字是 MySQL 自动生成的 machine_image_ibfk_N。
ALTER TABLE machine_image
    ADD CONSTRAINT fk_machine_image_image_id
        FOREIGN KEY (image_id) REFERENCES images(id);

-- SQLite notes:
-- 应用启动时的 _ensure_machine_image_schema 会幂等完成补列 / 回填 / 清理 / 换唯一键，
-- 因此 SQLite 侧无需手工执行本文件。
-- SQLite 无法直接 DROP 内联 UNIQUE 表约束、也无法 MODIFY 列的 NOT NULL，旧 SQLite 库
-- 的这两项由以下事实兜住：写点按复合键改写同一行，永远不会产生重复标签，旧约束因此
-- 永不触发；新建的库由 create_all 直接按模型建出（复合唯一键 + NOT NULL）。
