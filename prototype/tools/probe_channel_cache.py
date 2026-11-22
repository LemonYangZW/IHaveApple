"""量化 feed 缓存效果：冷启动 / 热启动 / 切频道。

用法：
    python -I tools/probe_channel_cache.py           # 先清缓存，测冷启动
    python -I tools/probe_channel_cache.py --keep     # 保留缓存，测热启动
"""
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QSettings       # noqa: E402

app = QCoreApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-probe")

import hgservice                                              # noqa: E402
from hgservice import HgService, CHANNELS, FEED_DIR           # noqa: E402

KEEP = "--keep" in sys.argv
if not KEEP and os.path.isdir(FEED_DIR):
    shutil.rmtree(FEED_DIR, ignore_errors=True)
    print("[probe] 已清空 feed 缓存\n", flush=True)

COLD = not os.path.isdir(FEED_DIR) or not os.listdir(FEED_DIR)


def wait_feed(svc, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if svc.status in ("ready", "empty"):
            break
        app.processEvents()
        time.sleep(0.01)
    return time.time() - t0


print(f"=== 启动（{'冷启动，无缓存' if COLD else '热启动，有缓存'}）===", flush=True)
ch = QSettings().value("feed/channel", "推荐", type=str)
svc = HgService()
svc.ensure_service()
t0 = time.time()
svc.load_async()
t = wait_feed(svc)
print(f"  {svc.channel} → 剧单就绪 {t:5.2f}s，{len(svc._dramas)} 部，推荐 {svc.recommendId}", flush=True)

print("\n=== 切频道（有缓存应 < 0.2s）===", flush=True)
for target in [c for c in CHANNELS if c != svc.channel]:
    before = svc.status
    t0 = time.time()
    svc.set_channel(target)
    t = wait_feed(svc, timeout=15)
    cached = "缓存" if t < 0.5 else "网络"
    print(f"  → {target:5s} {t:5.2f}s（{cached}）状态 {svc.status}，{len(svc._dramas)} 部", flush=True)

print("\n=== 等后台预热完成，再切一轮 ===", flush=True)
time.sleep(14)
for target in [c for c in CHANNELS if c != svc.channel]:
    t0 = time.time()
    svc.set_channel(target)
    t = wait_feed(svc, timeout=15)
    print(f"  → {target:5s} {t:5.2f}s  {len(svc._dramas)} 部", flush=True)

print("\n=== 模拟重启（新的服务实例读磁盘缓存）===", flush=True)
svc.shutdown()
svc2 = HgService()
svc2.ensure_service()
t0 = time.time()
svc2.load_async()
t = wait_feed(svc2)
print(f"  {svc2.channel} → 剧单就绪 {t:5.2f}s，{len(svc2._dramas)} 部", flush=True)
print(f"  缓存文件: {sorted(os.listdir(FEED_DIR)) if os.path.isdir(FEED_DIR) else '无'}", flush=True)
svc2.shutdown()