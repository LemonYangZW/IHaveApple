import QtQuick
import QtQuick.Templates as T
import IHaveApple 1.0

// 搜索 / 观看历史面板：从标题栏下方展开，两种模式共用一个面板，与选集面板互斥。
// 选中一部剧后由 Main 切换播放并关闭面板。不显示推荐内容。
Item {
    id: lib

    property string mode: ""                 // "" | "search" | "history"
    readonly property bool open: mode !== ""
    // 剧 id 是 19 位字符串（如 7707148393058946072）。这里声明成 int 会被截断成 32 位整数，
    // 结果是一条都解析不到，点进去还是原来那部剧 —— 所以信号和属性一律用 string。
    property string currentDrama: ""
    signal pick(string dramaId)

    // 内容按「最后一次打开的模式」显示，关闭动画期间不跳变
    property string shownMode: "search"
    property var historyItems: []
    readonly property string query: field.text.trim()
    property var results: []
    property bool searching: false
    readonly property var items: shownMode === "history" ? historyItems : results

    // 服务端检索（/v1/search）：输入停止 300ms 后才发请求，避免逐字打服务端
    onQueryChanged: {
        searching = false
        results = []
        if (query) debounce.restart()
        else debounce.stop()
    }
    Timer {
        id: debounce
        interval: 300
        onTriggered: { lib.searching = true; Backend.search(lib.query) }
    }
    Connections {
        target: Backend
        function onSearchResults(q, items) {
            if (q !== lib.query) return
            lib.searching = false
            lib.results = items
        }
    }

    function show(m) {
        if (m === "history") historyItems = Store.history()
        shownMode = m
        mode = m
        // 面板里每行都要缩略图；启动时只转了首屏几张，这里把剩下的补齐
        Backend.ensureCovers()
        if (m === "search") { field.selectAll(); field.forceActiveFocus() }
        else field.focus = false
    }
    function close() { mode = ""; field.focus = false }
    function toggle(m) { mode === m ? close() : show(m) }

    function detailOf(dramaId) {
        const d = MockData.drama(dramaId)
        const p = Store.progressOf(dramaId)
        return (p ? "看到第 " + (p.ep + 1) + " 集 · " : "") + (d.total > 0 ? "共 " + d.total + " 集" : "点击打开")
    }

    readonly property int headerHeight: Theme.space.sm * 2 + Theme.layout.button
    implicitHeight: headerHeight + (items.length > 0 ? items.length * Theme.layout.dramaRow : 64) + Theme.space.sm

    clip: true
    visible: open || slide.running

    // 展开进度 0 → 1，只对开关做动画。不能直接给 panel.y 加 Behavior：关闭时 y = -height，
    // 放大窗口时 height 一变也会触发滑动，动画期间面板可见，标题栏下方会露出一截面板
    property real reveal: open ? 1 : 0
    Behavior on reveal {
        NumberAnimation {
            id: slide
            duration: Theme.reducedMotion ? 0 : Theme.motion.base
            easing.type: Easing.BezierSpline
            easing.bezierCurve: Theme.motion.baseCurve
        }
    }

    Rectangle {
        id: panel
        width: parent.width
        height: parent.height
        y: -height * (1 - lib.reveal)
        color: Theme.color.wing
        bottomLeftRadius: Theme.radius.lg
        bottomRightRadius: Theme.radius.lg

        // 吃掉点击和滚轮，避免穿透到舞台
        MouseArea {
            anchors.fill: parent
            onWheel: wheel => wheel.accepted = true
        }

        // ---- 头部：搜索框 或 标题 ----
        Item {
            id: header
            x: Theme.space.md
            width: parent.width - x - Theme.space.xs
            height: lib.headerHeight

            T.TextField {
                id: field
                objectName: "searchField"
                visible: lib.shownMode === "search"
                anchors.left: parent.left
                anchors.right: closeButton.left
                anchors.rightMargin: Theme.space.xs
                anchors.verticalCenter: parent.verticalCenter
                height: Theme.layout.button
                leftPadding: Theme.space.xl
                rightPadding: Theme.space.sm
                verticalAlignment: TextInput.AlignVCenter
                font.family: Theme.type.body.family
                font.pixelSize: Theme.type.body.size
                color: Theme.color.subtitle
                selectionColor: Theme.color.crabappleDeep
                selectedTextColor: Theme.color.subtitle
                Accessible.name: "搜索剧名"
                // 回车直接播放第一个结果
                onAccepted: if (lib.results.length > 0) lib.pick(String(lib.results[0].id))

                background: Rectangle {
                    radius: Theme.radius.md
                    color: Theme.color.proscenium
                    border.width: field.activeFocus ? 1 : 0
                    border.color: Theme.color.crabapple
                    Icon {
                        x: Theme.space.sm
                        anchors.verticalCenter: parent.verticalCenter
                        glyph: Theme.icon.search
                        size: 14
                        color: Theme.color.aside
                    }
                    Label {
                        x: field.leftPadding
                        anchors.verticalCenter: parent.verticalCenter
                        visible: field.text === "" && field.preeditText === ""
                        color: Theme.color.aside
                        text: "搜索剧名"
                    }
                }
            }

            Row {
                visible: lib.shownMode === "history"
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.space.xs
                Label { role: Theme.type.h2; text: "观看历史"; anchors.verticalCenter: parent.verticalCenter }
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    role: Theme.type.caption
                    color: Theme.color.aside
                    text: lib.historyItems.length > 0 ? lib.historyItems.length + " 部" : ""
                }
            }

            IconButton {
                id: closeButton
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                glyph: Theme.icon.close
                glyphSize: 12
                tip: "关闭 (Esc)"
                onClicked: lib.close()
            }
        }

        // ---- 列表 ----
        ListView {
            id: list
            visible: lib.items.length > 0
            anchors.top: header.bottom
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Theme.space.sm
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: Theme.space.xs
            anchors.rightMargin: Theme.space.xs
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: lib.items
            delegate: DramaRow {
                required property var modelData
                width: ListView.view.width
                drama: MockData.drama(modelData.id)
                detail: lib.detailOf(modelData.id)
                current: String(modelData.id) === String(lib.currentDrama)
                onClicked: lib.pick(String(modelData.id))
            }
        }

        // ---- 空状态 ----
        Label {
            visible: lib.items.length === 0
            anchors.top: header.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: 64
            horizontalAlignment: Text.AlignHCenter
            color: Theme.color.aside
            text: lib.shownMode === "history" ? "还没有看过的剧"
                : lib.query === "" ? "输入剧名搜索"
                : lib.searching ? "搜索中…"
                : "没有找到「" + lib.query + "」相关的短剧"
        }
    }
}
