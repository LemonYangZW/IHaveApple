import QtQuick
import QtQuick.Templates as T
import IHaveApple 1.0

// 搜索 / 观看历史 / 收藏夹面板：从标题栏下方展开，三种模式共用一个面板，与选集面板互斥。
// 选中一部剧后由 Main 切换播放并关闭面板（历史 / 收藏里点开会续播）。不显示推荐内容。
Item {
    id: lib

    property string mode: ""                 // "" | "search" | "history" | "favorites"
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
    // 收藏夹直接跟着 Store：在列表里取消收藏，那一行马上消失
    readonly property var items: shownMode === "history" ? historyItems
                               : shownMode === "favorites" ? Store.favorites : results
    readonly property var titles: ({ history: "观看历史", favorites: "收藏夹" })

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
    // 选中一部剧：从搜索结果里选的，这次搜索算「确认过」，记进搜索记录
    function choose(dramaId) {
        if (shownMode === "search") Store.addSearch(query)
        pick(dramaId)
    }
    // 点搜索记录：填回搜索框重新搜（同时把它挪到记录最前面）
    function searchAgain(q) {
        field.text = q
        Store.addSearch(q)
        field.forceActiveFocus()
    }
    // 搜索框为空时显示最近搜索
    readonly property bool showRecent: shownMode === "search" && query === "" && Store.searches.length > 0

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

        // ---- 头部：返回 + 搜索框 或 标题 ----
        // 返回放在左侧：右上角是窗口的关闭按钮，两个 × 上下摞着容易点错把程序关了
        Item {
            id: header
            x: Theme.space.xs
            width: parent.width - x - Theme.space.md
            height: lib.headerHeight

            IconButton {
                id: closeButton
                objectName: "libraryBack"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                glyph: Theme.icon.back
                glyphSize: 12
                tip: "返回 (Esc)"
                onClicked: lib.close()
            }

            T.TextField {
                id: field
                objectName: "searchField"
                visible: lib.shownMode === "search"
                anchors.left: closeButton.right
                anchors.right: parent.right
                anchors.leftMargin: Theme.space.xs
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
                // 回车直接播放第一个结果（还没出结果时也记下这次搜索）
                onAccepted: {
                    Store.addSearch(lib.query)
                    if (lib.results.length > 0) lib.pick(String(lib.results[0].id))
                }

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
                visible: lib.shownMode !== "search"
                anchors.left: closeButton.right
                anchors.leftMargin: Theme.space.xs
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.space.xs
                Label { role: Theme.type.h2; text: lib.titles[lib.shownMode] || ""; anchors.verticalCenter: parent.verticalCenter }
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    role: Theme.type.caption
                    color: Theme.color.aside
                    text: lib.items.length > 0 ? lib.items.length + " 部" : ""
                }
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
                // 收藏夹里每行右侧一颗实心星：点它取消收藏
                actionGlyph: lib.shownMode === "favorites" ? Theme.icon.favoriteFill : ""
                actionTip: "取消收藏"
                onActionClicked: Store.toggleFavorite(String(modelData.id))
                onClicked: lib.choose(String(modelData.id))
            }
        }

        // ---- 最近搜索（搜索框为空时）：点一条重新搜 ----
        Column {
            visible: lib.showRecent
            anchors.top: header.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: Theme.space.md
            anchors.rightMargin: Theme.space.md
            spacing: Theme.space.sm

            Item {
                width: parent.width
                height: clearRecent.height
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    role: Theme.type.caption
                    color: Theme.color.aside
                    text: "最近搜索"
                }
                T.AbstractButton {
                    id: clearRecent
                    anchors.right: parent.right
                    height: 28
                    width: clearLabel.implicitWidth + Theme.space.sm * 2
                    Accessible.name: "清空搜索记录"
                    onClicked: Store.clearSearches()
                    contentItem: Label {
                        id: clearLabel
                        role: Theme.type.caption
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        color: clearRecent.hovered ? Theme.color.subtitle : Theme.color.aside
                        text: "清空"
                    }
                    background: Rectangle {
                        radius: Theme.radius.md
                        color: clearRecent.hovered ? Theme.color.subtitle08 : "transparent"
                        FocusRing { target: clearRecent }
                    }
                }
            }

            Flow {
                width: parent.width
                spacing: Theme.space.xs
                Repeater {
                    model: Store.searches
                    delegate: T.AbstractButton {
                        id: chip
                        required property string modelData
                        height: 30
                        width: Math.min(chipLabel.implicitWidth + Theme.space.md * 2, parent.width)
                        Accessible.name: "搜索 " + modelData
                        onClicked: lib.searchAgain(modelData)
                        contentItem: Label {
                            id: chipLabel
                            role: Theme.type.caption
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.color.subtitle
                            text: chip.modelData
                        }
                        background: Rectangle {
                            radius: height / 2
                            color: chip.hovered ? Theme.color.subtitle14 : Theme.color.subtitle08
                            Behavior on color { ColorAnimation { duration: Theme.motion.fast } }
                            FocusRing { target: chip; targetRadius: height / 2 }
                        }
                    }
                }
            }
        }

        // ---- 空状态 ----
        Label {
            visible: lib.items.length === 0 && !lib.showRecent
            anchors.top: header.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: 64
            horizontalAlignment: Text.AlignHCenter
            color: Theme.color.aside
            text: lib.shownMode === "history" ? "点「查看全集」看过的剧会记在这里"
                : lib.shownMode === "favorites" ? "点控件栏的星标收藏的剧会在这里，点开接着看"
                : lib.query === "" ? "输入剧名搜索"
                : lib.searching ? "搜索中…"
                : "没有找到「" + lib.query + "」相关的短剧"
        }
    }
}
