-- 平台注入片段：加一条**装完断言**（2026-09 决策）。
--
-- 症状（2026-09 实测）：某台机器构建时够不到 apt 源，`apt-get update` 失败；但注入段里
-- 那一串是 `apt-get update && install && rm ...`，失败发生在 `&&` 链的**非末尾**位置——
-- `set -e` **不会**因此退出，而它后面还有一条 `mkdir -p /run/sshd` 会成功，于是整层退出 0：
-- **构建"成功"，镜像里却没有 openssh**。那个坏镜像随后在下游以
-- `ssh-keygen: not found`（sshd 门禁失败）的形式暴露，而根因在完全不同的地方，
-- 排查时只能从上层症状一路倒推。
--
-- 修法：装完**断言它真的在**。装不上就当场构建失败，错误停在它该停的那一层。
-- 三个分支（apt / apk / dnf）共用这一条断言。
--
-- 同步改了 `services/settings_tasks.DEFAULT_IMAGE_PLATFORM_INJECTION_CONTENT`（新库的默认值）。
-- 本文件只服务**已经存在的**库——线上用的是 system_settings 里那一行，不吃代码默认值。
--
-- ⚠ 注意：改这里不会自动重建已有镜像。要让某个 (机器, 模板) 用上新注入，
--    清掉它的 machine_image 行即可（见 2026-09_container_entrypoint.sql 末尾的说明）。

UPDATE system_settings
   SET value = 'USER root
SHELL ["/bin/sh", "-c"]
RUN set -eu; \\
    if command -v apt-get >/dev/null 2>&1; then \\
        apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-server passwd && rm -rf /var/lib/apt/lists/*; \\
    elif command -v apk >/dev/null 2>&1; then \\
        apk add --no-cache openssh; \\
    elif command -v dnf >/dev/null 2>&1; then \\
        dnf install -y openssh-server shadow-utils && dnf clean all; \\
    else \\
        echo "unsupported package manager for Fuxi platform image injection" >&2; exit 1; \\
    fi; \\
    mkdir -p /run/sshd; \\
    if ! command -v ssh-keygen >/dev/null 2>&1 || ! test -x /usr/sbin/sshd; then \\
        echo "Fuxi platform image injection FAILED: ssh-keygen or sshd missing after install (package install silently failed? check the build network / apt sources)" >&2; \\
        exit 1; \\
    fi
EXPOSE 22',
       updated_at = NOW()
 WHERE `key` = 'image.platform_injection_content';
