# 坑点与经验

这份文件记录**踩过的坑、验证过的结论、以及绕路的原因**。目标只有一个：下次遇到同一形状的问题，别再从零试一遍。

写法约定：`症状` → `根因` → `对策/判据`。凡是「实测」的结论都标了日期和测法，方便以后判断是否已失效。

---

## 一、取流协议（红果 / 番茄）

### 1. 服务端回 `HTTP 200` + 空体 = 签名或参数不一致

- **症状**：`/novel/player/multi_video_model/player/v1` 返回 200，body 长度 0，没有任何错误码。
- **根因**：`x-medusa` 的消息体与服务端重新计算的摘要不一致。POST 请求的摘要必须同时覆盖**查询串**和**body 的 MD5**，只签查询串一定空体。
- **对策**：签名时把实际发出的 query 与 gzip 后的 body 一起算进 `f13` 摘要，并带上 `x-ss-stub = upper(md5(body))`。改 `_rticket` 拿到"支持的摘要变体"再封包（见 `sdk/openhongguo/internal/protocol/sign/videotab.go` 的 `signSealed`）。
- **判据**：空体不要去查网络/证书/DNS，先自查签名输出。

### 2. 官方客户端真正调用的端点是「播放器端点」，不是 `video_tab`

- **症状**：v0.1.14 只能靠 `GET /reading/bookapi/video_tab/multi_video_model/v1/` 取流，被当成"预览码阶"。
- **根因**：`video_tab` 是信息流预览接口（参考第三方客户端反推的），官方播放页走的是 `POST /novel/player/multi_video_model/player/v1`（另有 `preload/v1`）。两条路**码阶完全相同**（2026-11-26 实测同集对比），差别只在报文形状。
- **对策**：首选播放器端点，`video_tab` 降为回退；host 用 `reading.snssdk.com` 或 `api5-normal-sinfonlinea.fqnovel.com` 都可以（两端都实测通）。

### 3. `device_level` 不影响码阶；`bytevc2` 只跟片源有关

- **症状**：历史注释称「`device_level=3` 会把 1080p 以下换成 bytevc2，mpv 解不了」，因此固定用 1。
- **实测（2026-11-26）**：用播放器端点把 `device_level` 1/2/3/4 全跑一遍，**下发的码流完全一致**；`bytevc2` 出现与否取决于这一集有没有 H.266 转码产物。
- **对策**：维持 `device_level=1`，但别再把 bytevc2 归咎于它；解码能力问题去查 mpv/ffmpeg 支不支持 vvc。

### 4. 「1080p」不一定是 1080p

- **症状**：以为取到了 1080p。
- **实测**：某些剧的 `1080p` 档实际是 `1280×720`，只是码率更高（如 543/664 kbps vs 720p 档 451/525 kbps）。
- **对策**：判断质量看 `bitrate` + 实际 `vwidth/vheight`，别只看 `definition` 标签。

### 5. 各剧码阶差异极大，别拿一部剧的数值当基准

- 竖屏短剧：`1080p` ≈ 665 kbps / 8.66 MB per 103 s（这就是内容上限，不是取低了）。
- 横屏内容：`1080p` ≈ 1.27 Mbps / 33.6 MB，且 720p 及以下可能是 bytevc2。
- **对策**：怀疑"画质差"时先量同一集的完整码阶，再和官方对比，别先改代码。

### 6. 上游会拒「用过的设备」

- **症状**：某些集忽然空体，换新设备档案就好。
- **对策**：缓存优先（已落盘的集不依赖上游）；`withFreshDevice` 在客户端侧换身份重试。

---

## 二、真机取证

### 7. MITM 抓不到 TTNet 的 API 域（不要在这上面硬磨）

- **症状**：`api5-*.fqnovel.com`、`mon11-misc.fqnovel.com` 握手阶段被拒（`certificate unknown`）。
- **根因**：`apk-mitm` 之类只能改 Java 层（`AndroidNetworkLibrary.verifyServerCertificates` 打成恒成功）；真正拦人的是 `libsscronet.so` / `libttboringssl.so` 里 BoringSSL 的 custom verify 回调，网络配置里加信任证书没用。
- **曾试过且失败的**：替换 `SSL_CTX_set_custom_verify` 回调、`X509_verify_cert`/`SSL_get_verify_result` 置成功 —— 钩子能挂上，但 TTNet 的 `SSL_CTX` 在 App 初始化时已建好；改用 gadget `on_load=wait` 抢在建立之前，App 又因反 Hook 自检直接退出。
- **对策**：真机请求走 **logcat**（见下条）。

### 8. App 自己会把真机报文打全，logcat 是最省的一手证据

实测有用的 tag：

| tag | 内容 |
|---|---|
| `Net-ResponseHandleInterceptor` / `CAPURL` | 完整请求 URL（含全部 query、`_rticket`、`klink_egdi`） |
| `ShortPlayer_*` / `ResolutionManager` | 播放决策（`getResolution resolution:720p`、`getPreloadResolution`） |
| `ttmn ... av_formater_android` | 解复用实测码率（`bitrate is:423641`） |
| `TrafficMonitor(V3)` | 每个请求的字节数 |

**判据**：想确认"官方到底拿什么质量"，`getResolution` + `bitrate is:` 两行就够，不需要解密任何流量。

### 9. 改包取证与"官方版可更新"是冲突的，用 Android 多用户绕开

