import QtQuick
import IHaveApple 1.0

// 弹幕层：这一集的精选弹幕从右往左横穿画面。
//
// 数据：Backend.danmaku(dramaId, episode) 后台翻页拉（本地 SDK 的 /v1/danmaku），
// 到了 danmakuLoaded → 这里用 Backend.danmakuFor() 取回整集，按出现时间排好。
// 时间：不直接跟 stage.position（mpv 每 100ms 才刷新一次），以它为基准自己走时钟：
// 播放时按墙钟推进（平滑），暂停时停在真实位置，拖进度条（位置跳变）时重新对时。
// 布局：按出现时间贪心分道，同一道里前后两条不会撞上；窗口尺寸变了重新分。
Item {
    id: board

    property string dramaId: ""
    property int episode: 0
    property real position: 0          // 播放位置（秒）
    property bool playing: false
    property bool danmakuEnabled: true

    property var items: []             // [{id,text,offset,likes}]，按 offset 升序
    property var itemLanes: []         // 与 items 等长：道号
    property real clockMs: 0           // 弹幕时钟（毫秒）

    property real lastPosition: -1
    property double lastWall: 0

    readonly property int fontSize: Math.max(13, Math.round(height * 0.024))
    readonly property int lineHeight: Math.round(fontSize * 1.5)
    // 弹幕只占画面上部：让开标题栏 / 频道 tab，也不压住底部的剧名和控件
    readonly property int bandTop: Math.max(Theme.layout.titleBar + Theme.layout.channelBar + Theme.space.xs,
                                            Math.round(height * 0.07))
    readonly property int bandBottom: Math.round(height * 0.5)
    readonly property int laneCount: Math.max(1, Math.floor((bandBottom - bandTop) / lineHeight))
    readonly property int travelMs: 8000          // 一条从右边缘走到完全离开用的时间
    readonly property int gap: Math.round(fontSize * 1.2)
    readonly property int poolSize: 48            // 文本池：同时在屏上的弹幕上限

    clip: true

    // 估算文字宽度（全角 / 中文 / 表情按一个字宽，其余按半宽），用来分道和算 x
    function textWidth(text) {
        let w = 0
        for (let i = 0; i < text.length; ++i) {
            const c = text.charCodeAt(i)
            if (c >= 0xD800 && c <= 0xDBFF) { w += 1.0; continue }   // 代理对的高半位：整个表情算一个字
            if (c >= 0xDC00 && c <= 0xDFFF) continue
            if (c >= 0x2E80) w += 1.0
            else if (c >= 0x20) w += 0.55
        }
        return Math.ceil(w * fontSize)
    }

    // 贪心分道：第 k 道在 free[k] 之前都还占着，找最早空出来的那一道
    function assignLanes() {
        const w = Math.max(1, width)
        const n = laneCount
        const free = []
        const lanes = []
        for (let k = 0; k < n; ++k) free.push(-1e9)
        for (let i = 0; i < items.length; ++i) {
            const it = items[i]
            const tw = Math.min(textWidth(it.text), Math.round(w * 0.9)) + gap
            // 这一条占着这一道多久：尾端离开右边缘的时间（按移动速度折算）
            const hold = travelMs * tw / (w + tw)
            let lane = 0
            for (let k = 0; k < n; ++k) {
                if (free[k] <= it.offset) { lane = k; break }
                if (free[k] < free[lane]) lane = k
            }
            free[lane] = it.offset + hold
            lanes.push(lane)
        }
        itemLanes = lanes
    }

    function paint() {
        const w = Math.max(1, width)
        const t = clockMs
        // 二分找第一条还在屏上（offset >= t - travel）的弹幕
        let lo = 0, hi = items.length
        const from = t - travelMs
        while (lo < hi) {
            const mid = (lo + hi) >> 1
            if (items[mid].offset < from) lo = mid + 1
            else hi = mid
        }
        let n = 0
        for (let i = lo; i < items.length && n < poolSize; ++i) {
            const it = items[i]
            if (it.offset > t) break
            const p = (t - it.offset) / travelMs       // 0 = 刚进右边缘，1 = 完全离开
            if (p > 1) continue
            const d = pool.itemAt(n)
            if (!d) break
            const tw = Math.min(textWidth(it.text), Math.round(w * 0.9))
            d.text = it.text
            d.x = w - p * (w + tw)
            d.y = bandTop + (itemLanes[i] || 0) * lineHeight
            d.visible = true
            n++
        }
        for (let i = n; i < poolSize; ++i) {
            const d = pool.itemAt(i)
            if (d && d.visible) d.visible = false
        }
    }

    // 每帧推进时钟再重排一遍；位置跳变（拖动进度条 / 换集）时直接对齐
    function tick() {
        const wall = Date.now()
        const pos = Math.max(0, position) * 1000
        const dt = lastWall > 0 ? wall - lastWall : 0
        if (lastPosition < 0 || Math.abs(pos - lastPosition) > 400)
            clockMs = pos
        else if (playing && dt > 0)
            clockMs += Math.min(dt, 250)              // 主线程卡一下时不要跳一大段
        else
            clockMs = pos
        lastPosition = pos
        lastWall = wall
        paint()
    }

    function request() {
        items = []
        itemLanes = []
        clockMs = Math.max(0, position) * 1000
        lastPosition = -1
        lastWall = 0
        if (!danmakuEnabled || dramaId === "" || episode < 0) return
        Backend.danmaku(dramaId, episode)
    }

    onDramaIdChanged: request()
    onEpisodeChanged: request()
    onDanmakuEnabledChanged: request()
    onWidthChanged: { assignLanes(); paint() }
    onHeightChanged: { assignLanes(); paint() }

    Connections {
        target: Backend
        function onDanmakuLoaded(seriesId, ep) {
            if (String(seriesId) !== String(board.dramaId) || ep !== board.episode) return
            board.items = Backend.danmakuFor(board.dramaId, board.episode)
            board.assignLanes()
            board.lastPosition = -1
            board.paint()
        }
    }

    Timer {
        interval: 16
        repeat: true
        running: board.danmakuEnabled && board.items.length > 0 && board.visible
        onTriggered: board.tick()
    }

    Repeater {
        id: pool
        model: board.poolSize
        Text {
            visible: false
            textFormat: Text.PlainText
            font.family: Theme.font.ui
            font.pixelSize: board.fontSize
            font.weight: Font.Medium
            color: Theme.color.subtitle
            opacity: 0.92
            style: Text.Outline
            styleColor: Qt.rgba(0, 0, 0, 0.55)
        }
    }
}
