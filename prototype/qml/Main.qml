import QtQuick
import QtQuick.Controls
import Qt.labs.platform as Platform
import IHaveApple 1.0

// 应用只有一个播放界面，视频铺满整个窗口。
// 窗口锁定 9:16：拖拽任意边或角都会按比例缩放，因此不会出现黑边。
// 「最大化」改为「适应屏幕高度」：按比例放大到屏幕可用高度并水平居中。
ApplicationWindow {
    id: win

    readonly property real designAspect: 9 / 16
    // 当前窗口宽高比：默认 9:16；打开「适配视频」后跟随视频源分辨率，
    // 这样横屏片源也能铺满窗口，不再上下留黑边
    readonly property real videoAspect: Player.videoWidth > 0 && Player.videoHeight > 0
                                        ? Player.videoWidth / Player.videoHeight
                                        : designAspect
    // 启动默认按片源比例（设置里可关闭）：竖屏 9:16 保持原样，横屏片源会把窗口拉成同样的比例
    property bool fitToVideo: true
    // 记住最近一次有效的片源比例：换集时视频尺寸会短暂归零，直接取 videoAspect 会让窗口跳一下
    property real appliedVideoAspect: designAspect
    readonly property real windowAspect: fitToVideo ? appliedVideoAspect : designAspect
    readonly property bool canFitToVideo: Player.videoWidth > 0 && Player.videoHeight > 0

    // 未指定 --size 时：高度取可用屏幕的 90%（最多 960），宽度按当前比例
    readonly property int autoHeight: Math.min(960, Math.round(Screen.desktopAvailableHeight * 0.9))
    width: launchWidth > 0 ? launchWidth : Math.round(autoHeight * windowAspect)
    height: launchHeight > 0 ? launchHeight : autoHeight
    minimumWidth: windowAspect >= 1 ? 427 : 360     // 横屏时不强制 360×640 的竖屏下限
    minimumHeight: windowAspect >= 1 ? 240 : 640
    visible: true
    title: player.drama ? player.drama.title + " - IHaveApple" : "IHaveApple"
    flags: Qt.Window | Qt.FramelessWindowHint | (Store.prefs.alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)
    color: Theme.color.stage
    font.family: Theme.font.ui

    property bool immersive: false
    readonly property bool shotMode: launchShot

    // ---------- 窗口尺寸 ----------
    property bool fitted: false
    property rect normalGeometry

    function setGeometry(x, y, w, h) {
        win.x = x; win.y = y; win.width = w; win.height = h
    }
    // 把锁定比例同步给原生窗口过程（Windows 上拖动边缘时按这个比例修正）。
    // QML 不直接引用 hook 对象：hook 要等窗口有 winId 才能创建，是 load 之后才存在。
    // 这里只发信号，由 main.py 接到 hook.set_aspect()。
    signal windowAspectRequested(real aspect)
    onWindowAspectChanged: windowAspectRequested(windowAspect)

    // 以窗口中心为基准，按新的宽高比重排尺寸（高度保持，超屏时按可用宽高压回）
    function applyAspect(a) {
        let h = Math.round(Math.min(Math.max(minimumHeight, height), Screen.desktopAvailableHeight))
        let w = Math.round(h * a)
        if (w > Screen.desktopAvailableWidth) {        // 超宽片源：以屏幕宽度为准
            w = Screen.desktopAvailableWidth
            h = Math.round(w / a)
        }
        if (w < minimumWidth) {
            w = minimumWidth
            h = Math.round(w / a)
        }
        const cx = x + width / 2
        const cy = y + height / 2
        setGeometry(Math.round(cx - w / 2), Math.round(cy - h / 2), w, h)
        fitted = false
    }
    // 窗口适配视频：把有画面的片源比例套到窗口上，让画面铺满、不留黑边
    function toggleFitToVideo() {
        if (immersive) setImmersive(false)       // 全屏下改窗口几何没有意义，先退出
        // fitToVideo 直接改：带 --size 启动时它与 prefs.fitWindow 不一致，只改 prefs 可能不发变化信号
        if (fitToVideo) {
            fitToVideo = false
            Store.prefs.fitWindow = false
            applyAspect(designAspect)
            Store.toast("窗口已恢复 9:16")
            return
        }
        if (!canFitToVideo) {
            Store.toast("还没有画面，无法按视频比例调整窗口")
            return
        }
        appliedVideoAspect = videoAspect
        fitToVideo = true
        Store.prefs.fitWindow = true
        applyAspect(videoAspect)
        Store.toast("窗口已适配视频比例 " + Math.round(videoAspect * 100) / 100 + ":1")
    }
    // 适配状态下换集，片源比例可能变（竖屏 ↔ 横屏），跟着重排一次。
    // 直接监听播放器信号并现读宽高：videoAspect / canFitToVideo 同样依赖这个信号，
    // 在 onVideoAspectChanged 里读 canFitToVideo 拿到的是重算前的旧值 —— 换集时尺寸归零那一下会被当成
    // 有效比例套成 9:16，新尺寸到达时反而被当成无效跳过，窗口就不再跟随片源
    Connections {
        target: Player
        function onVideoSizeChanged() {
            const vw = Player.videoWidth, vh = Player.videoHeight
            if (vw <= 0 || vh <= 0) return              // 尺寸还没拿到 / 正在换集，保持上一次的比例
            const a = vw / vh
            if (a === win.appliedVideoAspect) return
            win.appliedVideoAspect = a
            if (win.fitToVideo) win.applyAspect(a)
        }
    }

    // 设置页切换「按片源比例自动调整」：立刻按当前状态重排窗口
    // （控件栏的按钮走 toggleFitToVideo 自己会调，这里判定值没变就直接返回，避免重复重排）
    Connections {
        target: Store.prefs
        function onFitWindowChanged() {
            if (win.fitToVideo === Store.prefs.fitWindow) return
            win.fitToVideo = Store.prefs.fitWindow
            win.applyAspect(win.fitToVideo ? win.appliedVideoAspect : win.designAspect)
        }
    }

    // 说明：QML 只能拿到整个虚拟桌面的可用区域；C++ 正式版应使用 QScreen::availableGeometry()
    function toggleFit() {
        if (fitted) {
            setGeometry(normalGeometry.x, normalGeometry.y, normalGeometry.width, normalGeometry.height)
            fitted = false
            return
        }
        normalGeometry = Qt.rect(x, y, width, height)
        const h = Screen.desktopAvailableHeight
        const w = Math.round(h * windowAspect)
        setGeometry(Screen.virtualX + Math.round((Screen.desktopAvailableWidth - w) / 2), Screen.virtualY, w, h)
        fitted = true
    }
    // 按比例缩放：以拖动幅度更大的方向为准，另一边按当前比例计算；拖左 / 上边时保持对边不动
    function resizeLocked(edges, g, dx, dy) {
        const horiz = edges & (Qt.LeftEdge | Qt.RightEdge)
        const vert = edges & (Qt.TopEdge | Qt.BottomEdge)
        let w = g.width + (edges & Qt.RightEdge ? dx : 0) - (edges & Qt.LeftEdge ? dx : 0)
        let h = g.height + (edges & Qt.BottomEdge ? dy : 0) - (edges & Qt.TopEdge ? dy : 0)
        if (vert && (!horiz || Math.abs(h - g.height) * windowAspect >= Math.abs(w - g.width)))
            w = h * windowAspect
        else
            h = w / windowAspect
        h = Math.round(Math.max(minimumHeight, Math.min(h, Screen.desktopAvailableHeight)))
        w = Math.round(h * windowAspect)
        setGeometry(edges & Qt.LeftEdge ? g.x + g.width - w : g.x,
                    edges & Qt.TopEdge ? g.y + g.height - h : g.y, w, h)
    }

    // ---------- 关闭 / 托盘 ----------
    property bool quitting: false
    function hideToTray() {
        player.saveNow()
        win.hide()
        if (!Store.prefs.trayHintShown) {
            tray.showMessage("IHaveApple 已最小化到托盘", "单击托盘图标恢复窗口。在设置中可以改为关闭时退出程序。",
                             Platform.SystemTrayIcon.Information, 4000)
            Store.prefs.trayHintShown = true
        }
    }
    function showFromTray() {
        if (win.visibility === Window.Minimized || !win.visible) win.showNormal()
        win.raise()
        win.requestActivate()
    }
    function quitApp() {
        quitting = true
        player.saveNow()
        Qt.quit()
    }
    onClosing: close => {
        if (Store.prefs.closeAction === "tray" && tray.available && !quitting) {
            close.accepted = false
            hideToTray()
            return
        }
        player.saveNow()
    }

    function setImmersive(on) {
        if (immersive === on) return
        immersive = on
        if (shotMode) return                 // 截图模式保持窗口尺寸
        on ? showFullScreen() : showNormal()
    }

    function handleDemo(name) {
        if (name === "codec") {
            Store.quality = "720P"
            Store.toast("当前画质无法在这台电脑上播放，已切换到 720P。")
            return
        }
        player.demo(name)
    }

    // 启动参数：--drama 与 --page（演示状态）
    // 没传 --drama（=0）时首屏播本次推荐：MockData.drama() 会解析到 Backend.recommendId，
    // PlayerPage 在剧单到达后把 dramaId 定为那部（见 PlayerPage 的 Connections）
    Component.onCompleted: {
        Theme.reducedMotion = systemReducedMotion
        if (shotMode) Store.muted = true      // 截图模式静音
        // 启动：按片源比例决定窗口比例（默认开）；显式给了 --size 就尊重用户指定的尺寸
        fitToVideo = (launchWidth > 0 || launchHeight > 0) ? false : Store.prefs.fitWindow
        windowAspectRequested(windowAspect)
        player.open(launchDrama)
        switch (launchPage) {
        case "immersive": setImmersive(true); break
        case "offline": Store.offline = true; break
        case "end": case "error": case "episodes": Qt.callLater(() => player.demo(launchPage)); break
        case "search": case "history": Qt.callLater(() => library.show(launchPage)); break
        case "settings": settings.show(); break
        }
    }
    // 最小化或隐藏到托盘都视为「最小化」，由设置决定是否暂停
    onVisibilityChanged: player.setMinimized(win.visibility === Window.Minimized || win.visibility === Window.Hidden)

    // ---------- 视频（铺满窗口） ----------
    PlayerPage {
        id: player
        anchors.fill: parent
        immersive: win.immersive
        aspect: win.windowAspect
        fitVideo: win.fitToVideo
        // 输入剧名、打开设置页时不触发播放快捷键
        keysEnabled: library.mode !== "search" && !settings.open && !updateDialog.open
        onImmersiveRequested: on => win.setImmersive(on)
        onFitVideoRequested: win.toggleFitToVideo()
        // 选集面板、搜索 / 历史面板、设置页互斥
        onEpisodesOpenChanged: if (episodesOpen) { library.close(); settings.close() }
    }

    // 搜索 / 观看历史整页打开时暂停播放，关闭后恢复
    property bool pausedByLibrary: false

    // 整页面板（设置、搜索 / 历史）打开时隐藏频道 tab（全剧界面的顶栏同理），面板顶到标题栏下面。
    // 位置按「面板还看得见」算（含关闭时的滑出 / 淡出），免得关闭途中面板先往下跳一行
    readonly property bool panelShown: library.visible || settings.visible

    // 标题栏是透明叠层：面板打开时在它下面铺上和面板同色的底，别让画面从顶部透出来
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        height: library.y
        color: Theme.color.wing
        opacity: settings.open || library.open ? 1 : 0
        visible: opacity > 0 && !win.immersive
        Behavior on opacity { NumberAnimation { duration: Theme.reducedMotion ? 0 : Theme.motion.base } }
    }

    // ---------- 叠加层 ----------
    TitleBar {
        id: titleBar
        anchors.left: parent.left
        anchors.right: parent.right
        visible: !win.immersive && opacity > 0
        opacity: player.chromeShown || library.open || settings.open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.reducedMotion ? 0 : Theme.motion.base } }
        fitted: win.fitted
        panel: settings.open ? "settings" : library.mode
        onToggleFit: win.toggleFit()
        onSearch: library.toggle("search")
        onHistory: library.toggle("history")
        onSettings: settings.toggle()
    }
    // 顶部频道 tab：透明形式叠在画面上，和标题栏一起淡入淡出；全剧界面时换成 DramaBar。
    // 设置 / 搜索 / 历史打开时隐藏：那时在看面板，频道切换用不上
    ChannelBar {
        id: channelBar
        objectName: "channelBar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: titleBar.bottom
        visible: !win.immersive && !player.dramaMode && opacity > 0
        opacity: player.chromeShown && !library.open && !settings.open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.reducedMotion ? 0 : Theme.motion.base } }
        onPicked: ch => win.pickChannel(ch)
    }
    // 全剧界面顶栏：返回 + 剧名 + 集数，占频道 tab 那一行
    DramaBar {
        id: dramaBar
        objectName: "dramaBar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: titleBar.bottom
        visible: !win.immersive && player.dramaMode && opacity > 0
        opacity: channelBar.opacity
        drama: player.drama
        episode: player.currentEp + 1
        total: player.drama ? player.drama.total : 0
        onBack: player.exitDramaView()
    }
    OfflineBanner {
        id: banner
        anchors.left: parent.left
        anchors.right: parent.right
        y: titleBar.visible ? titleBar.height + (win.panelShown ? 0 : channelBar.height) : 0
        visible: Store.offline
    }

    // 切频道：后端换内容流，播放页等新剧单到达后播该频道的推荐
    // 再点一次当前频道：立刻换一部节目，同时后台再拉一批新的推荐
    function pickChannel(ch) {
        if (ch === Backend.channel) {
            player.showAnother()
            Backend.reshuffle()
            return
        }
        player.closeEpisodes()
        library.close()
        player.dramaMode = false      // 换频道 = 换内容流，回到信息流模式
        player.awaitingChannel = true
        Backend.set_channel(ch)
    }

    // 搜索 / 观看历史：从标题栏（及离线横幅）下方展开
    // 搜索 / 观看历史：整版页面，从标题栏（及离线横幅）下方铺到窗口底部，能一次显示更多结果
    LibraryPanel {
        id: library
        objectName: "libraryPanel"
        anchors.left: parent.left
        anchors.right: parent.right
        y: banner.y + (banner.visible ? banner.height : 0)
        height: win.height - y
        currentDrama: String(player.dramaId)
        onOpenChanged: {
            if (open) {
                player.closeEpisodes()
                settings.close()
                player.dramaMode = false      // 打开搜索 / 历史 = 想找别的剧，退出本剧模式
                // 整页盖住了画面，暂停播放（关闭时恢复）
                if (player.playing) { pausedByLibrary = true; player.togglePlay() }
            } else if (pausedByLibrary) {
                pausedByLibrary = false
                player.togglePlay()
            }
        }
        onPick: id => {
            library.close()
            // id 是 19 位字符串，比较时统一按字符串，避免类型不同误判成「另一部剧」
            if (String(id) !== String(player.dramaId)) player.open(id)
        }
    }

    // 设置页：盖住标题栏以下的整个窗口
    SettingsPage {
        id: settings
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.top: library.top
        trayAvailable: tray.available
        onOpenChanged: if (open) { player.closeEpisodes(); library.close() }
    }

    // 托盘图标：仅在「关闭窗口时 → 最小化到托盘」时显示
    Platform.SystemTrayIcon {
        id: tray
        visible: Store.prefs.closeAction === "tray"
        icon.source: Qt.resolvedUrl("../assets/icon.svg")
        tooltip: "IHaveApple · " + player.drama.title + " 第 " + (player.currentEp + 1) + " 集"
        onActivated: reason => {
            if (reason === Platform.SystemTrayIcon.Trigger || reason === Platform.SystemTrayIcon.DoubleClick)
                win.showFromTray()
        }
        menu: Platform.Menu {
            Platform.MenuItem {
                text: win.visible ? "隐藏窗口" : "显示窗口"
                onTriggered: win.visible ? win.hideToTray() : win.showFromTray()
            }
            Platform.MenuItem {
                text: player.playing ? "暂停" : "播放"
                onTriggered: player.togglePlay()
            }
            Platform.MenuItem {
                text: "下一集"
                onTriggered: player.goTo(player.currentEp + 1)
            }
            Platform.MenuSeparator {}
            Platform.MenuItem {
                text: "退出 IHaveApple"
                onTriggered: win.quitApp()
            }
        }
    }

    Shortcut { sequence: Store.keys.search; onActivated: library.show("search") }
    Shortcut { sequence: Store.keys.history; enabled: player.keysEnabled; onActivated: library.toggle("history") }
    Shortcut { sequence: Store.keys.settings; onActivated: settings.toggle() }
    // Esc 逐层关闭：倍速 / 画质菜单 → 设置页 / 搜索 / 历史面板 → 选集面板 → 全剧界面 → 沉浸模式。
    // 演示面板打开时让它自己处理 Esc（CloseOnEscape），避免与这里形成歧义快捷键。
    Shortcut {
        sequence: "Esc"
        enabled: !demo.opened
        onActivated: {
            if (updateDialog.open) updateDialog.close()
            else if (player.menuOpen) player.handleEscape()
            else if (settings.open) settings.close()
            else if (library.open) library.close()
            else player.handleEscape()
        }
    }

    // 更新提示：盖住整个窗口（含标题栏），视频在下面继续播放
    UpdateDialog {
        id: updateDialog
        anchors.fill: parent
        z: 90
        // 点过「稍后」的版本，本次运行内定时检查不再打扰；手动检查或出了更新的版本照常提示
        property string dismissed: ""
        onOpenChanged: if (!open) dismissed = Updater.latestVersion
    }
    Connections {
        target: Updater
        function onUpdateAvailable(manual) {
            if (manual || Updater.latestVersion !== updateDialog.dismissed) updateDialog.show()
        }
        function onToast(message) { Store.toast(message) }
        // 安装包已启动：退出播放器，把文件让给安装程序覆盖
        function onQuitRequested() { win.quitApp() }
    }
    // 启动后稍等再查（别和首屏拉剧单抢网络），之后每 6 小时查一次：
    // 播放器常常最小化到托盘一开好几天，只在启动时查会错过新版本
    Timer {
        interval: 5000
        repeat: true
        running: !win.shotMode && Store.prefs.autoCheckUpdate && Updater.canCheck
        onTriggered: {
            interval = 6 * 3600 * 1000
            Updater.check(false, Store.prefs.updateChannel)
        }
    }

    Toast {
        id: toast
        z: 100
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: player.toastMargin
    }
    Connections {
        target: Store
        function onToast(message) { toast.show(message) }
    }
    // 设置页「完全重置」：退出程序，退出后 main.py 清掉所有数据并重新打开（运行中清会被 Settings 写回）
    Connections {
        target: Backend
        function onResetRequested() { win.quitApp() }
    }

    // 仅原型：Ctrl+Shift+D 打开状态演示面板
    DemoPanel {
        id: demo
        onAction: name => win.handleDemo(name)
    }
    Shortcut { sequence: "Ctrl+Shift+D"; onActivated: demo.open() }

    // ---------- 无边框窗口：1px 边框 + 按比例缩放 ----------
    Rectangle {
        anchors.fill: parent
        z: 200
        color: "transparent"
        border.width: 1
        border.color: Theme.color.line
        visible: win.visibility === Window.Windowed
    }

    component ResizeEdge: MouseArea {
        property int edges
        property rect startGeometry
        property point startMouse
        z: 201
        enabled: win.visibility === Window.Windowed
        property bool systemResize: false
        onPressed: mouse => {
            win.fitted = false
            // Windows：由系统接管缩放，native_window.py 在 WM_SIZING 中保持 9:16，跟手且不掉帧
            systemResize = nativeAspectResize && win.startSystemResize(edges)
            if (systemResize) return
            startMouse = mapToGlobal(mouse.x, mouse.y)
            startGeometry = Qt.rect(win.x, win.y, win.width, win.height)
        }
        onPositionChanged: mouse => {
            if (!pressed || systemResize) return
            const p = mapToGlobal(mouse.x, mouse.y)
            win.resizeLocked(edges, startGeometry, p.x - startMouse.x, p.y - startMouse.y)
        }
    }
    readonly property int grip: 6
    ResizeEdge { edges: Qt.LeftEdge; cursorShape: Qt.SizeHorCursor; x: 0; y: win.grip; width: win.grip; height: win.height - win.grip * 2 }
    ResizeEdge { edges: Qt.RightEdge; cursorShape: Qt.SizeHorCursor; x: win.width - win.grip; y: win.grip; width: win.grip; height: win.height - win.grip * 2 }
    ResizeEdge { edges: Qt.TopEdge; cursorShape: Qt.SizeVerCursor; x: win.grip; y: 0; width: win.width - win.grip * 2; height: win.grip }
    ResizeEdge { edges: Qt.BottomEdge; cursorShape: Qt.SizeVerCursor; x: win.grip; y: win.height - win.grip; width: win.width - win.grip * 2; height: win.grip }
    ResizeEdge { edges: Qt.LeftEdge | Qt.TopEdge; cursorShape: Qt.SizeFDiagCursor; x: 0; y: 0; width: win.grip; height: win.grip }
    ResizeEdge { edges: Qt.RightEdge | Qt.BottomEdge; cursorShape: Qt.SizeFDiagCursor; x: win.width - win.grip; y: win.height - win.grip; width: win.grip; height: win.grip }
    ResizeEdge { edges: Qt.RightEdge | Qt.TopEdge; cursorShape: Qt.SizeBDiagCursor; x: win.width - win.grip; y: 0; width: win.grip; height: win.grip }
    ResizeEdge { edges: Qt.LeftEdge | Qt.BottomEdge; cursorShape: Qt.SizeBDiagCursor; x: 0; y: win.height - win.grip; width: win.grip; height: win.grip }
}
