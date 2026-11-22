import QtQuick
import QtQuick.Effects

// 集号字幕卡：淡入 160ms → 停留 1200ms → 淡出 240ms；减少动画时直接显示 / 消失
Label {
    id: card

    function show(ep) {
        text = "第 " + (ep + 1) + " 集"
        fullAnim.stop()
        reducedAnim.stop()
        Theme.reducedMotion ? reducedAnim.start() : fullAnim.start()
    }

    role: Theme.type.card
    elide: Text.ElideNone
    opacity: 0
    visible: opacity > 0
    Accessible.ignored: true

    // 文字阴影只作用于字幕卡自身，不处理视频画面
    layer.enabled: visible
    layer.effect: MultiEffect {
        shadowEnabled: true
        shadowColor: Theme.color.stage60
        shadowBlur: 0.5
        shadowVerticalOffset: 2
    }

    SequentialAnimation {
        id: fullAnim
        NumberAnimation { target: card; property: "opacity"; to: 1; duration: Theme.motion.cardIn }
        PauseAnimation { duration: Theme.motion.cardHold }
        NumberAnimation { target: card; property: "opacity"; to: 0; duration: Theme.motion.cardOut }
    }
    SequentialAnimation {
        id: reducedAnim
        PropertyAction { target: card; property: "opacity"; value: 1 }
        PauseAnimation { duration: Theme.motion.cardHold }
        PropertyAction { target: card; property: "opacity"; value: 0 }
    }
}
