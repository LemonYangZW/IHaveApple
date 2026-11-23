import QtQuick
import IHaveApple 1.0
import "Fmt.js" as Fmt

// 播放界面：视频铺满整个窗口（窗口锁定 9:16，见 Main.qml），选集通过控件栏的「选集」按钮打开底部面板。
// 全屏时屏幕比例与视频不同，视频按高度撑满，两侧为黑色。
Rectangle {
    id: page

    property string dramaId: ""     // 空 = 取剧单第一部；剧 id 是 19 位字符串，不能用 int
    readonly property var drama: MockData.drama(dramaId)
    property int currentEp: 0
    property bool immersive: false
    property bool keysEnabled: true          // 搜索 / 历史面板打开时由 Main 关闭播放快捷键
    readonly property bool episodesOpen: sheet.open
    readonly property bool menuOpen: stage.menuOpen
    readonly property bool playing: stage.playing
    property bool started: false
    // 启动时还没决定播哪部（等剧单到达后按推荐定），见下面的 Connections
    property bool awaitingRecommend: false
    // 用户切了频道：等新频道的剧单到达后改播该频道的推荐
    property bool awaitingChannel: false
    // 频道没有内容（上游空数据时）
    readonly property bool channelEmpty: Backend.status === "empty"

    // 当前 dramaId 是否对应剧单里真实存在的剧（启动时 dramaId 可能是 0 / 空，代表「等推荐」）
    readonly property bool dramaKnown: {
        const list = MockData.dramas
        for (let i = 0; i < list.length; ++i)
            if (String(list[i].id) === String(dramaId)) return true
        return false
    }

    signal immersiveRequested(bool on)
    signal fitVideoRequested()          // 窗口按视频比例调整（由 Main 执行窗口几何变化）

    // 标题栏等窗口元素与播放控件同步显示 / 隐藏
    readonly property bool chromeShown: stage.awake || !stage.playing || sheet.open
    // Toast 底边距：选集面板打开时移到面板上方，避免挡住方格
    readonly property real toastMargin: sheet.open ? height - sheet.y + Theme.space.md : 120

    color: Theme.color.stage

    // ---------- 行为 ----------
    // 切换到另一部剧（启动时、或从搜索 / 历史中选择）；先保存当前剧的进度
    function open(id) {
        if (started) saveNow()
        started = true
        dramaId = String(id)
        dramaMode = false          // 换了一部剧就回到信息流模式
        sheet.open = false
        const known = dramaKnown
        const s = known ? startOf(dramaId) : { ep: 0, pos: 0 }
        const ep = s.ep, pos = s.pos
        currentEp = ep
        // 占位阶段（剧单未载入）不写进度，否则会多一条空记录
        // （进度不等于观看历史：进了全剧界面才进历史，见 onDramaModeChanged）
        if (known) Store.saveProgress(dramaId, ep, pos)
        // 只有「没指定剧」（0 / 空）才等推荐；--drama 3 这类明确指定不要被推荐覆盖
        else if (!(Number(dramaId) >= 1)) awaitingRecommend = true
        stage.episode = ep
        stage.start(pos)
        Qt.callLater(() => sheet.grid.showEpisode(ep, false))
        maybeLoadMore()          // 已经滑到推荐流末尾附近：先续一页，免得转圈回到第一部
    }
    // 打开一部剧时从哪里起播：有进度接着上次；上次已看到 95% 以上，从下一集开头开始
    function startOf(id) {
        const p = Store.progressOf(id)
        if (!p) return { ep: 0, pos: 0 }
        if (p.pos >= MockData.duration(id, p.ep) * 0.95 && p.ep + 1 < MockData.drama(id).total)
            return { ep: p.ep + 1, pos: 0 }
        return { ep: p.ep, pos: p.pos }
    }
    // 预载往上拖会依次看到的 5 个节目（第 8.3 节）：信息流里是剧单接下来 5 部（各自要起播的那一集），
    // 选集面板 / 本剧模式里是本剧接下来 5 集。当前这个起播后才开始，免得和它抢带宽；后端逐个落盘。
    // 当前这一集排在最前：没落盘时它是实时流，落盘后才能任意拖进度（已落盘的后端直接跳过）
    readonly property int preloadCount: 5
    function preloadAhead() {
        if (!dramaKnown || !drama) return
        const items = [[String(dramaId), currentEp]]
        if (sheet.open || dramaMode) {
            for (let k = 1; k <= preloadCount && currentEp + k < drama.total; ++k)
                items.push([String(dramaId), currentEp + k])
        } else {
            let id = String(dramaId)
            for (let k = 0; k < preloadCount; ++k) {
                id = neighborId(1, id)
                if (!id || id === String(dramaId)) break     // 剧单不足 5 部：转一圈就停
                items.push([id, startOf(id).ep])
            }
        }
        Backend.preload(items, Store.definition)
    }
    // 位置 / 模式 / 清晰度变了且当前这个已在播：重排预载队列
    readonly property string preloadKey: stage.phase !== "playing" ? ""
        : [dramaId, currentEp, sheet.open || dramaMode, Store.definition, Backend.feedIds.join(",")].join("|")
    onPreloadKeyChanged: if (preloadKey !== "") preloadAhead()
    // 剧单到达：把 dramaId 定为本次推荐的那部（stage.start 已按推荐解析，不会重复起播）
    Connections {
        target: Backend
        function onDramasChanged() {
            // 切频道后：新频道的剧单到了，播该频道的推荐
            if (page.awaitingChannel) {
                if (!Backend.recommendId) return      // 清空剧单那一拍，继续等
                page.awaitingChannel = false
                page.open(Backend.recommendId)
                return
            }
            if (!page.awaitingRecommend || !Backend.recommendId) return
            page.awaitingRecommend = false
            page.dramaId = String(Backend.recommendId)
            // 记下首屏这部剧的进度（stage 是本文档里的 id）
            Store.saveProgress(page.dramaId, page.currentEp, stage.position)
        }
    }
    function saveNow() {
        if (!dramaKnown) return                  // 占位阶段（剧单未到）不写进度
        if (stage.phase !== "ended") Store.saveProgress(dramaId, currentEp, stage.position)
    }

    function goTo(i) {
        if (!drama || i < 0 || i >= drama.total || i === currentEp || stage.animating) return
        heldAtEnd = false
        Store.saveProgress(dramaId, currentEp, stage.position)
        currentEp = i
        // 联动：视频滑动与选集方格的选框移动同时开始、同一曲线
        stage.transitionTo(i, 0)
        sheet.grid.showEpisode(i, sheet.open)
    }
    // 本集播完：自动连播；关闭自动连播时停在最后一帧，再按播放才进入下一集
    property bool heldAtEnd: false
    function onEpisodeFinished() {
        if (currentEp + 1 >= drama.total) { stage.phase = "ended"; return }
        if (Store.prefs.autoNext || heldAtEnd) { heldAtEnd = false; goTo(currentEp + 1); return }
        heldAtEnd = true
        stage.playing = false
        Store.toast("本集已播完，按播放继续下一集")
    }
    // 用户主动播放 / 暂停（快捷键、托盘菜单）：之后恢复窗口时不再自动改变播放状态
    function togglePlay() {
        pausedByMinimize = false
        stage.togglePlay()
    }
    // 最小化 / 隐藏到托盘时暂停（设置项）；恢复窗口时只恢复由此引起的暂停
    property bool pausedByMinimize: false
    function setMinimized(minimized) {
        if (minimized && Store.prefs.pauseOnMinimize && stage.playing) {
            stage.playing = false
            pausedByMinimize = true
        } else if (!minimized && pausedByMinimize) {
            stage.playing = true
            pausedByMinimize = false
        }
    }
    // 滚动 / 上下键的语义取决于「当前在哪」：
    //  - 信息流模式（默认）：在频道推荐流里换一部短剧
    //  - 本剧模式：翻本剧的上一集 / 下一集。进过选集面板就一直保持，
    //    直到点返回 / Esc、换剧、切频道或打开搜索 / 历史。第一集 / 最后一集再滚会被拦住。
    property bool dramaMode: false
    // 进了全剧界面（查看全集 / 选集）才算「在看这部剧」，记进观看历史；信息流里刷过的只记进度
    onDramaModeChanged: if (dramaMode && dramaKnown) Store.saveProgress(dramaId, currentEp, stage.position, true)
    function stepEpisodeOrDrama(dir) {
        if (!sheet.open && !dramaMode) {
            goDrama(dir)
            return
        }
        const total = drama ? drama.total : 0
        if (total <= 0) return
        const next = currentEp + dir
        if (next < 0 || next >= total) {
            // 到了第一集 / 最后一集：拦住，不换剧（要换剧先点返回回到信息流）
            Store.toast(next < 0 ? "已经是第 1 集了" : "已经是最后一集了")
            return
        }
        goTo(next)
    }
    // 画面上的滚轮：按设置可能是调音量
    function onWheel(dir) {
        if (Store.prefs.wheelAction === "volume") stepVolume(-dir)
        else stepEpisodeOrDrama(dir)
    }
    // 再点一次当前频道 tab：随机换一部（和「下一部」不同，避免总在原地打转）
    function showAnother() {
        const ids = Backend.feedIds
        if (!ids || ids.length < 2) return
        const start = Math.floor(Math.random() * ids.length)
        for (let k = 0; k < ids.length; ++k) {
            const id = String(ids[(start + k) % ids.length])
            if (id !== String(dramaId)) { open(id); return }
        }
    }
    // 离推荐流末尾还剩不到几部时，让后端续一页（服务端可以一直翻，见 hgservice._more）
    function maybeLoadMore() {
        if (!Backend.feedHasMore) return
        const ids = Backend.feedIds
        if (!ids || ids.length === 0) return
        let i = -1
        for (let k = 0; k < ids.length; ++k)
            if (String(ids[k]) === String(dramaId)) { i = k; break }
        if (i >= 0 && i >= ids.length - Backend.feedMoreAt) Backend.loadMore()
    }
    // 当前频道剧单里 from（默认当前这部）的上一部 / 下一部（循环）；没有可换的返回 ""
    function neighborId(dir, from) {
        const cur = String(from === undefined ? dramaId : from)
        const ids = Backend.feedIds
        if (!ids || ids.length < 2) return ""
        let i = 0
        for (let k = 0; k < ids.length; ++k)
            if (String(ids[k]) === cur) { i = k; break }
        const next = String(ids[(i + dir + ids.length) % ids.length])
        return next === cur ? "" : next
    }
    function neighborDrama(dir) {
        const id = neighborId(dir)
        return id ? MockData.drama(id) : null
    }
    // 拖动画卷翻过了一格：本剧模式翻集（切集动画从画卷当前位置续滑），信息流里画卷滑到邻居那部剧再换过去
    function onSwipe(dir) {
        if (sheet.open || dramaMode) { stepEpisodeOrDrama(dir); return }
        const next = neighborId(dir)
        if (next) stage.slideTo(dir, () => page.open(next))
    }
    // 在当前频道的剧单里换一部（循环）。集内切换交给自动连播和全剧界面。
    function goDrama(dir) {
        const next = neighborId(dir)
        if (!next || stage.animating) return
        if (Theme.reducedMotion) { open(next); return }
        switchFade.target = next
        switchFade.restart()
    }
    // 换剧的过渡：快速淡出 → 换片 → 淡入（比切集的滑动更轻，避免复用播放器池的位移）
    SequentialAnimation {
        id: switchFade
        property string target: ""
        NumberAnimation { target: stage; property: "opacity"; to: 0; duration: Theme.motion.fast }
        ScriptAction { script: page.open(switchFade.target) }
        NumberAnimation { target: stage; property: "opacity"; to: 1; duration: Theme.motion.base }
    }
    function stepVolume(dir) {
        Store.muted = false
        Store.volume = Math.max(0, Math.min(1, (Math.round(Store.volume * 20) + dir) / 20))
        Store.toast("音量 " + Math.round(Store.volume * 100) + "%")
    }
    function replay() {
        Store.saveProgress(dramaId, 0, 0)
        open(dramaId)
    }
    function closeEpisodes() { sheet.open = false }
    function toggleEpisodes() {
        if (!sheet.open) {
            sheet.grid.showEpisode(currentEp, false)
            dramaMode = true          // 进了选集就是「看这部剧」，滚轮从此翻集
        }
        sheet.open = !sheet.open
    }
    // Esc（由 Main 调用）：菜单 → 选集面板 → 全剧界面 → 退出沉浸，每次只执行一项
    function handleEscape() {
        if (stage.menuOpen) stage.closeMenus()
        else if (sheet.open) sheet.open = false
        else if (dramaMode) exitDramaView()
        else if (immersive) immersiveRequested(false)
    }
    function stepSpeed(dir) {
        const i = Math.max(0, Math.min(Store.speeds.length - 1, Store.speeds.indexOf(Store.speed) + dir))
        Store.speed = Store.speeds[i]
        Store.toast("倍速 " + Fmt.speed(Store.speed))
    }

    // 演示入口
    function demo(name) {
        if (name === "slow") stage.simulateSlowLoad()
        else if (name === "buffering") stage.simulateBuffering()
        else if (name === "error") stage.phase = "error"
        else if (name === "end") { stage.phase = "ended"; stage.playing = false }
        else if (name === "episodes") toggleEpisodes()
    }

    Timer {
        interval: 5000
        repeat: true
        running: stage.playing && stage.phase === "playing"
        onTriggered: Store.saveProgress(page.dramaId, page.currentEp, stage.position)
    }

    // 本集快结束时预解析下一集的播放地址（不下载内容）。
    // 条件：已经看了 ≥ 8 秒 → 快速滑动换集不会触发，避免把上游匿名额度烧光。
    property int prefetchCheckedFor: -1
    Timer {
        objectName: "prefetchTimer"
        interval: 1000
        repeat: true
        running: stage.playing && stage.phase === "playing"
        onTriggered: {
            if (stage.duration <= 0 || page.currentEp === page.prefetchCheckedFor) return
            if (stage.position < 8) return
            const remain = stage.duration - stage.position
            if (remain <= 0 || remain > Store.prefs.prefetchLead) return
            page.prefetchCheckedFor = page.currentEp
            if (page.currentEp + 1 < page.drama.total)
                Backend.prefetch(String(page.dramaId), page.currentEp + 1, Store.definition)
        }
    }

    // 换集 / 换剧时重置，让新的一集重新走一次检查
    onCurrentEpChanged: prefetchCheckedFor = -1

    // ---------- 舞台 ----------
    // 窗口宽高比，由 Main 传入（默认 9:16；打开「适配视频」后跟随视频源）
    property real aspect: 9 / 16
    property bool fitVideo: false

    // 频道无内容时盖住舞台（不显示旧频道的画面）
    Rectangle {
        anchors.fill: parent
        visible: page.channelEmpty
        color: Theme.color.stage
        z: 2
        Column {
            anchors.centerIn: parent
            spacing: Theme.space.sm
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                role: Theme.type.body
                text: "「" + Backend.channel + "」暂时没有内容"
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                role: Theme.type.caption
                color: Theme.color.aside
                text: "换个频道看看"
            }
        }
    }

    // 按比例完整显示（不裁剪画面）；窗口比例与片源一致时正好铺满
    Stage {
        id: stage
        objectName: "stage"
        height: Math.min(page.height, page.width / page.aspect)
        width: Math.min(page.width, height * page.aspect)
        anchors.centerIn: parent
        drama: page.drama
        immersive: page.immersive
        episodesOpen: sheet.open
        fitVideo: page.fitVideo
        dramaMode: page.dramaMode
        // 画卷上下邻居：信息流里是剧单的上一部 / 下一部，选集面板 / 本剧模式里是本剧上下集
        swipeDramas: !sheet.open && !page.dramaMode
        prevDrama: swipeDramas ? page.neighborDrama(-1) : null
        nextDrama: swipeDramas ? page.neighborDrama(1) : null
        onFinished: page.onEpisodeFinished()
        onWheelStep: dir => page.onWheel(dir)
        onSwipe: dir => page.onSwipe(dir)
        onToggleImmersive: page.immersiveRequested(!page.immersive)
        onToggleEpisodes: page.toggleEpisodes()
        onShowAllEpisodes: page.enterDramaView()
        onToggleFitVideo: page.fitVideoRequested()
        onReplay: page.replay()
    }

    EpisodeSheet {
        id: sheet
        x: stage.x
        width: stage.width
        height: Math.min(implicitHeight, stage.height * Theme.layout.episodeSheet)
        y: stage.y + stage.height - Theme.layout.controlsBar - height
        drama: page.drama
        currentEp: page.currentEp
        position: stage.position
        duration: stage.duration
        onPick: ep => page.goTo(ep)
    }

    // ---------- 全剧界面 ----------
    // 从底部信息区的「进入查看全剧」进入：就是本剧模式的播放界面——视频不中断、接着当前进度播，
    // 顶部频道 tab 换成「返回 + 剧名 + 集数」，滚轮 / ↑↓ 翻本剧上下集。返回或 Esc 回到信息流。
    function enterDramaView() {
        if (dramaMode) return
        dramaMode = true
        Store.toast("滚动切换上下集")
    }
    function exitDramaView() { dramaMode = false }

    // ---------- 键盘（第 6.1 节，按键可在设置页修改） ----------
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.playPause; onActivated: page.togglePlay() }
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.seekBack; onActivated: stage.seekTo(stage.position - 5) }
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.seekForward; onActivated: stage.seekTo(stage.position + 5) }
    // 上下键：与滚轮同语义（面板打开时翻集，否则换剧）
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.prevEpisode; onActivated: page.stepEpisodeOrDrama(-1) }
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.nextEpisode; onActivated: page.stepEpisodeOrDrama(1) }
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.episodes; onActivated: page.toggleEpisodes() }
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.fullscreen; onActivated: page.immersiveRequested(!page.immersive) }
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.mute; onActivated: Store.muted = !Store.muted }
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.speedDown; onActivated: page.stepSpeed(-1) }
    Shortcut { enabled: page.keysEnabled; sequence: Store.keys.speedUp; onActivated: page.stepSpeed(1) }
}
