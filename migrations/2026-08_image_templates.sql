-- 镜像模板主表：Ctrl 长期保存 Dockerfile 与可选 pre_build.sh（内容直存 DB Text，
-- 与元数据同事务，无文件系统悬挂态；Node 构建时由 Ctrl 下发内容或落临时文件）。
CREATE TABLE IF NOT EXISTS images (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    description VARCHAR(500) NULL,
    dockerfile TEXT NOT NULL,
    pre_build TEXT NULL,
    status ENUM('draft', 'ready', 'disabled') NOT NULL DEFAULT 'draft',
    created_by_user_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_images_name (name),
    INDEX ix_images_created_by_user_id (created_by_user_id),
    CONSTRAINT fk_images_created_by_user_id
        FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- 旧版本（路径列）迁移说明（2026-08，文件系统 → DB Text）：
--   ALTER TABLE images
--     CHANGE dockerfile_path dockerfile TEXT NOT NULL,
--     CHANGE pre_build_path pre_build TEXT NULL;
--   存量内容导入：读取 storage/images 下旧路径文件写入新列后删除旧目录（一次性脚本，开发期可直接清表重跑 seed）。

-- user-i 从裸 image_id 升级为正式镜像资源外键。
ALTER TABLE user_images
    ADD CONSTRAINT fk_user_images_image_id
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE;
