"""验收：首屏推荐（每次启动换一部）。

直接驱动 HgService，模拟多次启动：每次新建一个服务实例、拉 feed、看 recommendId。
QSettings 用来校验「不会连续两次推荐同一部」。

用法：python -I tools/verify_recommend.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QSettings      # noqa: E402

app = QCoreApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-recommend")

from hgservice import HgService                              # noqa: E402

FAILED = []


def check(cond, label, detail=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if detail else ""), flush=True)
    if not cond:
        FAILED.append(label)


picks = []
for i in range(8):
    svc = HgService()
    svc.ensure_service()
    svc._load()                      # 同步跑一次「启动加载」
    rid = svc.recommendId
    titles = {d["id"]: d["title"] for d in svc._dramas}
    picks.append(rid)
    print(f"  第 {i + 1} 次启动: {len(svc._dramas)} 部 → 推荐 {titles.get(rid, '?')}", flush=True)

check(len(set(picks)) > 1, "多次启动推荐不是同一部", f"{len(set(picks))} 种")
check(all(a != b for a, b in zip(picks, picks[1:])), "连续两次不会重复同一部", str(picks))
check(all(p for p in picks), "每次都能给出推荐")
all_ids = None
for p in picks:
    check(bool(p), f"推荐 id 非空 {p}")

# 推荐 id 必须能在剧单里解析到（否则播放页会回落第一部）
svc = HgService()
svc.ensure_service()
svc._load()
known = {d["id"] for d in svc._dramas}
check(svc.recommendId in known, "推荐 id 在剧单里存在", svc.recommendId)
check(len(svc._dramas) >= 5, "推荐池是整页 feed（上游单页 8–9 部，会浮动）", f"{len(svc._dramas)} 部")

# 首屏那部要能真的播（分集按需拉取）
eps = svc._fetch_episodes(svc.recommendId)
check(bool(eps) and len(eps) > 0, "推荐剧的分集可按需拉到", f"{len(eps)} 集")
d = next((x for x in svc._dramas if x["id"] == svc.recommendId), None)
check(d and d["total"] > 0, "推荐剧的集数来自 feed", f"{d['total'] if d else '?'} 集")
check(d and d["total"] == len(eps), "feed 集数与真实分集一致",
      f"feed={d['total'] if d else '?'} 实际={len(eps)}")

QSettings().clear()
svc.shutdown()
print("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"), flush=True)
sys.exit(0 if not FAILED else 1)