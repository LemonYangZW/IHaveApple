pragma Singleton
import QtQuick
import QtCore
import IHaveApple 1.0

// 可变的播放状态：观看进度、播放设置和用户设置。
QtObject {
    id: store

    // ---------- 用户设置（持久保存：QtCore.Settings，Windows 下写入注册表） ----------
    property Settings prefs: Settings {
        id: prefsObj
        category: "prefs"
        // 播放
        property bool pauseOnMinimize: true    // 最小化时暂停，恢复窗口后继续
        property bool autoNext: true           // 自动播放下一集
        property bool titleCard: true          // 切集时显示集号字幕卡
        property bool keepAwake: true          // 播放时阻止休眠和息屏（原型不生效；C++ 调用 SetThreadExecutionState）
        property string quality: "自动"
        property real speed: 1.0               // 跨集、跨剧保留
        property real volume: 0.8
        // 窗口
        property bool fitWindow: true          // 启动 / 换剧时按片源比例调整窗口（竖屏 9:16，横屏自动拉宽）
        property bool alwaysOnTop: false
        property string closeAction: "quit"    // 关闭窗口时：quit 退出程序 | tray 最小化到托盘
        property bool trayHintShown: false     // 第一次最小化到托盘时的系统通知只显示一次
        // 操作
        property string wheelAction: "episode" // episode：切换短剧 | volume：调节音量
        property int controlsIdle: 2500        // 控件自动隐藏延迟（毫秒）
        property int prefetchLead: 20          // 本集剩余多少秒时确认下一集已预取（服务端落盘要 3–8 秒）
        // 更新
        property bool autoCheckUpdate: true    // 启动后检查 GitHub 上有没有新版本
        property string updateChannel: "official" // 更新渠道：official 直连 GitHub | ghfast 走 ghfast.top 镜像（键见 updater.py 的 MIRRORS）
        // 快捷键：只保存与默认值不同的项（JSON：action -> 按键序列，"" 表示未设置）
        property string shortcutsJson: "{}"
    }

    property alias quality: prefsObj.quality
    property alias speed: prefsObj.speed
    property alias volume: prefsObj.volume
    property bool muted: false
    property bool offline: false
    property bool simulateFrames: false     // 仅原型：模拟视频按 30fps 重绘，用于测试播放中拖动窗口

    readonly property var speeds: [0.75, 1.0, 1.25, 1.5, 2.0]
    readonly property var qualities: ["自动", "1080P", "720P", "480P"]
    // 传给后端的清晰度参数："自动" → ""（后端用默认），其余如 "720P" → "720p"
    readonly property string definition: quality === "自动" ? "" : quality.toLowerCase()

    // ---------- 观看进度 ----------
    // dramaId -> { ep, pos, at, title, total, desc }，ep 从 0 开始，at 为最后观看时间（用于历史排序）。
    // 标题 / 集数 / 简介是快照：重启后这部剧多半不在新的推荐流里，靠它把剧并回剧单（Backend.rememberDramas）。
    // 和搜索记录一起存在注册表（QtCore.Settings），升级、重装都不会丢；只有设置页「完全重置」会清掉
    property var progress: ({})
    property var searches: []                // 最近搜索词，新的在前，最多 maxSearches 条
    readonly property int maxSearches: 10
    readonly property int maxHistory: 300    // 历史最多保留多少部（最久没看的先丢），免得注册表越写越大

    property Settings records: Settings {
        id: recordsObj
        category: "records"
        property string progressJson: "{}"
        property string searchesJson: "[]"
    }

    function parseJson(text, fallback) {
        try { return JSON.parse(text) || fallback } catch (e) { return fallback }
    }
    Component.onCompleted: {
        progress = parseJson(recordsObj.progressJson, {})
        searches = parseJson(recordsObj.searchesJson, [])
        Backend.rememberDramas(Object.keys(progress).map(k => ({
            id: k, title: progress[k].title, total: progress[k].total, desc: progress[k].desc })))
    }

    signal toast(string message)

    function progressOf(id) { return progress[id] || null }
    function saveProgress(id, ep, pos) {
        const d = MockData.drama(id)
        const old = progress[id] || {}
        const known = d && String(d.id) === String(id)      // 剧单里找不到时 drama() 会退回别的剧，不能拿来当快照
        progress[id] = { ep: ep, pos: pos, at: Date.now(),
                         title: known ? d.title : (old.title || ""),
                         total: known ? d.total : (old.total || 0),
                         desc: known ? (d.desc || "") : (old.desc || "") }
        const ids = Object.keys(progress)
        if (ids.length > maxHistory) {
            ids.sort((a, b) => progress[a].at - progress[b].at)
            for (let i = 0; i < ids.length - maxHistory; ++i) delete progress[ids[i]]
        }
        recordsObj.progressJson = JSON.stringify(progress)
    }
    // 观看历史：最近看过的在前。id 保持字符串（19 位，转成数字会丢精度）
    function history() {
        return Object.keys(progress).map(k => ({ id: k, at: progress[k].at }))
                                    .sort((a, b) => b.at - a.at)
    }
    function clearHistory() {
        progress = ({})
        recordsObj.progressJson = "{}"
    }

    // ---------- 搜索记录 ----------
    // 只记「确认过」的搜索（回车或点了结果），边打字边出的中间词（「死」「死考」）不记
    function addSearch(q) {
        q = String(q || "").trim()
        if (!q) return
        searches = [q].concat(searches.filter(s => s !== q)).slice(0, maxSearches)
        recordsObj.searchesJson = JSON.stringify(searches)
    }
    function clearSearches() {
        searches = []
        recordsObj.searchesJson = "[]"
    }

    // ---------- 快捷键（第 6.1 节） ----------
    // Esc 固定用于逐层关闭，不可修改
    readonly property var actions: [
        { key: "playPause",   name: "播放 / 暂停", seq: "Space" },
        { key: "seekBack",    name: "后退 5 秒",   seq: "Left" },
        { key: "seekForward", name: "前进 5 秒",   seq: "Right" },
        { key: "prevEpisode", name: "上一部短剧", seq: "Up" },
        { key: "nextEpisode", name: "下一部短剧", seq: "Down" },
        { key: "episodes",    name: "选集",        seq: "E" },
        { key: "fullscreen",  name: "全屏",        seq: "F" },
        { key: "mute",        name: "静音",        seq: "M" },
        { key: "speedDown",   name: "降低倍速",    seq: "[" },
        { key: "speedUp",     name: "提高倍速",    seq: "]" },
        { key: "search",      name: "搜索",        seq: "Ctrl+F" },
        { key: "history",     name: "观看历史",    seq: "H" },
        { key: "settings",    name: "设置",        seq: "Ctrl+," }
    ]
    // action -> 当前按键序列
    readonly property var keys: {
        const custom = JSON.parse(prefsObj.shortcutsJson || "{}")
        const result = {}
        for (const a of actions) result[a.key] = a.key in custom ? custom[a.key] : a.seq
        return result
    }
    function actionName(key) {
        for (const a of actions) if (a.key === key) return a.name
        return ""
    }
    // 设置快捷键；若与其他操作冲突，把那一项改为未设置。返回被解绑的操作名（没有冲突时为空）
    function setKey(action, seq) {
        const custom = JSON.parse(prefsObj.shortcutsJson || "{}")
        let unbound = ""
        if (seq !== "") {
            for (const a of actions) {
                if (a.key !== action && keys[a.key] === seq) {
                    custom[a.key] = ""
                    unbound = a.name
                }
            }
        }
        custom[action] = seq
        for (const a of actions) if (custom[a.key] === a.seq) delete custom[a.key]
        prefsObj.shortcutsJson = JSON.stringify(custom)
        return unbound
    }
    function resetKeys() { prefsObj.shortcutsJson = "{}" }

    // 显示用文字：Space → 空格，Left → ←，Ctrl+, → Ctrl + ,
    function keyText(seq) {
        if (!seq) return "未设置"
        const names = { Space: "空格", Left: "←", Right: "→", Up: "↑", Down: "↓", Return: "回车", Del: "Delete" }
        return seq.split(/\+(?!$)/).map(p => names[p] || p).join(" + ")
    }
    // 提示文字中的快捷键后缀，如「 (E)」；未设置时为空
    function tipKey(action) { return keys[action] ? " (" + keyText(keys[action]) + ")" : "" }

    // 由按键事件生成按键序列；只按下修饰键时返回空字符串
    function sequenceFromEvent(e) {
        const k = e.key
        if (k === Qt.Key_Control || k === Qt.Key_Shift || k === Qt.Key_Alt || k === Qt.Key_Meta || k === 0)
            return ""
        const special = {
            [Qt.Key_Space]: "Space", [Qt.Key_Left]: "Left", [Qt.Key_Right]: "Right",
            [Qt.Key_Up]: "Up", [Qt.Key_Down]: "Down", [Qt.Key_PageUp]: "PgUp", [Qt.Key_PageDown]: "PgDown",
            [Qt.Key_Home]: "Home", [Qt.Key_End]: "End", [Qt.Key_Insert]: "Ins", [Qt.Key_Delete]: "Del",
            [Qt.Key_Return]: "Return", [Qt.Key_Enter]: "Return", [Qt.Key_Tab]: "Tab"
        }
        let name = special[k]
        let printable = false
        if (!name && k >= Qt.Key_F1 && k <= Qt.Key_F24) name = "F" + (k - Qt.Key_F1 + 1)
        if (!name && k > 0x20 && k <= 0x7e) { name = String.fromCharCode(k); printable = true }
        if (!name) return ""
        let mods = ""
        if (e.modifiers & Qt.ControlModifier) mods += "Ctrl+"
        if (e.modifiers & Qt.AltModifier) mods += "Alt+"
        // 符号键的 Shift 已体现在字符本身（如 Shift+[ 得到 {），不再重复
        const isLetterOrDigit = /[A-Z0-9]/.test(name)
        if ((e.modifiers & Qt.ShiftModifier) && (!printable || isLetterOrDigit)) mods += "Shift+"
        return mods + name
    }
}