- **症状**：改签后的同包名 App 装上后，应用商店再想装官方版会 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`。
- **对策**：官方版留在 `user 0`；抓包/改签包装进另一个 Android 用户（`pm create-user cap` + `adb install --user 10`）。同包名可以并存，签名互不干扰。
- **收尾**：结束取证后 `adb uninstall --user 10` 把改签包清掉，平板上只剩原厂签名。

### 10. MIUI 会挡 `adb install`

- **症状**：`INSTALL_FAILED_USER_RESTRICTED: Install canceled by user`。
- **根因**：开发者选项里的「USB 安装」未开启（部分机型要求登录小米账号 + 插 SIM），不是你点错了。
- **对策**：`adb push` 到 `/sdcard/Download/`，让用户在文件管理器里点安装；或用应用商店。验证签名用 `adb pull` 回来的 `base.apk` 跑 `apksigner verify --print-certs`（`dumpsys` 里那个短哈希对不上证书 SHA-1，别用它比对）。

### 11. git-bash 会把 `/sdcard/...` 当成本地路径改写

- **症状**：`adb push x.apk /sdcard/Download/x.apk` 报 `remote secure_mkdirs() failed`，路径变成了 `D:/ScoopApps/.../sdcard/...`。
- **对策**：命令前加 `MSYS_NO_PATHCONV=1`。

### 12. apktool 重打包签名用 debug keystore，不用猜自建库密码

- 历史 `cap.keystore` 密码未知（`keystore password was incorrect`），直接用 `~/.android/debug.keystore`（别名 `androiddebugkey`，口令 `android`）即可。

---

## 三、播放与缓存

### 13. 缓存按清晰度分档，不能"有哪档发哪档"

- **症状**：同一集永远只有 720p；或某些集点开就报错。
- **根因**：`cachedDefinition` 会在请求档未落盘时**回退到任意已缓存档**（含更低档）→ 既降质又再也不去取高码率，且下游可能拿到早已失效的地址。
- **对策**：只认请求的那一档（`exactCached`），未落盘就向上游解析；**只有上游失败时**才退回已缓存档做离线兜底。
- **实测**：只落 720p 时请求 1080p，修复后返回 `definition=1080p, cached=false`。

### 14. 播放地址有生命期，必须按 `expires_at` 过期重解

- **症状**：长会话里点开某一集直接报错（CDN 403）。
- **根因**：播放器把解析到的 `stream_url` 永久存在内存里。
- **对策**：记录 `expires_at`，留 90 s 余量，过期即丢弃重解（`hgservice._url_expired`）。

### 15. 缓存落盘的原子性靠 `.part` + `rename`

- `fillCache` 写 `xxx.mp4.part`，成功后 `os.Rename` 到正式名；被中断只会剩 `.part`，不会出现"半截 mp4 被当成已缓存"。
- **注意**：`cacheReady` 只判 `> 32 KB`，很弱。若要更稳，可加 ffprobe 校验或完成标记。

### 16. `ohgd` 只转封装、不转码

- `ffmpeg -c copy -decryption_key ... -movflags +faststart`，画质不损失；解码在 mpv 侧进行，所以 **bytevc2 能不能播取决于 libmpv 的 ffmpeg 是否带 vvc 解码器**（本机系统 ffmpeg 8.1.1 有 `vvc`，不代表 libmpv 也有）。

### 17. 打包版把 `ohgd` 的 stdout 丢掉，必须落文件日志

- `hgservice` 用 `stdout=DEVNULL` 拉起 `ohgd`，出问题只剩一个弹窗。
- **对策**：`ohgd -log`（默认 `<cache>/ohgd.log`，超过 2 MB 轮转一次），取流失败写 `集号 / 清晰度 / 错误原文`。

### 18. Qt Quick 渲染线程里不要跑 Python

- **症状**：播放时拖动窗口一顿一顿、画面掉帧；暂停时不卡。
- **根因**：自定义 `QQuickItem.updatePaintNode` 在**渲染线程的 sync 阶段**执行，需要 GIL；GUI 线程在 sync 期间整段阻塞，任何 Python 线程占着 GIL 都会把这段拉长（实测只多一个忙线程，sync 从 ~0 ms 涨到 16 ms）。
- **对策**：改成 `QQuickImageProvider` + `Image`（`qml/VideoFrame.qml`），取帧在 GUI 线程、纹理上传交给 C++，渲染线程上不执行任何 Python。

---

## 四、排查方法与习惯

### 19. 先量，再改

本次有三条"看起来对"的假设都被实测推翻：`device_level` 影响码阶、「走 video_tab 所以画质差」、「官方有更高档位」。**每条都先写脚本量出来，再决定改什么**。

### 20. 批量采样能快速把问题分到"取流侧"还是"播放侧"

- 采样器（临时放在 `.repro/scan*`，不入库）：拉推荐流/搜索结果 → 逐集 `ResolvePlayback` + `ContentKey` → 归类 `ok / drm-key / login-required / hls-or-dash-only / empty-model / timeout`。
- 结论示例：某剧 103 集 + 第二季 129 集 + 超长剧 1000 集**全部取流成功**，说明故障在播放侧，别再去调签名。

### 21. 取证留痕，但别入库

`.repro/` 放抓包、临时 APK、探针程序（已进 `.gitignore`）。结论写进本文件与 `CHANGELOG.md`，代码里只留必要注释。

### 22. 结论要写"为什么"和日期

`CHANGELOG.md` 记对外行为变化，本文件记内部机理与判据。凡是写着"实测"的，都注明日期，方便下次服务端行为变化时快速定位哪些结论过期了。
