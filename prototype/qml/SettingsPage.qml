import QtQuick
import QtQuick.Templates as T

// 设置页：盖在画面上（标题栏下方到窗口底部），视频在下面继续播放。
// 所有设置即时生效并持久保存（Store.prefs），没有「保存」按钮。
Item {
    id: page

    property bool open: false
    property bool trayAvailable: true
    function show() { open = true; flick.contentY = 0; recorder.cancel() }
    function close() { open = false; recorder.cancel() }
    function toggle() { open ? close() : show() }

    visible: opacity > 0
    opacity: open ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Theme.reducedMotion ? 0 : Theme.motion.base } }

    Rectangle {
        anchors.fill: parent
        color: Theme.color.wing
        // 吃掉点击和滚轮，避免穿透到舞台
        MouseArea { anchors.fill: parent; onWheel: wheel => wheel.accepted = true }
    }

    // ---- 头部 ----
    Item {
        id: header
        width: parent.width
        height: 56
        Label {
            x: Theme.space.md
            anchors.verticalCenter: parent.verticalCenter
            role: Theme.type.h1
            text: "设置"
        }
        IconButton {
            anchors.right: parent.right
            anchors.rightMargin: Theme.space.xs
            anchors.verticalCenter: parent.verticalCenter
            glyph: Theme.icon.close
            glyphSize: 12
            tip: "关闭 (Esc)"
            onClicked: page.close()
        }
    }

    Flickable {
        id: flick
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        width: parent.width
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: content.height + Theme.space.xl

        Column {
            id: content
            x: Math.max(Theme.space.md, (parent.width - width) / 2)
            width: Math.min(Theme.layout.settingsWidth, flick.width - Theme.space.md * 2)

            // ---------- 播放 ----------
            SectionTitle { text: "播放" }
            ToggleRow {
                title: "最小化时暂停播放"
                note: "恢复窗口后自动继续"
                checked: Store.prefs.pauseOnMinimize
                onClicked: Store.prefs.pauseOnMinimize = !Store.prefs.pauseOnMinimize
            }
            ToggleRow {
                title: "自动播放下一集"
                note: "关闭后，每集播完停在最后一帧"
                checked: Store.prefs.autoNext
                onClicked: Store.prefs.autoNext = !Store.prefs.autoNext
            }
            ToggleRow {
                title: "切集时显示集号"
                note: "画面左上角短暂显示「第 N 集」"
                checked: Store.prefs.titleCard
                onClicked: Store.prefs.titleCard = !Store.prefs.titleCard
            }
            ToggleRow {
                title: "播放时阻止电脑休眠和息屏"
                checked: Store.prefs.keepAwake
                onClicked: Store.prefs.keepAwake = !Store.prefs.keepAwake
            }
            ChoiceRow {
                title: "画质"
                note: "播放时也可以在控件栏切换"
                options: Store.qualities.map(q => ({ value: q, text: q }))
                value: Store.quality
                onPicked: v => Store.quality = v
            }

            // ---------- 窗口 ----------
            SectionTitle { text: "窗口" }
            ToggleRow {
                title: "窗口置顶"
                note: "和其他软件并排时，播放窗口始终在最前面"
                checked: Store.prefs.alwaysOnTop
                onClicked: Store.prefs.alwaysOnTop = !Store.prefs.alwaysOnTop
            }
            ChoiceRow {
                title: "关闭窗口时"
                note: page.trayAvailable ? "最小化到托盘后，单击托盘图标恢复窗口，右键菜单可以退出"
                                         : "当前系统不支持托盘图标"
                enabled: page.trayAvailable
                options: [{ value: "quit", text: "退出程序" }, { value: "tray", text: "最小化到托盘" }]
                value: Store.prefs.closeAction
                onPicked: v => Store.prefs.closeAction = v
            }

            // ---------- 操作 ----------
            SectionTitle { text: "操作" }
            ChoiceRow {
                title: "在画面上滚动鼠标滚轮"
                options: [{ value: "episode", text: "切换短剧" }, { value: "volume", text: "调节音量" }]
                value: Store.prefs.wheelAction
                onPicked: v => Store.prefs.wheelAction = v
            }
            ChoiceRow {
                title: "鼠标静止后隐藏控件"
                options: [{ value: 1500, text: "1.5 秒" }, { value: 2500, text: "2.5 秒" }, { value: 4000, text: "4 秒" }]
                value: Store.prefs.controlsIdle
                onPicked: v => Store.prefs.controlsIdle = v
            }

            // ---------- 快捷键 ----------
            Item {
                width: parent.width
                height: keysTitle.height
                SectionTitle { id: keysTitle; text: "快捷键" }
                T.AbstractButton {
                    id: resetKeys
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: Theme.space.xxs
                    height: 28
                    width: resetLabel.implicitWidth + Theme.space.sm * 2
                    Accessible.name: "快捷键恢复默认"
                    onClicked: { recorder.cancel(); Store.resetKeys(); recorder.message = "已恢复默认快捷键" }
                    background: Rectangle {
                        radius: Theme.radius.md
                        color: Theme.color.proscenium
                        opacity: resetKeys.hovered ? 1 : 0
                        FocusRing { target: resetKeys }
                    }
                    contentItem: Label {
                        id: resetLabel
                        role: Theme.type.caption
                        horizontalAlignment: Text.AlignHCenter
                        color: resetKeys.hovered ? Theme.color.subtitle : Theme.color.aside
                        text: "恢复默认"
                    }
                }
            }
            Label {
                width: parent.width
                role: Theme.type.caption
                color: Theme.color.aside
                wrapMode: Text.WordWrap
                text: "点击按键后按下新的组合键；Backspace 清除，Esc 取消。Esc 固定用于逐层关闭，不能修改。"
            }
            Label {
                id: keyMessage
                visible: recorder.message !== ""
                width: parent.width
                topPadding: Theme.space.xs
                role: Theme.type.caption
                color: Theme.color.crabapple
                wrapMode: Text.WordWrap
                text: recorder.message
            }
            Item { width: 1; height: Theme.space.xs }
            Repeater {
                model: Store.actions
                delegate: KeyRow {
                    required property var modelData
                    action: modelData.key
                    title: modelData.name
                }
            }

            // ---------- 数据 ----------
            SectionTitle { text: "数据" }
            Item {
                width: parent.width
                height: 56
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    role: Theme.type.body
                    text: "观看历史"
                }
                IhaButton {
                    id: clearButton
                    property bool confirming: false
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: confirming ? "确认清空" : "清空"
                    onClicked: {
                        if (!confirming) { confirming = true; confirmTimer.restart(); return }
                        confirming = false
                        Store.clearHistory()
                        Store.toast("观看历史已清空")
                    }
                    inkColor: confirming ? Theme.color.danger : Theme.color.subtitle
                    Timer { id: confirmTimer; interval: 3000; onTriggered: clearButton.confirming = false }
                }
            }

            // ---------- 关于 ----------
            SectionTitle { text: "关于" }
            Label {
                width: parent.width
                role: Theme.type.caption
                color: Theme.color.aside
                wrapMode: Text.WordWrap
                text: "IHaveApple · UI 原型 v2.2\n设置保存在本机，下次启动时自动恢复。"
            }
        }
    }

    // ---------- 快捷键录制（同一时间只录制一项） ----------
    QtObject {
        id: recorder
        property string action: ""
        property string message: ""
        function start(a) { action = a; message = "" }
        function cancel() { action = "" }
        function finish(seq) {
            const a = action
            action = ""
            const unbound = Store.setKey(a, seq)
            message = seq === "" ? "「" + Store.actionName(a) + "」已设为未设置"
                    : unbound ? Store.keyText(seq) + " 原来用于「" + unbound + "」，该项已改为未设置"
                    : ""
        }
    }

    // ---------- 行组件 ----------
    component SectionTitle: Label {
        width: parent ? parent.width : 0
        topPadding: Theme.space.lg
        bottomPadding: Theme.space.xxs
        role: Theme.type.caption
        color: Theme.color.crabapple
    }

    // 整行是一个按钮（点文字也能切换），开关只作指示
    component ToggleRow: T.AbstractButton {
        id: tr
        property string note
        width: parent.width
        height: Math.max(56, texts.implicitHeight + Theme.space.sm * 2)
        Accessible.role: Accessible.CheckBox
        Accessible.checked: checked
        Accessible.name: title

        property string title
        background: FocusRing { target: tr }
        Column {
            id: texts
            anchors.left: parent.left
            anchors.right: sw.left
            anchors.rightMargin: Theme.space.md
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Label { width: parent.width; role: Theme.type.body; text: tr.title; wrapMode: Text.WordWrap; elide: Text.ElideNone }
            Label {
                visible: tr.note !== ""
                width: parent.width
                role: Theme.type.caption
                color: Theme.color.aside
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                text: tr.note
            }
        }
        Toggle {
            id: sw
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            enabled: false
            checked: tr.checked
        }
    }

    component ChoiceRow: Column {
        id: cr
        property string title
        property string note
        property alias options: seg.options
        property alias value: seg.value
        signal picked(var value)
        width: parent.width
        topPadding: Theme.space.sm
        bottomPadding: Theme.space.sm
        spacing: Theme.space.xs
        Column {
            width: parent.width
            spacing: 2
            Label { width: parent.width; role: Theme.type.body; text: cr.title }
            Label {
                visible: cr.note !== ""
                width: parent.width
                role: Theme.type.caption
                color: Theme.color.aside
                text: cr.note
            }
        }
        Segmented { id: seg; onPicked: v => cr.picked(v) }
    }

    component KeyRow: Item {
        id: kr
        property string action
        property string title
        readonly property string seq: Store.keys[action]
        readonly property bool recording: recorder.action === action
        width: parent.width
        height: 40

        Label {
            anchors.verticalCenter: parent.verticalCenter
            role: Theme.type.body
            text: kr.title
        }
        T.AbstractButton {
            id: cap
            objectName: "key_" + kr.action
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            height: 28
            width: Math.max(64, capLabel.implicitWidth + Theme.space.md)
            Accessible.name: kr.title + "快捷键：" + Store.keyText(kr.seq)
            onClicked: { recorder.start(kr.action); forceActiveFocus() }
            onActiveFocusChanged: if (!activeFocus && kr.recording) recorder.cancel()

            // 录制时先于窗口快捷键拿到按键
            Keys.onShortcutOverride: event => event.accepted = kr.recording
            Keys.onPressed: event => {
                if (!kr.recording) return
                event.accepted = true
                if (event.key === Qt.Key_Escape) { recorder.cancel(); return }
                if (event.key === Qt.Key_Backspace) { recorder.finish(""); return }
                const s = Store.sequenceFromEvent(event)
                if (s !== "") recorder.finish(s)
            }

            background: Rectangle {
                radius: Theme.radius.sm + 2
                color: Theme.color.proscenium
                border.width: kr.recording ? 1 : 0
                border.color: Theme.color.crabapple
                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    color: Theme.color.subtitle
                    opacity: cap.hovered && !kr.recording ? 0.08 : 0
                }
                FocusRing { target: cap }
            }
            contentItem: Label {
                id: capLabel
                role: Theme.type.label
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideNone
                color: kr.recording ? Theme.color.crabapple : kr.seq ? Theme.color.subtitle : Theme.color.aside
                text: kr.recording ? "请按下新按键" : Store.keyText(kr.seq)
            }
        }
    }
}
