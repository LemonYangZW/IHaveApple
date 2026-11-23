import QtQuick
import IHaveApple 1.0

// 舞台：视频表面池 + 播放控件 + 状态浮层。
// 池中固定 3 个表面（上一集 / 当前 / 下一集），切集时只平移 reel，不重建、不缩放（第 9 节）。
// 播放由 libmpv 驱动：position/duration/playing 全部来自 Player。
Rectangle {
    id: stage

    property var drama
    property int episode: 0
    property real position: 0
    property bool playing: true
    property string phase: "loading"   // loading | playing | buffering | error | ended
    property bool immersive: false
    property bool episodesOpen: false
    property bool fitVideo: false      // 窗口已按视频比例适配（工具栏按钮的选中态）
    property string errorReason: ""    // 最近一次播放失败的具体原因（空则用通用文案）
    property bool dramaMode: false     // 全剧界面（本剧模式）：底部不再显示「进入查看全剧」
    // 画卷上下邻居：信息流里是剧单的上一部 / 下一部（显示它们的封面），本剧模式里是本剧上下集
    property bool swipeDramas: false
    property var prevDrama: null
    property var nextDrama: null

    // 本地 SDK 没落盘时推的是实时流，mpv 的 duration 只是已下载的长度（领先播放位置约 20 秒、一直在涨），
    // 拿它当总长会让进度条比例不断变化 —— 点同一处落到不同时间。这时用剧集信息里的时长。
    // 剧集时长只精确到秒，可能比实际文件短几秒：已下载的超过它时说明文件更长，改用已下载的（否则结尾几秒被吞掉）；
    // 比实际文件长时进度走不到切集点，由 Player.onEnded 兜底
    readonly property real duration: {
        if (Player.seekable && Player.duration > 0) return Player.duration
        const known = drama ? Backend.durationOf(String(drama.id), episode) : 0
        if (known > 0) return Math.max(known, Player.duration)
        return Player.duration > 0 ? Player.duration : 90
    }
    readonly property bool animating: reelAnim.running || fadeAnim.running || slideAnim.running || settleAnim.running
    readonly property bool dragging: pointer.following
    readonly property bool menuOpen: controls.menuOpen
    function closeMenus() { controls.closeMenus() }

    signal finished()          // 当前集播完，由播放页决定下一步
    signal wheelStep(int dir)  // 滚轮：换短剧或调节音量（见设置）
    signal swipe(int dir)      // 拖动画卷翻过了一格：由播放页决定翻集还是换剧（不接则弹回）
    signal toggleImmersive()
    signal toggleEpisodes()
    signal showAllEpisodes()   // 底部「进入查看全剧」：进入全剧界面（本剧模式）
    signal toggleFitVideo()    // 窗口按当前视频比例调整尺寸
    signal replay()            // 全剧终后从第 1 集重看

    color: Theme.color.stage
    clip: true

    // ---------- 播放流程 ----------
    property int incoming: -1
    property int incomingDir: 1
    property real pendingPos: 0
    property bool slowLoad: false
    property bool waitingData: false   // 剧单还没载入，等 Backend.dramasChanged
    property bool awake: true
    // 换清晰度：保持原画面继续播，新地址到了再从原位置接着播
    property string activeQuality: Store.quality   // 当前画面实际的清晰度（切换失败时退回它）
    property bool qualityPending: false            // 已按新清晰度请求地址，等它到达后从当前位置接着播
    property bool switching: false                 // 已发起切换、新画面首帧还没到（期间不读进度，避免进度条跳回 0）
    property string currentUrl: ""                 // 播放器里正在播的地址
    property real startAt: 0                       // 这一集从第几秒起播（续播历史进度 / 重试）；0 = 从头
    property real seekPending: -1                  // 实时流上跳转：等落盘后从这里重新装载；-1 = 无
    readonly property bool controlsShown: (awake || !playing || episodesOpen) && phase !== "ended" && phase !== "error"
    // 出错 / 全剧终的浮层是实心遮罩，控件虽然隐藏，光标仍要可见 —— 否则鼠标落在黑色遮罩上就看不见了
    readonly property bool pointerVisible: controlsShown || phase === "error" || phase === "ended"

    // 向本地 SDK 请求这一集的播放地址；地址到达后由 onEpisodeReady 装载
    function start(pos) {
        // 先停掉旧节目：新地址要 3–8 秒才到，不停的话旧的会在封面底下继续播（出声）
        Player.stop()
        currentUrl = ""
        qualityPending = false
        seekPending = -1
        switching = false
        activeQuality = Store.quality
        position = pos || 0
        startAt = position >= 1 ? position : 0     // 不到 1 秒按从头播：免得为这点进度等落盘
        phase = "loading"
        slowLoad = false
        playing = true
        slowTimer.restart()
        if (!drama || String(drama.id) === "loading") {
            waitingData = true
            return
        }
        waitingData = false
        // 从中途起播要能 seek：后端会等这一集落盘再给地址（实时流只能从头播）
        Backend.prepare(String(drama.id), episode, Store.definition, false, startAt > 0)
        if (Store.prefs.titleCard) titleCard.show(episode)
    }

    // 地址就绪：装入播放器并请求起播（换清晰度 / 跳转时从对应位置接着播，并保持暂停状态）
    function loadUrl(url) {
        Player.setVolume(Store.volume)
        Player.setMute(Store.muted)
        Player.setSpeed(Store.speed)
        activeQuality = Store.quality
        const seekAt = seekPending
        if (qualityPending || seekAt >= 0) {
            qualityPending = false
            seekPending = -1
            // 换清晰度但实际还是同一路流（如「自动」与「1080P」都落在 1080p）：不必重载。
            // 跳转则一定要重载：地址相同，但这一集已落盘，再请求拿到的是能 seek 的文件
            if (seekAt < 0 && sameStream(url, currentUrl)) {
                switching = false
                return
            }
            // 换清晰度用此刻的位置而不是发起时的：等新清晰度落盘的几秒里原画面一直在播
            Player.load_url_at(url, seekAt >= 0 ? seekAt : Player.position)
        } else if (startAt > 0) {
            Player.load_url_at(url, startAt)
        } else {
            Player.load_url(url)
        }
        currentUrl = url
        if (playing) Player.play(); else Player.pause()
    }
    // strict 参数只影响 SDK 选哪档，不影响内容
    function sameStream(a, b) { return a.replace("&strict=1", "") === b.replace("&strict=1", "") }
    // 播放中换清晰度：不停当前画面，只按新清晰度重新取地址。
    // 用 strict：本地 SDK 默认缓存优先，这一集落过盘（开播几秒就会）就只返回缓存的那一档。
    // 后端会等新清晰度落盘再给地址（实时流不能 seek，接不上原位置）
    function switchQuality() {
        if (Store.quality === activeQuality) return        // 切换失败退回原清晰度时触发，无需重载
        if (!drama || String(drama.id) === "loading") return
        if (phase === "loading") {                          // 还没起播：直接按新清晰度取地址，旧请求的结果会被忽略
            activeQuality = Store.quality
            Backend.prepare(String(drama.id), episode, Store.definition, false, startAt > 0)
            return
        }
        if (phase !== "playing" && phase !== "buffering") return   // 出错 / 播完：重试或下一集时自然用新清晰度
        qualityPending = true
        switching = true
        Store.toast("正在切换到 " + Store.quality + "…")   // 新清晰度要先落盘，需要几秒，期间原画面继续播
        Backend.prepare(String(drama.id), episode, Store.definition, true, true)
    }
    function transitionTo(to, pos) {
        incoming = to
        incomingDir = to > episode ? 1 : -1
        pendingPos = pos || 0
        if (Theme.reducedMotion) {
            fadeAnim.start()
        } else {
            reelAnim.to = -incomingDir * height
            reelAnim.duration = remainDuration(reelAnim.to)   // 拖动松手时画卷已走了一段：只滑剩下的
            reelAnim.start()
        }
    }
    // 画卷滑到 to 剩下的时长：按剩余距离折算整段 motion.reel，最短 motion.fast
    function remainDuration(to) {
        return Math.max(Theme.motion.fast, Math.round(Theme.motion.reel * Math.abs(to - reel.y) / Math.max(1, height)))
    }
    // 画卷续滑到上 / 下一格，滑到后执行 action（信息流换剧：邻居显示的就是那部剧的封面，换完归位无缝）
    function slideTo(dir, action) {
        if (Theme.reducedMotion) { reel.y = 0; action(); return }
        slideAnim.action = action
        slideAnim.to = -dir * height
        slideAnim.duration = remainDuration(slideAnim.to)
        slideAnim.start()
    }
    // 没翻过去：弹回原位
    function settle() {
        if (reel.y === 0) return
        if (Theme.reducedMotion) { reel.y = 0; return }
        settleAnim.start()
    }
    // 那一侧有没有可翻到的邻居（没有时拖动带阻尼）
    function hasNeighbor(dir) {
        if (swipeDramas) return !!(dir > 0 ? nextDrama : prevDrama)
        const ep = episode + dir
        return !!drama && ep >= 0 && ep < drama.total
    }
    function commit() {
        episode = incoming
        reel.y = 0
        incoming = -1
        start(pendingPos)
    }
    function togglePlay() {
        if (phase !== "playing" && phase !== "buffering") return
        playing = !playing
        if (playing) Player.play(); else Player.pause()
    }
    function seekTo(sec) {
        const target = Math.max(0, Math.min(duration - 0.1, sec))
        position = target
        if (Player.seekable || !drama || (phase !== "playing" && phase !== "buffering")) {
            Player.seek(target)
            return
        }
        // 实时流只能顺着播，超出已下载部分的 seek 会失败（进度条弹回原处）。
        // 改为等这一集落盘（开播几秒 SDK 就会落盘，通常已经好了）后从目标位置重新装载，期间原画面继续播
        const inFlight = seekPending >= 0
        seekPending = target
        switching = true                 // 期间不读播放器进度，进度条停在目标位置
        if (!inFlight) Backend.prepare(String(drama.id), episode, Store.definition, false, true)
    }
    function wake() { awake = true; idleTimer.restart() }

    // 演示：慢网首帧 / 缓冲
    function simulateSlowLoad() { start(position); loadTimer.interval = 2500; loadTimer.restart() }
    function simulateBuffering() { phase = "buffering"; bufferTimer.restart() }

    Timer { id: slowTimer; interval: 500; onTriggered: stage.slowLoad = true }
    Connections {
        target: Player
        function onReady() {
            stage.switching = false
            if (stage.phase === "loading") stage.phase = "playing"
        }
        // 播到文件末尾。通常进度先走到结尾、由 tick 切下一集；这里兜底总时长比实际文件略长的情况
        function onEnded() {
            if (!stage.playing || stage.animating || stage.switching) return
            if (stage.phase !== "playing" && stage.phase !== "buffering") return
            stage.position = stage.duration
            stage.finished()
        }
    }
    // 设置变化实时同步到播放器（之前只在装载新一集时下发，播放中改了不生效）
    Connections {
        target: Store
        function onMutedChanged() { Player.setMute(Store.muted) }
        function onVolumeChanged() { Player.setVolume(Store.volume) }
        function onSpeedChanged() { Player.setSpeed(Store.speed) }
        function onQualityChanged() { stage.switchQuality() }
    }
    Connections {
        target: Backend
        function onDramasChanged() {
            if (stage.waitingData) {
                stage.waitingData = false
                stage.start(stage.position)
            }
        }
    }
    Connections {
        target: Backend
        function onEpisodeReady(dramaId, ep, url, definition) {
            if (!stage.drama || String(stage.drama.id) !== String(dramaId)) return
            if (ep !== stage.episode) return
            if (definition !== Store.definition) return     // 换清晰度前发出的旧请求
            stage.loadUrl(url)
        }
        function onEpisodeFailed(dramaId, ep, reason, definition) {
            if (!stage.drama || String(stage.drama.id) !== String(dramaId)) return
            if (ep !== stage.episode) return
            if (definition !== Store.definition) return
            if (stage.seekPending >= 0) {                    // 跳转前没等到落盘：原画面还在播，进度条回到实际位置
                stage.seekPending = -1
                stage.switching = false
                Store.toast("这一集还没缓存好，稍后再拖动进度")
                return
            }
            if (stage.qualityPending) {                      // 换清晰度失败：原画面还在播，退回原清晰度
                stage.qualityPending = false
                stage.switching = false
                Store.toast("切换到 " + Store.quality + " 失败，继续以 " + stage.activeQuality + " 播放")
                Store.quality = stage.activeQuality
                return
            }
            stage.errorReason = reason || ""
            stage.phase = "error"
        }
    }
    Timer { id: bufferTimer; interval: 2500; onTriggered: if (stage.phase === "buffering") stage.phase = "playing" }
    Timer {
        id: tick
        interval: 100
        repeat: true
        running: stage.visible && stage.playing && !stage.animating
                 && (stage.phase === "playing" || stage.phase === "buffering")
        onTriggered: {
            if (Store.offline) { stage.phase = "buffering"; return }
            if (stage.phase === "buffering") { if (!bufferTimer.running) stage.phase = "playing"; return }
            if (stage.switching) return
            stage.position = Player.position
            // 播完由播放器 eof/idle 驱动：position 走到结尾即切下一集
            if (stage.duration > 0 && stage.position >= stage.duration - 0.4) {
                stage.position = stage.duration
                stage.finished()
            }
        }
    }
    // 仅原型：模拟真实视频的逐帧重绘（30fps）。翻转一个 1px 色块迫使窗口每帧渲染，画面上看不出来
    Timer {
        interval: 33
        repeat: true
        running: Store.simulateFrames && stage.playing && stage.visible
        onTriggered: frameProbe.flip = !frameProbe.flip
    }
    Rectangle {
        id: frameProbe
        property bool flip: false
        z: 1
        width: 1; height: 1
        color: flip ? "#010101" : "#000000"
        visible: Store.simulateFrames
    }
    Timer {
        id: idleTimer
        interval: Store.prefs.controlsIdle
        onTriggered: if (!controls.menuOpen && !controlsHover.hovered) stage.awake = false
    }

    // ---------- 视频表面池 ----------
    Item {
        id: reel
        objectName: "reel"
        width: stage.width
        height: stage.height

        // 切集过渡中（含信息流里的自动连播）邻居一律是要切到的那一集
        VideoSurface {
            y: -stage.height
            width: stage.width; height: stage.height
            drama: stage.incoming < 0 && stage.swipeDramas ? stage.prevDrama : stage.drama
            episode: stage.incoming >= 0 && stage.incomingDir < 0 ? stage.incoming
                   : stage.incoming < 0 && stage.swipeDramas ? 0 : stage.episode - 1
            showCover: true
        }
        VideoSurface {
            width: stage.width; height: stage.height
            drama: stage.drama
            episode: stage.episode
            position: stage.position
            live: true
            showCover: stage.phase === "loading"
        }
        VideoSurface {
            y: stage.height
            width: stage.width; height: stage.height
            drama: stage.incoming < 0 && stage.swipeDramas ? stage.nextDrama : stage.drama
            episode: stage.incoming >= 0 && stage.incomingDir > 0 ? stage.incoming
                   : stage.incoming < 0 && stage.swipeDramas ? 0 : stage.episode + 1
            showCover: true
        }
    }
    // 减少动画：交叉淡入
    VideoSurface {
        id: fadeSurface
        width: stage.width; height: stage.height
        drama: stage.drama
        episode: stage.incoming
        showCover: true
        opacity: 0
        visible: opacity > 0
    }

    NumberAnimation {
        id: reelAnim
        target: reel
        property: "y"
        duration: Theme.motion.reel
        easing.type: Easing.BezierSpline
        easing.bezierCurve: Theme.motion.reelCurve
        onFinished: stage.commit()
    }
    NumberAnimation {
        id: slideAnim
        property var action
        target: reel
        property: "y"
        easing.type: Easing.BezierSpline
        easing.bezierCurve: Theme.motion.reelCurve
        onFinished: {
            const a = action
            action = null
            a()
            reel.y = 0
        }
    }
    NumberAnimation {
        id: settleAnim
        target: reel
        property: "y"
        to: 0
        duration: Theme.motion.base
        easing.type: Easing.BezierSpline
        easing.bezierCurve: Theme.motion.baseCurve
    }
    SequentialAnimation {
        id: fadeAnim
        NumberAnimation { target: fadeSurface; property: "opacity"; from: 0; to: 1; duration: Theme.motion.crossfade }
        ScriptAction { script: stage.commit() }
        PropertyAction { target: fadeSurface; property: "opacity"; value: 0 }
    }

    // ---------- 鼠标：单击暂停 / 双击全屏 / 滚轮切集 / 拖动画卷 / 静止隐藏控件 ----------
    MouseArea {
        id: pointer
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: following ? Qt.ClosedHandCursor : stage.pointerVisible ? Qt.ArrowCursor : Qt.BlankCursor
        property real wheelAccum: 0
        // 按住上下拖动：画卷跟手。松手时拖过 layout.swipe、或快速甩过（≥ layout.swipeVelocity）就续滑到上 / 下一个，
        // 否则弹回。上拖 = 下一个（同往下滚）。移动超过系统拖动阈值就算拖动，不再触发单击暂停
        property point pressAt
        property bool dragged: false
        property bool following: false     // 越过阈值时以纵向为主：画卷跟手
        property real lastY: 0
        property real lastT: 0
        property real velocity: 0          // 逻辑像素 / 毫秒，向下为正

        onPressed: mouse => {
            pressAt = Qt.point(mouse.x, mouse.y)
            dragged = following = false
            velocity = 0
            lastY = mouse.y
            lastT = Date.now()
        }
        onPositionChanged: mouse => {
            stage.wake()
            if (!pressed) return
            const dx = mouse.x - pressAt.x, dy = mouse.y - pressAt.y
            if (!dragged && Math.hypot(dx, dy) > Qt.styleHints.startDragDistance) {
                dragged = true
                following = !stage.animating && Math.abs(dy) >= Math.abs(dx)   // 方向在越过阈值时定下
            }
            if (!following) return
            const now = Date.now()
            if (now > lastT) velocity = 0.6 * (mouse.y - lastY) / (now - lastT) + 0.4 * velocity
            lastY = mouse.y
            lastT = now
            // 那一侧没有可翻的（首尾集 / 剧单只有一部）：带阻尼，只跟三分之一
            const free = stage.hasNeighbor(dy < 0 ? 1 : -1)
            reel.y = Math.max(-stage.height, Math.min(stage.height, free ? dy : dy / 3))
        }
        onReleased: mouse => {
            if (!following) return
            following = false
            const dy = mouse.y - pressAt.y
            if (Date.now() - lastT > 100) velocity = 0     // 停住再松手不算甩
            const flick = Math.abs(velocity) >= Theme.layout.swipeVelocity && (velocity < 0) === (dy < 0)
            if (Math.abs(dy) >= Theme.layout.swipe || flick) {
                stage.swipe(dy < 0 ? 1 : -1)
                if (!stage.animating) stage.settle()      // 播放页没翻（首尾拦截等）：弹回
            } else {
                stage.settle()
            }
        }
        onCanceled: { following = false; stage.settle() }
        onEntered: stage.wake()
        onClicked: if (!dragged) clickTimer.restart()
        onDoubleClicked: { clickTimer.stop(); stage.toggleImmersive() }
        onWheel: wheel => {
            if (stage.animating) { wheelAccum = 0; return }
            // 鼠标滚轮每格 120；触控板惯性滚动按像素累计，超过 120 才切一集
            wheelAccum += wheel.pixelDelta.y !== 0 ? wheel.pixelDelta.y : wheel.angleDelta.y
            if (Math.abs(wheelAccum) >= 120) {
                stage.wheelStep(wheelAccum < 0 ? 1 : -1)
                wheelAccum = 0
            }
            wheelReset.restart()
        }
        Timer { id: wheelReset; interval: 300; onTriggered: pointer.wheelAccum = 0 }
        Timer { id: clickTimer; interval: 250; onTriggered: stage.togglePlay() }
    }

    // ---------- 浮层 ----------
    // 位于标题栏下方，避免与标题栏重叠
    TitleCard {
        id: titleCard
        x: Theme.space.lg
        y: Theme.layout.titleBar + Theme.space.xs
    }

    LoadingRing {
        anchors.centerIn: parent
        visible: (stage.phase === "loading" && stage.slowLoad) || stage.phase === "buffering"
    }

    // 暂停时画面中央的播放按钮：半透明圆底 + 三角，点一下继续播放。
    // 只做单次淡入淡出、不做循环动画 —— 第 10 节要求「暂停且无交互时窗口 MUST NOT 重绘」。
    Rectangle {
        id: centerPlay
        objectName: "centerPlayButton"
        readonly property bool shown: !stage.playing && stage.phase === "playing"
        anchors.centerIn: parent
        width: Theme.layout.centerPlay
        height: width
        radius: width / 2
        color: Theme.color.stage60
        border.width: 1
        border.color: Theme.color.subtitle30
        opacity: shown ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.reducedMotion ? 0 : Theme.motion.base } }
        Accessible.name: "播放"
        Accessible.role: Accessible.Button
        Icon {
            anchors.centerIn: parent
            glyph: Theme.icon.play
            size: Math.round(parent.width * 0.34)
            color: Theme.color.subtitle
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.ArrowCursor
            onClicked: stage.togglePlay()
            HoverHandler { onHoveredChanged: if (hovered) stage.wake() }
        }
    }

    // 播放失败：遮罩盖住最后一帧，避免和画面内容混在一起
    Rectangle {
        anchors.fill: parent
        visible: stage.phase === "error"
        color: Theme.color.scrim
    }
    Column {
        anchors.centerIn: parent
        width: parent.width - Theme.space.xl
        visible: stage.phase === "error"
        spacing: Theme.space.md
        Label {
            width: parent.width
            role: Theme.type.body
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            text: stage.errorReason !== "" ? stage.errorReason
                                           : "这一集没能播放。网络连接已断开，检查网络后重试。"
        }
        IhaButton {
            anchors.horizontalCenter: parent.horizontalCenter
            variant: "primary"
            iconGlyph: Theme.icon.refresh
            text: "重试"
            onClicked: stage.start(stage.position)
        }
    }

    EndScreen {
        anchors.fill: parent
        visible: stage.phase === "ended"
        drama: stage.drama
        onReplay: stage.replay()
    }

    // 底部信息区：剧名 + 简介 + 集数 + 查看全集（常驻，不随控件淡出）
    DramaInfo {
        id: dramaInfo
        objectName: "dramaInfo"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: controls.top
        drama: stage.drama
        episode: stage.episode + 1
        total: stage.drama ? stage.drama.total : 0
        z: 2
        transform: Translate { y: reel.y }   // 剧名属于这一格画面：跟着画卷一起走
        inDramaView: stage.dramaMode
        onShowAll: stage.showAllEpisodes()
    }

    PlayerControls {
        id: controls
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        // 隐藏时彻底不参与合成（第 9 节第 3 条）
        opacity: stage.controlsShown ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.reducedMotion ? 0 : Theme.motion.base } }

        playing: stage.playing
        position: stage.position
        duration: stage.duration
        immersive: stage.immersive
        episodesOpen: stage.episodesOpen
        fitVideo: stage.fitVideo
        onTogglePlay: stage.togglePlay()
        onSeek: s => stage.seekTo(s)
        onToggleImmersive: stage.toggleImmersive()
        onToggleEpisodes: stage.toggleEpisodes()
        onToggleFitVideo: stage.toggleFitVideo()

        HoverHandler { id: controlsHover; onHoveredChanged: if (hovered) stage.wake() }
    }
}
