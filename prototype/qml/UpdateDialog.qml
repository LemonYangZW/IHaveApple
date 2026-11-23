import QtQuick
import IHaveApple 1.0

// 更新提示：发现新版本时盖在画面上，问要不要下载；下载完成后自动安装并退出播放器。
// 视频在下面继续播放。点遮罩 / Esc =「稍后」（下载中则取消下载）。
Item {
    id: dlg

    property bool open: false
    readonly property bool busy: Updater.state === "downloading" || Updater.state === "installing"
    function show() { open = true }
    function close() {
        if (Updater.state === "installing") return
        if (Updater.state === "downloading") Updater.cancel()
        open = false
    }

    visible: opacity > 0
    opacity: open ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Theme.reducedMotion ? 0 : Theme.motion.base } }

    Rectangle {
        anchors.fill: parent
        color: Theme.color.scrim
        // 吃掉点击和滚轮，避免穿透到舞台；点空白处 =「稍后」
        MouseArea {
            anchors.fill: parent
            onWheel: wheel => wheel.accepted = true
            onClicked: if (!dlg.busy) dlg.close()
        }
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(360, parent.width - Theme.space.md * 2)
        height: body.implicitHeight + Theme.space.lg * 2
        radius: Theme.radius.lg
        color: Theme.color.wing
        border.width: 1
        border.color: Theme.color.line
        MouseArea { anchors.fill: parent }      // 卡片上的点击不算「点空白处」

        Column {
            id: body
            x: Theme.space.lg
            y: Theme.space.lg
            width: parent.width - Theme.space.lg * 2
            spacing: Theme.space.sm

            Label { width: parent.width; role: Theme.type.h2; text: "发现新版本 " + Updater.latestVersion }
            Label {
                width: parent.width
                role: Theme.type.caption
                color: Theme.color.aside
                text: "当前版本 " + Updater.version
            }
            Flickable {
                visible: Updater.notes !== ""
                width: parent.width
                height: Math.min(notes.implicitHeight, 160)
                contentHeight: notes.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Label {
                    id: notes
                    width: parent.width
                    role: Theme.type.caption
                    color: Theme.color.subtitle70
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                    text: Updater.notes
                }
            }

            // 下载进度
            Column {
                visible: dlg.busy
                width: parent.width
                spacing: Theme.space.xxs
                Rectangle {
                    width: parent.width
                    height: 4
                    radius: 2
                    color: Theme.color.proscenium
                    Rectangle {
                        width: parent.width * Updater.progress
                        height: parent.height
                        radius: parent.radius
                        color: Theme.color.crabapple
                    }
                }
                Label {
                    width: parent.width
                    role: Theme.type.caption
                    color: Theme.color.aside
                    text: Updater.state === "installing" ? "正在启动安装程序，播放器将自动关闭并在更新后重新打开…"
                        : "正在下载 " + Math.floor(Updater.progress * 100) + "%"
                }
            }
            Label {
                visible: !dlg.busy
                width: parent.width
                role: Theme.type.caption
                color: Theme.color.aside
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                text: "下载完成后会自动安装到当前目录，播放器会关闭并在更新后重新打开。"
            }

            Row {
                anchors.right: parent.right
                spacing: Theme.space.xs
                topPadding: Theme.space.xs
                IhaButton {
                    text: Updater.state === "downloading" ? "取消" : "稍后"
                    enabled: Updater.state !== "installing"
                    onClicked: dlg.close()
                }
                IhaButton {
                    visible: !dlg.busy
                    variant: "primary"
                    text: "下载并更新"
                    onClicked: Updater.download(Store.prefs.updateChannel)
                }
            }
        }
    }
}
