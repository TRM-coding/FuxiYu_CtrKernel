"""初始化 ~/FuxiYu_Next 三套 .env：删死键 + 补注释。

只按**键名**增删，不读取也不改写任何值（SQLPASSWORD / SECRET_KEY 等原样保留），
其余行逐字节不动。执行前先备份。

"死键" = 全仓已无读取处。判定依据是本地三仓的 grep 结果；这些是 WSS 方向反转前
的残留——那时 Node 要主动拨 Ctrl，所以需要知道 Ctrl 的地址。
"""

import datetime
import pathlib
import shutil
import sys

ROOT = pathlib.Path.home() / "FuxiYu_Next"

# 每个仓库：要删的键
DEAD_KEYS = {
    "FuxiYu_CtrKernel": ["CTRL_WSS_PORT"],
    "FuxiYu_NodeKernel": ["CTRL_IP", "CTRL_PORT", "NODE_WSS_ENABLED", "NODE_CTRL_WSS_URL"],
    "FuxiYu_Web": [],
}

# 要在某键之前插入的注释（键名 -> 注释文本）
ANNOTATIONS = {
    "CTRL_WSS_ENABLED": (
        "# 链路旁挂进程开关（名字是 WSS 时代的遗留，语义已是「Ctrl→Node 拨号管理器」）。\n"
        "# 置 0 会导致一台机器都不被拨、全线离线——不要因为名字里带 WSS 就删它。"
    ),
}

# 追加到文件末尾的说明（仓库 -> 文本）
FOOTERS = {
    "FuxiYu_NodeKernel": (
        "\n# 方向已反转：Ctrl 主动拨入 Node，Node 是被动端点。\n"
        "# 因此 Node 不需要知道 Ctrl 的地址——CTRL_IP / CTRL_PORT / NODE_CTRL_WSS_URL\n"
        "# 等键已无读取处，已于本次初始化中移除，别再按旧文档加回来。\n"
    ),
}


def rewrite(repo: str) -> tuple[list[str], list[str]]:
    path = ROOT / repo / ".env"
    original = path.read_text(encoding="utf-8")
    dead = set(DEAD_KEYS[repo])
    removed, kept = [], []

    out_lines: list[str] = []
    for line in original.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in dead:
                removed.append(key)
                continue
            if key in ANNOTATIONS:
                out_lines.append(ANNOTATIONS[key])
        out_lines.append(line)

    text = "\n".join(out_lines)
    if not text.endswith("\n"):
        text += "\n"
    if FOOTERS.get(repo):
        text += FOOTERS[repo]

    stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, path.with_name(f".env.bak-{stamp}"))
    path.write_text(text, encoding="utf-8")

    live = [
        line.strip().split("=", 1)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line
    ]
    return removed, live


def main() -> None:
    dry = "--apply" not in sys.argv
    for repo in DEAD_KEYS:
        path = ROOT / repo / ".env"
        if not path.exists():
            print(f"!! {repo}/.env 不存在，跳过")
            continue
        if dry:
            before = [
                line.strip().split("=", 1)[0].strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#") and "=" in line
            ]
            print(f"{repo}: 现有 {len(before)} 键；将删除 {DEAD_KEYS[repo] or '（无）'}")
            continue
        removed, live = rewrite(repo)
        print(f"{repo}: 删除 {removed or '（无）'} → 剩余 {len(live)} 键 {live}")

    if dry:
        print("\ndry run：未写入。加 --apply 落地（会先备份为 .env.bak-<时间戳>）。")


main()
