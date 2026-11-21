#!/usr/bin/env python3
"""
在云端编译前给 Swipt 源码打「预装插件」补丁：
1) 把优化版 skip-chinese-ads-optimized.swiplet 复制成 App bundle 资源
   Swipt/Resources/BundledSkipAds.swiplet —— 项目用 PBXFileSystemSynchronizedRootGroup，
   放进 Swipt/ 目录的资源会自动打进 App bundle，无需改 project.pbxproj。
2) 在 Platform.init() 里 core 创建后、reload 前插入首次启动预装逻辑：
   若 Application Support/Swiplets 里没有 skip-chinese-ads，则从 bundle 解压安装。

幂等：重复执行不会重复插入（用标记检测）。
用法：python3 scripts/prebundle.py            （在 swipt 仓库根目录运行）
"""
from pathlib import Path
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
SRC_SWIPLET = ROOT.parent / "swiplet" / "skip-chinese-ads-optimized.swiplet"
# 兼容 workflow 里把整个 cloud-build 复制到仓库内的情况
if not SRC_SWIPLET.exists():
    SRC_SWIPLET = ROOT / "cloud-build" / "swiplet" / "skip-chinese-ads-optimized.swiplet"
DST_SWIPLET = ROOT / "Swipt" / "Resources" / "BundledSkipAds.swiplet"
PLATFORM = ROOT / "Swipt" / "Platform" / "Platform.swift"

MARK = "// --- prebundle: install bundled swiplet on first launch ---"

INJECT = '''        // --- prebundle: install bundled swiplet on first launch ---
        // 首次启动时把 App 内置的优化版跳广告插件装进运行时目录，实现装完即用。
        // 用户在 App 内删除后不会再自动重装（用标记文件判断）。
        do {
            let fm = FileManager.default
            let swipletDir = SwipletStore.directory
            let id = "skip-chinese-ads"
            let installed = swipletDir.appendingPathComponent(id, isDirectory: true)
            let marker = swipletDir.appendingPathComponent(".prebundle-\\(id)-done")
            if !fm.fileExists(atPath: marker.path) && !fm.fileExists(atPath: installed.path) {
                if let bundled = Bundle.main.url(forResource: "BundledSkipAds", withExtension: "swiplet") {
                    let result = core.installSwiplet(bundled.path)
                    if result?.errorCode == LibSwiptSwipletErrorNone {
                        try? fm.createDirectory(at: swipletDir, withIntermediateDirectories: true)
                        try? Data(id.utf8).write(to: marker)
                        Self.logger.info("prebundle: installed skip-chinese-ads")
                    } else {
                        Self.logger.error("prebundle: install failed: \\(result?.errorMessage ?? "unknown", privacy: .public)")
                    }
                }
            }
        }
'''

def fail(msg: str):
    print(f"[prebundle] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

def main():
    if not SRC_SWIPLET.exists():
        fail(f"找不到插件文件: {SRC_SWIPLET}")
    if not PLATFORM.exists():
        fail(f"找不到 Platform.swift: {PLATFORM}")

    # 1) 复制插件为 bundle 资源
    DST_SWIPLET.parent.mkdir(parents=True, exist_ok=True)
    DST_SWIPLET.write_bytes(SRC_SWIPLET.read_bytes())
    print(f"[prebundle] 已写入资源: {DST_SWIPLET} ({DST_SWIPLET.stat().st_size} bytes)")

    # 2) 注入 Swift 代码
    src = PLATFORM.read_text(encoding="utf-8")
    if MARK in src:
        print("[prebundle] Platform.swift 已打过补丁，跳过注入")
        return

    anchor = "        let core = LibSwiptNewPlatform(options, events, deviceOptions, deviceEvents)!\n        self.core = core\n"
    if anchor not in src:
        fail("找不到注入锚点 (LibSwiptNewPlatform ... self.core = core)，Swift 源码结构可能已变化")
    new = anchor + "\n" + INJECT + "\n"
    PLATFORM.write_text(src.replace(anchor, new, 1), encoding="utf-8")
    print("[prebundle] 已注入首次启动预装逻辑到 Platform.swift")

if __name__ == "__main__":
    main()
