import QtQuick

// 选集面板：从舞台底部（控件栏上方）升起，高度贴合方格内容（最多占舞台 60%）。
// 面板打开时控件栏保持显示，「选集」按钮可再次点击关闭。
// 不做实心卡片：顶部从透明渐变到 scrimDeep，与控件栏（面板打开时同样铺 scrimDeep）连成一片，
// 画面到面板没有硬边。不用模糊 —— 视频每帧都在变，模糊要每帧重算（第 9 节）。
Item {
    id: sheet

    property bool open: false
    property var drama
    property int currentEp: 0
    property real position: 0
    property real duration: 1
    property alias grid: grid
    signal pick(int ep)

    implicitHeight: header.y + header.height + Theme.space.xs + grid.implicitHeight + Theme.space.sm
    clip: true
    visible: open || slide.running

    // 展开进度 0 → 1，只对开关做动画。不能直接给 panel.y 加 Behavior：关闭时 y = height，
    // 窗口放大、换剧导致面板高度变化时也会触发滑动，动画期间面板可见，底部会露出一截
    property real reveal: open ? 1 : 0
    Behavior on reveal {
        NumberAnimation {
            id: slide
            duration: Theme.reducedMotion ? 0 : Theme.motion.base
            easing.type: Easing.BezierSpline
            easing.bezierCurve: Theme.motion.baseCurve
        }
    }

    Item {
        id: panel
        width: parent.width
        height: parent.height
        y: height * (1 - sheet.reveal)

        // 背景：顶部 episodeFade 高度内由透明过渡到 scrimDeep，其余铺满
        Rectangle {
            id: fade
            width: parent.width
            height: Theme.layout.episodeFade
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 1.0; color: Theme.color.scrimDeep }
            }
        }
        Rectangle {
            anchors.top: fade.bottom
            anchors.bottom: parent.bottom
            width: parent.width
            color: Theme.color.scrimDeep
        }

        // 吃掉点击（避免穿透到舞台触发暂停）和滚轮。面板里的滚轮只滚动面板自己：
        // 方格放不下时上下滚方格、分页栏上横向滚分页（都由它们自己处理，叠在这一层上面）；
        // 滚到头或无处可滚的滚轮落到这里吃掉，不漏到舞台上去翻集
        MouseArea {
            anchors.fill: parent
            onWheel: wheel => wheel.accepted = true
        }

        Row {
            id: header
            x: Theme.space.md
            // 标题压在渐变的下半段：渐变读起来是画面的延伸，而不是面板外的空白
            y: Theme.layout.episodeFade - Theme.space.xs
            spacing: Theme.space.xs
            Label { role: Theme.type.h2; text: "选集"; anchors.verticalCenter: parent.verticalCenter }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                role: Theme.type.caption
                color: Theme.color.aside
                text: sheet.drama ? "共 " + sheet.drama.total + " 集" : ""
            }
        }
        IconButton {
            anchors.right: parent.right
            anchors.rightMargin: Theme.space.xs
            anchors.verticalCenter: header.verticalCenter
            glyph: Theme.icon.close
            glyphSize: 12
            tip: "关闭" + Store.tipKey("episodes")
            onClicked: sheet.open = false
        }

        EpisodeGrid {
            id: grid
            anchors.top: header.bottom
            anchors.topMargin: Theme.space.xs
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Theme.space.sm
            drama: sheet.drama
            currentEp: sheet.currentEp
            position: sheet.position
            duration: sheet.duration
            onPick: ep => sheet.pick(ep)
        }
    }
}
