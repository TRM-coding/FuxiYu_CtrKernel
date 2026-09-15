-- 容器镜像归属的收口：构建留痕、Dockerfile 快照、模板停用（2026-09 决策）。
--
-- 本文件承接 2026-09_container_image_id.sql，是同一主题的第二步。那一步把镜像归属
-- 从"字符串正则反解"变成外键；这一步补齐它缺的三件事：
--
--   1. 构建留痕 last_build_at —— 记录"本次构建所依据的模板版本时刻"，使
--      「容器是否落后于模板」可判定，并让镜像标签可推导（因此标签不再落库）。
--   2. 配方留痕 —— 容器实际使用的那份 Dockerfile，用于展示运行基底、以及作为精确还原的
--      内容来源。存的是**渲染前的输入**（base_image / dockerfile_body），不是渲染后的整段
--      文本：渲染结果是派生值，落库等于给同一个事实造第二个来源。
--      **平台注入不存**：它永远取当下的系统设置（不是用户的内容，而是平台设施——
--      容器该带的是现在这一版 sshd 那套，不是它当年那版）。
--      二次决策（2026-09）把它从单列 image_dockerfile 改成两项，见 ⑦。
--   3. 模板移除改为「停用」—— 归属外键因此永不触发，"构建自哪个模板"这个事实不丢；
--      同时移除 images.name 的唯一约束（停用行会继续占名，唯一约束会让名字永久不可复用）。
--
-- 顺序是硬约束：先去外键 → 再改约束/加列 → 最后按新语义重建外键。
--
-- MySQL / MariaDB production path.

-- ① 外键语义变更：ON DELETE SET NULL → 普通外键（无 ondelete）。
--    模板改为停用后不再有物理删除，外键永不触发，归属标识的值因此永不改变。
--    MySQL 为外键自动建了同名索引，DROP FOREIGN KEY 之后要一并 DROP INDEX。
ALTER TABLE containers
    DROP FOREIGN KEY fk_containers_image_id;

ALTER TABLE containers
    DROP INDEX fk_containers_image_id;

ALTER TABLE containers
    ADD CONSTRAINT fk_containers_image_id
        FOREIGN KEY (image_id) REFERENCES images(id);

-- ② 构建留痕与配方两项。
ALTER TABLE containers
    ADD COLUMN last_build_at DATETIME NULL;

ALTER TABLE containers
    ADD COLUMN base_image VARCHAR(255) NULL;

ALTER TABLE containers
    ADD COLUMN dockerfile_body TEXT NULL;

-- ③ 存量回填 last_build_at：标签 fuxi/image-<模板id>:<版本戳> 里编码的版本时间即为该值。
--    裸镜像标签无从推断，保持 NULL（不猜）。幂等：只补 NULL。
UPDATE containers
   SET last_build_at = STR_TO_DATE(
           SUBSTRING_INDEX(runtime_image, ':', -1), '%Y%m%dT%H%i%sZ'
       )
 WHERE last_build_at IS NULL
   AND runtime_image LIKE 'fuxi/image-%:%Z';

-- 注：STR_TO_DATE 对格式不符的值返回 NULL，因此上面那条即使碰上畸形标签也只会留空，
--     不会写入垃圾。存量的配方两项保持为空——历史配方无从重建。

-- ④ 模板名唯一性移交应用层：停用的模板继续占名，唯一约束会让该名字永久不可复用。
--    应用层在「未停用」的模板之间查重（image_repo 的创建/改名路径）。
--    全新建的库由 create_all 按模型建出（模型已去掉 unique）。
ALTER TABLE images
    DROP INDEX name;

-- ⑤ 已删容器快照 JSON 里的 image 键退役。
--    那个键存的是删除当刻的标签字符串，两个消费者都已改掉：恢复路径不再拿它当标签回落
--    （标签是派生值，两个输入都在容器行上），已删列表出参改为由容器行推导。
--    消费者没了，留着就是无意义保留，而且是会被抄进每份新快照的派生值。
--    应用启动时的 _strip_legacy_snapshot_image_key 会幂等完成同样的事；
--    此处显式写出，便于人工迁移时一次到位。
UPDATE deleted_container_restore_snapshot
   SET snapshot = JSON_REMOVE(snapshot, '$.image')
 WHERE JSON_CONTAINS_PATH(snapshot, 'one', '$.image');

-- ⑥ 派发记录表：Ctrl 向各机器派发过的构建。语义是「请求过」而非「建成过」，
--    纯观测、不在执行链上（详见 models/machine_image.py 的说明）。
--    该表由 create_all 创建；此处显式写出以便人工迁移时可读。
CREATE TABLE IF NOT EXISTS machine_image (
    id INT AUTO_INCREMENT PRIMARY KEY,
    machine_id INT NOT NULL,
    image_tag VARCHAR(200) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_machine_image_tag UNIQUE (machine_id, image_tag),
    CONSTRAINT fk_machine_image_machine_id
        FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE,
    INDEX ix_machine_image_machine_id (machine_id)
);

-- ⑦ 配方留痕：单列 image_dockerfile → 两项输入（2026-09 二次决策）。
--    该列是本次变更新引入、**从未发布**的，因此没有"旧库还在依赖它"这回事。
--    但若库里已经有值，先做一次验证性对齐再删：拿该容器 image_id 对应模板此刻的配方渲染
--    一份，与存量文本逐字节比对，相同即写入两项——相同就证明当初写进去的就是这一份。
--    不做文本反解：渲染结果是纯文本，段边界没有标记，反解只会引入脆弱的启发式。
--    ⚠ 前置条件：先让应用启动一次（跑完 _backfill_container_dockerfile_parts，它幂等），
--    再执行下面这条 DROP。纯 SQL 里做不了"渲染后逐字节比对"，所以转换只能在应用侧做；
--    应用只在**所有存量行都转出成功**时才自动删列——还有转不出来的行，旧列就是它们配方
--    的唯一留存，那种情况下**不要**手工删。
ALTER TABLE containers
    DROP COLUMN image_dockerfile;

-- ⑧ runtime_image 退役（2026-09 二次决策）。
--    它存的是"本次实跑制品的标签"——一个派生值（归属标识 + 版本戳一算就有）。标签改由
--    format_image_build_tag 纯推导后，它唯一的读点是展示回落，而那个回落在推导成功时
--    永远轮不到；写点却还在每一行上抄一份。
--    ⚠ 前置条件：**必须排在上面的回填之后**（③ 正是从这一列反解归属与版本戳的）。
--    ⚠ 这一步也是必须做的，不只是清理：旧库里这一列是 NOT NULL，而新代码不再写它——
--    不删掉，新容器根本插不进去。
ALTER TABLE containers
    DROP COLUMN runtime_image;

-- SQLite notes:
-- 应用启动时的 _ensure_container_image_schema 会幂等补齐 last_build_at 与配方两项、
-- 回填并退役 image_dockerfile 与 runtime_image；machine_image 表由 create_all 建出。
-- SQLite 无法 ALTER 加外键、也无法直接 DROP 唯一约束（内联 UNIQUE 需重建表），
-- 因此旧 SQLite 库的这两项由以下事实兜住：
--   - 外键缺失：模板不再被物理删除，悬挂值无从产生，语义等价；
--   - 唯一约束残留：多个停用行可继续占用各自名字，不阻塞新建（应用层查重只看未停用行）。
