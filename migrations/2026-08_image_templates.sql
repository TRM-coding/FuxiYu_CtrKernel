-- 镜像模板主表：Ctrl 长期保存基础镜像与用户业务 Dockerfile 片段。
-- 最终 Dockerfile 由平台构建器在临时目录生成，不回写 DB。
CREATE TABLE IF NOT EXISTS images (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    description VARCHAR(500) NULL,
    base_image VARCHAR(255) NOT NULL,
    dockerfile_body TEXT NOT NULL,
    status ENUM('draft', 'ready', 'disabled') NOT NULL DEFAULT 'draft',
    created_by_user_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_images_name (name),
    INDEX ix_images_created_by_user_id (created_by_user_id),
    CONSTRAINT fk_images_created_by_user_id
        FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- 旧版本迁移说明（开发期可直接清表重跑 seed）：
--   ALTER TABLE images
--     ADD COLUMN base_image VARCHAR(255) NOT NULL DEFAULT 'ubuntu:22.04',
--     ADD COLUMN dockerfile_body TEXT NOT NULL;
--   若旧列 dockerfile 存完整 Dockerfile，一次性脚本解析首个 FROM 为 base_image，
--   其余内容写入 dockerfile_body，确认后删除旧 dockerfile 列。

-- user-i 从裸 image_id 升级为正式镜像资源外键。
ALTER TABLE user_images
    ADD CONSTRAINT fk_user_images_image_id
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE;
