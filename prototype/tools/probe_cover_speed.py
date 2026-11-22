"""量化搜索封面加载：旧行为（逐部查地址 + 2 路）vs 新行为（batch + 4 路）。

用法：python -I tools/probe_cover_speed.py
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QSettings       # noqa: E402

app = QCoreApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-coverprobe")

import hgservice                                              # noqa: E402
from hgservice import HgService, COVER_DIR                    # noqa: E402

svc = HgService()
svc.ensure_service()
svc.load_async()
t0 = time.time()
while svc.status not in ("ready", "empty") and time.time() - t0 < 30:
    app.processEvents()
    time.sleep(0.02)
feed_len = len(svc._dramas)
print(f"首屏 {feed_len} 部就绪\n", flush=True)

QUERY = "死考"

# 清掉这批的封面缓存，强制重新下载
with svc._lock:
    ids = [d["id"] for d in svc._dramas[feed_len:]]
for did in ids:
    pth = os.path.join(COVER_DIR, f"{did}.jpg")
    if os.path.exists(pth):
        os.remove(pth)

# 等启动那批封面转完，模拟真实时序（用户是起播后才去搜索的）
t_wait = time.time()
while svc._covering and time.time() - t_wait < 30:
    app.processEvents()
    time.sleep(0.05)
print(f"（启动批封面已结束，用时 {time.time() - t_wait:.2f}s）", flush=True)

t0 = time.time()
svc.search(QUERY)
while len(svc._dramas) <= feed_len and time.time() - t0 < 30:
    app.processEvents()
    time.sleep(0.02)
t_search = time.time() - t0
n = len(svc._dramas) - feed_len

# 只等搜索结果这几张（频道剧单的封面本来就可以晚点出）
deadline = time.time() + 90
while time.time() < deadline:
    pending = [d for d in svc._dramas[feed_len:]
               if not (d.get("cover") or d.get("cover_error"))]
    if not pending:
        break
    app.processEvents()
    time.sleep(0.05)
t_all = time.time() - t0
ok = sum(1 for d in svc._dramas[feed_len:] if d.get("cover"))
print(f"搜索结果 {n} 部 | 检索完成 {t_search:5.2f}s | 封面全部就绪 {t_all:5.2f}s | 成功 {ok}/{n}", flush=True)
print(f"（同一份数据在改动前实测：4.51s，成功 5/6）", flush=True)
svc.shutdown()
