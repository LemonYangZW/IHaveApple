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
    signal wheelStep(int dir)   // 面板上的滚轮：翻本剧上下集（由播放页处理）

    implicitHeight: header.y + header.height + Theme.space.xs + grid.implicitHeight + Theme.space.sm
    clip: true
    visible: open || slide.running

    Item {
        id: panel
        width: parent.width
        height: parent.height
        y: sheet.open ? 0 : height
        Behavior on y {
            NumberAnimation {
                id: slide
                duration: Theme.reducedMotion ? 0 : Theme.motion.base
                easing.type: Easing.BezierSpline
                easing.bezierCurve: Theme.motion.baseCurve
            }
        }

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

        // 吃掉点击（避免穿透到舞台触发暂停）；滚轮转成「翻本剧上下集」交给播放页。
        // 进了选集面板就是「本剧模式」，这时滚动不再换剧。
        MouseArea {
            id: sheetWheel
            anchors.fill: parent
            property real wheelAccum: 0
            onWheel: wheel => {
                wheel.accepted = true
                // 鼠标滚轮每格 120；触控板惯性滚动按像素累计，超过 120 才翻一集
                wheelAccum += wheel.pixelDelta.y !== 0 ? wheel.pixelDelta.y : wheel.angleDelta.y
                if (Math.abs(wheelAccum) >= 120) {
                    sheet.wheelStep(wheelAccum < 0 ? 1 : -1)
                    wheelAccum = 0
                }
                wheelReset.restart()
            }
            Timer { id: wheelReset; interval: 300; onTriggered: sheetWheel.wheelAccum = 0 }
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
