import QtQuick
import QtQuick.Templates as T
import "Fmt.js" as Fmt

// 播放控件浮层（第 5.2 节）：静态渐变遮罩，无模糊
Item {
    id: controls

    property bool playing: true
    property real position: 0
    property real duration: 1
    property bool immersive: false
    property bool episodesOpen: false
    property bool fitVideo: false        // 窗口是否已按视频比例适配
    property bool favorite: false        // 当前这部剧已收藏

    readonly property bool menuOpen: speedMenu.opened || qualityMenu.opened
    function closeMenus() { speedMenu.close(); qualityMenu.close() }

    signal togglePlay()
    signal seek(real seconds)
    signal toggleImmersive()
    signal toggleEpisodes()
    signal toggleFitVideo()
    signal toggleFavorite()

    height: 96

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 1.0; color: Theme.color.stage60 }
        }
    }
    // 选集面板打开时铺上与面板相同的底色，两者连成一片（面板压在本控件上沿，从 controlsBar 高度往下铺）
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Theme.layout.controlsBar
        color: Theme.color.scrimDeep
        opacity: controls.episodesOpen ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.reducedMotion ? 0 : Theme.motion.base } }
    }

    ProgressSlider {
        id: progress
        objectName: "progressSlider"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: buttons.top
        anchors.leftMargin: Theme.space.sm
        anchors.rightMargin: Theme.space.sm
        value: controls.position / controls.duration
        buffered: (controls.position + 20) / controls.duration
        onSeek: v => controls.seek(v * controls.duration)
    }

    Item {
        id: buttons
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Theme.space.xs
        height: Theme.layout.iconButton

        Row {
            anchors.left: parent.left
            height: parent.height
            spacing: Theme.space.xxs
            IconButton {
                glyph: controls.playing ? Theme.icon.pause : Theme.icon.play
                tip: (controls.playing ? "暂停" : "播放") + Store.tipKey("playPause")
                onClicked: controls.togglePlay()
            }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                role: Theme.type.mono
                // 拖动进度条时显示手柄所在的时间
                readonly property real at: progress.dragging ? progress.dragValue * controls.duration : controls.position
                // 舞台很窄时只显示当前时间，避免和右侧按钮挤在一起
                text: controls.width < 340 ? Fmt.timecode(at)
                      : Fmt.timecode(at) + " / " + Fmt.timecode(controls.duration)
            }
        }

        Row {
            anchors.right: parent.right
            height: parent.height
            spacing: Theme.space.xxs

            // 收藏：信息流和全剧界面都在这里，收藏的剧在标题栏「收藏夹」里点开即续播
            IconButton {
                objectName: "favoriteButton"
                glyph: controls.favorite ? Theme.icon.favoriteFill : Theme.icon.favorite
                tip: (controls.favorite ? "取消收藏" : "收藏") + Store.tipKey("favorite")
                active: controls.favorite
                onClicked: controls.toggleFavorite()
            }
            // 弹幕开关：开着时海棠红（与设置页「显示弹幕」是同一项）
            IconButton {
                objectName: "danmakuButton"
                glyph: Theme.icon.danmaku
                tip: (Store.prefs.danmaku ? "关闭弹幕" : "开启弹幕") + Store.tipKey("danmaku")
                active: Store.prefs.danmaku
                onClicked: Store.toggleDanmaku()
            }
            // 选集：打开选集面板
            IconButton {
                objectName: "episodesButton"
                glyph: Theme.icon.episodes
                tip: "选集" + Store.tipKey("episodes")
                active: controls.episodesOpen
                onClicked: controls.toggleEpisodes()
            }
            TextControl {
                id: speedButton
                objectName: "speedButton"
                text: Fmt.speed(Store.speed)
                tip: "倍速" + (Store.keys.speedDown && Store.keys.speedUp ? " (" + Store.keyText(Store.keys.speedDown) + " / " + Store.keyText(Store.keys.speedUp) + ")" : "")
                onClicked: speedMenu.opened ? speedMenu.close() : speedMenu.open()
                SelectMenu {
                    id: speedMenu
                    y: -height - Theme.space.xs
                    x: (parent.width - width) / 2
                    options: Store.speeds
                    current: Store.speed
                    format: v => Fmt.speed(v)
                    onPicked: v => Store.speed = v
                }
            }
            TextControl {
                text: Store.quality
                tip: "画质"
                onClicked: qualityMenu.opened ? qualityMenu.close() : qualityMenu.open()
                SelectMenu {
                    id: qualityMenu
                    y: -height - Theme.space.xs
                    x: (parent.width - width) / 2
                    options: Store.qualities
                    current: Store.quality
                    onPicked: v => Store.quality = v
                }
            }
            IconButton {
                glyph: Store.muted || Store.volume === 0 ? Theme.icon.mute : Theme.icon.volume
                tip: Store.muted ? "取消静音" + Store.tipKey("mute") : "音量 " + Math.round(Store.volume * 100) + "%（在图标上滚动滚轮调节）"
                onClicked: Store.muted = !Store.muted
                WheelHandler {
                    onWheel: event => {
                        Store.volume = Math.max(0, Math.min(1, Store.volume + (event.angleDelta.y > 0 ? 0.05 : -0.05)))
                        Store.muted = false
                    }
                }
            }
            IconButton {
                glyph: controls.immersive ? Theme.icon.exitFullscreen : Theme.icon.fullscreen
                tip: (controls.immersive ? "退出全屏" : "全屏") + Store.tipKey("fullscreen")
                onClicked: controls.toggleImmersive()
            }
            // 窗口适配视频比例：横屏片源在 9:16 窗口里会大面积留黑，点这里把窗口套成片源比例
            IconButton {
                objectName: "fitVideoButton"
                glyph: Theme.icon.fitVideo
                tip: controls.fitVideo ? "恢复 9:16 窗口" : "窗口适配视频比例"
                active: controls.fitVideo
                onClicked: controls.toggleFitVideo()
            }
        }
    }

    // 控件栏里的文字按钮（倍速、画质）
    component TextControl: T.AbstractButton {
        id: tc
        property string tip
        height: Theme.layout.iconButton
        width: Math.max(44, tcLabel.implicitWidth + Theme.space.md)
        Accessible.name: tip + " " + text
        background: Rectangle {
            radius: Theme.radius.md
            color: Theme.color.subtitle
            opacity: tc.hovered ? 0.08 : 0
            FocusRing { target: tc }
        }
        contentItem: Label {
            id: tcLabel
            role: Theme.type.label
            tabular: true
            horizontalAlignment: Text.AlignHCenter
            color: tc.hovered ? Theme.color.subtitle : Theme.color.aside
            text: tc.text
        }
        Tip { text: tc.tip; visible: tc.hovered }
    }
}
