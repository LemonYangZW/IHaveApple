import QtQuick

// 标题栏：叠加在视频顶部，高 40，与播放控件一起显示 / 隐藏。
// 背景是静态渐变（不模糊），只为保证文字在任何画面上都可读。
// 说明：纯 QML 无边框窗口无法弹出 Win11 Snap Layouts，
//      C++ 正式版需处理 WM_NCHITTEST 返回 HTMAXBUTTON（见 README）。
Item {
    id: bar

    property bool fitted: false        // 窗口已「适应屏幕高度」
    property string panel: ""          // 当前打开的面板："" | "search" | "history" | "settings"

    signal toggleFit()
    signal search()
    signal history()
    signal settings()

    height: Theme.layout.titleBar

    Rectangle {
        anchors.fill: parent
        // 整页面板打开时下面已经是实色底，不需要再压暗，免得顶部多出一道深色带
        visible: bar.panel === ""
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.color.stage60 }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    // 拖动窗口 / 双击切换「适应屏幕高度」。
    // 用 MouseArea 吃掉点击，避免穿透到舞台触发暂停。
    // 每次按下只调用一次 startSystemMove：重复调用会排队多个系统移动请求，拖动起步时卡顿。
    MouseArea {
        anchors.fill: parent
        property point pressPos
        property bool moving: false
        onPressed: mouse => { pressPos = Qt.point(mouse.x, mouse.y); moving = false }
        onPositionChanged: mouse => {
            if (pressed && !moving && Math.hypot(mouse.x - pressPos.x, mouse.y - pressPos.y) > 4) {
                moving = true
                Window.window.startSystemMove()
            }
        }
        onDoubleClicked: bar.toggleFit()
    }

    // 标题栏只放操作入口：剧名和简介移到底部信息区（那里空间够，长剧名能完整显示）
    // 左侧留空，整条都可以拖动窗口

    // 入口：搜索、观看历史、设置（剧级 / 应用级操作放在顶部；集级操作「选集」在底部控件栏）
    Row {
        id: tools
        anchors.right: buttons.left
        anchors.rightMargin: Theme.space.xs
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.space.xxs
        IconButton {
            objectName: "searchButton"
            glyph: Theme.icon.search
            glyphSize: 14
            tip: "搜索" + Store.tipKey("search")
            active: bar.panel === "search"
            focusPolicy: Qt.NoFocus
            onClicked: bar.search()
        }
        IconButton {
            objectName: "historyButton"
            glyph: Theme.icon.history
            glyphSize: 14
            tip: "观看历史" + Store.tipKey("history")
            active: bar.panel === "history"
            focusPolicy: Qt.NoFocus
            onClicked: bar.history()
        }
        IconButton {
            objectName: "settingsButton"
            glyph: Theme.icon.settings
            glyphSize: 14
            tip: "设置" + Store.tipKey("settings")
            active: bar.panel === "settings"
            focusPolicy: Qt.NoFocus
            onClicked: bar.settings()
        }
    }

    // 系统按钮：宽 46 × 高 40（Windows 规范尺寸）
    Row {
        id: buttons
        anchors.right: parent.right
        height: parent.height
        WindowButton { glyph: Theme.icon.minimize; tip: "最小化"; onClicked: Window.window.showMinimized() }
        WindowButton {
            glyph: bar.fitted ? Theme.icon.restore : Theme.icon.maximize
            tip: bar.fitted ? "还原窗口" : "适应屏幕高度"
            onClicked: bar.toggleFit()
        }
        WindowButton { glyph: Theme.icon.close; tip: "关闭"; closeStyle: true; onClicked: Window.window.close() }
    }

    component WindowButton: IconButton {
        width: 46
        height: bar.height
        glyphSize: 10
        focusPolicy: Qt.NoFocus
        background: Rectangle {
            color: parent.closeStyle ? Theme.color.crabappleDeep : Theme.color.subtitle
            opacity: parent.closeStyle ? (parent.hovered ? 1 : 0) : (parent.hovered ? 0.12 : 0)
        }
    }
}
