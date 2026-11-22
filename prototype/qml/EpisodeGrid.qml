import QtQuick
import QtQuick.Templates as T

// 选集方格（第 5.3 节）：每集一个按钮，每 30 集一页。
// 方格是叠在深色底上的浅色半透明块；当前集是一块海棠红实底（垫在方格下面），底部显示本集进度。
// 面板打开时切集，红块沿 motion.reel 曲线滑到新格子，
// 与视频滑动同时开始、同时结束（由播放页同时调用 Stage.transitionTo() 和 showEpisode()）。
Item {
    id: grid

    property var drama
    property int currentEp: 0
    property real position: 0
    property real duration: 1
    signal pick(int ep)

    readonly property int pageSize: 30
    readonly property int pages: drama ? Math.ceil(drama.total / pageSize) : 0
    property int page: 0

    readonly property int columns: Theme.layout.episodeColumns
    readonly property int gap: Theme.space.xs
    readonly property int cellHeight: Theme.layout.episodeCell
    readonly property real cellWidth: (width - Theme.space.md * 2 - gap * (columns - 1)) / columns
    // 按最满的一页计算高度，翻页时面板高度不跳动
    readonly property int rows: drama ? Math.ceil(Math.min(drama.total, pageSize) / columns) : 0
    readonly property int tabsHeight: pages > 1 ? Theme.layout.episodeTab : 0
    implicitHeight: tabsHeight + (pages > 1 ? Theme.space.sm : 0) + rows * (cellHeight + gap) - gap

    // 翻到该集所在的页并移动红块；只有同一页内才做滑动动画
    function showEpisode(ep, animated) {
        const p = Math.floor(ep / pageSize)
        selector.animate = animated && p === page && !Theme.reducedMotion
        page = p
        selector.ep = ep
    }

    // ---- 分页：一行胶囊，放不下时横向滚动（滚轮也可以），当前页始终滚到可见处 ----
    ListView {
        id: tabs
        x: Theme.space.md
        width: parent.width - Theme.space.md * 2
        height: grid.tabsHeight
        visible: grid.pages > 1
        orientation: ListView.Horizontal
        spacing: Theme.space.xxs
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: grid.pages
        currentIndex: grid.page
        highlightFollowsCurrentItem: false
        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Center)   // 靠边会被渐隐盖住；到头时 ListView 自动贴边

        delegate: T.AbstractButton {
            id: tab
            required property int index
            readonly property bool isCurrent: index === grid.page
            readonly property int first: index * grid.pageSize + 1
            readonly property int last: Math.min(grid.drama.total, (index + 1) * grid.pageSize)
            height: tabs.height
            width: tabLabel.implicitWidth + Theme.space.md
            Accessible.name: "第 " + first + " 到 " + last + " 集"
            onClicked: grid.page = index

            contentItem: Label {
                id: tabLabel
                role: Theme.type.caption
                tabular: true
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: tab.isCurrent || tab.hovered ? Theme.color.subtitle : Theme.color.aside
                text: tab.first + "–" + tab.last
            }
            background: Rectangle {
                radius: height / 2
                color: tab.isCurrent ? Theme.color.subtitle14 : tab.hovered ? Theme.color.subtitle08 : "transparent"
                Behavior on color { ColorAnimation { duration: Theme.motion.fast } }
                FocusRing { target: tab; targetRadius: height / 2 }
            }
        }

        // 两端渐隐：提示还有更多页
        Rectangle {
            anchors.left: parent.left
            width: Theme.space.lg
            height: parent.height
            visible: !tabs.atXBeginning
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.color.scrimDeep }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
        Rectangle {
            anchors.right: parent.right
            width: Theme.space.lg
            height: parent.height
            visible: !tabs.atXEnd
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 1.0; color: Theme.color.scrimDeep }
            }
        }
    }

    // ---- 方格 ----
    Flickable {
        id: area
        anchors.top: tabs.bottom
        anchors.topMargin: grid.pages > 1 ? Theme.space.sm : 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: Theme.space.md
        anchors.rightMargin: Theme.space.md
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: cells.height

        // 当前集红块 + 本集进度。先声明 → 画在方格下面，集号压在红块上
        Rectangle {
            id: selector
            property int ep: 0
            property bool animate: false
            readonly property int local: ep - grid.page * grid.pageSize
            visible: local >= 0 && local < grid.pageSize
            x: (local % grid.columns) * (grid.cellWidth + grid.gap)
            y: Math.floor(local / grid.columns) * (grid.cellHeight + grid.gap)
            width: grid.cellWidth
            height: grid.cellHeight
            radius: Theme.radius.md
            color: Theme.color.crabapple

            Behavior on x {
                enabled: selector.animate
                NumberAnimation { duration: Theme.motion.reel; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.motion.reelCurve }
            }
            Behavior on y {
                enabled: selector.animate
                NumberAnimation { duration: Theme.motion.reel; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.motion.reelCurve }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.leftMargin: Theme.space.sm
                anchors.rightMargin: Theme.space.sm
                anchors.bottomMargin: Theme.space.xxs
                height: 2
                radius: 1
                color: Theme.color.subtitle30
                Rectangle {
                    width: parent.width * Math.min(1, grid.position / grid.duration)
                    height: parent.height
                    radius: parent.radius
                    color: Theme.color.subtitle
                }
            }
        }

        Grid {
            id: cells
            columns: grid.columns
            spacing: grid.gap

            Repeater {
                model: grid.drama ? Math.min(grid.pageSize, grid.drama.total - grid.page * grid.pageSize) : 0
                delegate: T.AbstractButton {
                    id: cell
                    required property int index
                    readonly property int ep: grid.page * grid.pageSize + index
                    readonly property bool isCurrent: ep === grid.currentEp
                    readonly property bool watched: ep < grid.currentEp

                    width: grid.cellWidth
                    height: grid.cellHeight
                    Accessible.name: "第 " + (ep + 1) + " 集" + (watched ? "，已看" : isCurrent ? "，正在播放" : "")
                    onClicked: grid.pick(ep)

                    // 当前集的底色由红块提供，这里保持透明
                    background: Rectangle {
                        radius: Theme.radius.md
                        color: cell.isCurrent ? "transparent"
                             : cell.hovered ? Theme.color.subtitle14
                             : Theme.color.subtitle08
                        Behavior on color { ColorAnimation { duration: Theme.motion.fast } }
                        FocusRing { target: cell }
                    }
                    contentItem: Label {
                        role: Theme.type.episode
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideNone
                        text: cell.ep + 1
                        color: cell.isCurrent ? Theme.color.subtitle
                             : cell.watched ? Theme.color.aside
                             : Theme.color.subtitle
                    }
                }
            }
        }
    }
}
