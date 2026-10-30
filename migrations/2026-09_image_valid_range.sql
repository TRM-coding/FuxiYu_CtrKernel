-- 镜像模板的可见范围收口：valid_range 三态（2026-09 决策）。
--
-- 在此之前，"全员可见"不是一列，而是一条**派生规则**：created_by_user_id IS NULL 的
-- 系统内置模板被 _visible_scope 当成公开的。用户只能靠 user_images 授权行分享，
-- 无法把自己的模板公开，也无法明确地"只给自己看"。
--
-- 这一步把可见性收进一列：private（只有创建者）/ everyone（所有用户）/ custom（名单）。
-- 收口之后 **created_by_user_id 不再参与可见性判定**，它只剩两个用途：归属显示、
-- 以及"编辑只能动自己建的"那条归属闸（resource_type = image:owner）。
--
-- MySQL / MariaDB production path.

-- ① 加列。默认 custom 与模型默认一致（新建模板 = 创建者自带一行授权、别人看不见，
--    与旧行为逐字相同）。
ALTER TABLE images
    ADD COLUMN valid_range ENUM('private', 'everyone', 'custom') NOT NULL DEFAULT 'custom';

-- ② 存量回填：逐字保住旧语义。
--    - 系统内置（created_by IS NULL）→ everyone：它们在旧规则里就是全员可见的，
--      不回填这一条，内置模板会从所有普通用户眼前消失。
--    - 用户建的 → custom：它们在旧规则里靠 user_images 名单可见，名单原样留着即可。
--    ⚠ 这一步**只做一次**。应用侧的同名回填以"valid_range 列刚被加出来"为闸门
--      （_ensure_image_template_schema），不会在每次启动把管理员故意设成 custom 的
--      系统模板翻回 everyone。手工重复执行本文件同样会覆盖人工设置，别再跑第二遍。
UPDATE images SET valid_range = 'everyone' WHERE created_by_user_id IS NULL;
UPDATE images SET valid_range = 'custom'   WHERE created_by_user_id IS NOT NULL;

-- ③ 授权名单不动。切态时**不删 user_images 行**：切到 everyone/private 时名单原样保留，
--    切回 custom 时它还在——"曾经授权给谁"在切回来的那一刻正是用户期待看到的东西。
--    因此本迁移不触碰 user_images。
--
-- 注：非 custom 态下 set_image_visible_users 一律拒绝（error_reason = not_custom_range），
--     这是 API 层的行为，不是数据约束——名单是"存着但此刻不生效"，不是"非法状态"。

-- SQLite notes:
-- 应用启动时的 _ensure_image_template_schema 会幂等补齐本列（VARCHAR(16) + DEFAULT 'custom'），
-- 并在**加列的那一刻**执行同样的回填；create_all 建的库由模型默认值兜住。
-- SQLite 无法 ALTER 加 ENUM，按 VARCHAR 存，取值约束由应用层（ImageValidRange）保证。
