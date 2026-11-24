pragma Singleton
import QtQuick

// 设计 Token —— 与 docs/windows-ui-design.md 第 3 节一一对应。
// 组件中禁止出现色值 / 字号 / 间距字面量，一律从这里取。
QtObject {
    id: theme

    // 由 Main.qml 根据系统「动画效果」设置写入
    property bool reducedMotion: false

    readonly property QtObject color: QtObject {
        readonly property color curtain: "#141016"
        readonly property color wing: "#1F1922"
        readonly property color proscenium: "#2A2230"
        readonly property color line: "#3A3040"
        readonly property color subtitle: "#F3EDE6"
        readonly property color aside: "#9A8F9C"
        readonly property color crabapple: "#E8436A"
        readonly property color crabappleDeep: "#C42A52"
        readonly property color stage: "#000000"
        readonly property color danger: "#FF7A6B"
        readonly property color scrim: Qt.rgba(20 / 255, 16 / 255, 22 / 255, 0.72)
        // 叠在画面上的深色底（选集面板 + 面板打开时的控件栏）：幕布色 94%：亮画面（如加载时的封面）也不会透出来干扰集号；与画面的过渡靠面板顶部的渐变
        readonly property color scrimDeep: Qt.rgba(20 / 255, 16 / 255, 22 / 255, 0.94)
        // 由 subtitle 派生的透明度变体（不是新颜色）
        readonly property color subtitle08: Qt.rgba(243 / 255, 237 / 255, 230 / 255, 0.08)
        readonly property color subtitle14: Qt.rgba(243 / 255, 237 / 255, 230 / 255, 0.14)
        readonly property color subtitle25: Qt.rgba(243 / 255, 237 / 255, 230 / 255, 0.25)
        readonly property color subtitle30: Qt.rgba(243 / 255, 237 / 255, 230 / 255, 0.30)
        readonly property color subtitle70: Qt.rgba(243 / 255, 237 / 255, 230 / 255, 0.70)
        readonly property color stage60: Qt.rgba(0, 0, 0, 0.6)
    }

    readonly property QtObject font: QtObject {
        readonly property string display: "Smiley Sans"
        readonly property string ui: "HarmonyOS Sans SC"
    }

    // 字号阶梯：size / line / weight
    readonly property QtObject type: QtObject {
        readonly property var card:    ({ family: "Smiley Sans", size: 56, line: 56, weight: Font.Normal })
        readonly property var episode: ({ family: "Smiley Sans", size: 18, line: 24, weight: Font.Normal })
        readonly property var h1:      ({ family: "HarmonyOS Sans SC", size: 22, line: 30, weight: Font.DemiBold })
        readonly property var h2:      ({ family: "HarmonyOS Sans SC", size: 17, line: 24, weight: Font.DemiBold })
        readonly property var body:    ({ family: "HarmonyOS Sans SC", size: 14, line: 22, weight: Font.Normal })
        readonly property var label:   ({ family: "HarmonyOS Sans SC", size: 14, line: 20, weight: Font.Medium })
        readonly property var caption: ({ family: "HarmonyOS Sans SC", size: 12, line: 18, weight: Font.Normal })
        readonly property var mono:    ({ family: "HarmonyOS Sans SC", size: 12, line: 16, weight: Font.Medium })
    }

    // 间距：4 · 8 · 12 · 16 · 24 · 32 · 48
    readonly property QtObject space: QtObject {
        readonly property int xxs: 4
        readonly property int xs: 8
        readonly property int sm: 12
        readonly property int md: 16
        readonly property int lg: 24
        readonly property int xl: 32
        readonly property int xxl: 48
    }

    readonly property QtObject radius: QtObject {
        readonly property int sm: 4
        readonly property int md: 8
        readonly property int lg: 12
        readonly property int pill: 999
        readonly property int video: 0
    }

    readonly property QtObject motion: QtObject {
        readonly property int fast: 120
        readonly property int base: 200
        readonly property int reel: 280
        readonly property var reelCurve: [0.2, 0.8, 0.2, 1, 1, 1]
        readonly property var baseCurve: [0.2, 0, 0, 1, 1, 1]
        readonly property int cardIn: 160
        readonly property int cardHold: 1200
        readonly property int cardOut: 240
        readonly property int controlsIdle: 2500      // 默认值；用户可在设置页修改（Store.prefs.controlsIdle）
        readonly property int crossfade: 120
    }

    // 布局常量（第 4 节）
    readonly property QtObject layout: QtObject {
        readonly property int titleBar: 40
        readonly property int channelBar: 32          // 顶部频道 tab 行高
        readonly property real episodeSheet: 0.6      // 选集面板最多占舞台高度的比例
        readonly property int controlsBar: 56         // 进度条 + 按钮行
        readonly property int episodeCell: 40         // 选集方格高度（宽度按列数均分）
        readonly property int episodeFade: 40         // 选集面板顶部从透明过渡到 scrimDeep 的高度
        readonly property int episodeTab: 28          // 选集分页胶囊的高度
        readonly property int episodeColumns: 6
        readonly property real libraryPanel: 0.7      // 搜索 / 历史面板最多占窗口高度的比例
        readonly property int dramaRow: 88
        readonly property int coverThumb: 72          // 封面缩略图高度（宽 = 高 × 3/4）
        readonly property int settingsWidth: 560      // 设置页内容最大宽度（「适应屏幕高度」后窗口较宽时居中）
        readonly property int button: 36
        readonly property int iconButton: 32
        readonly property int centerPlay: 64          // 暂停时画面中央的播放按钮直径
        readonly property int dramaInfo: 92           // 底部剧名 + 简介信息区高度
        readonly property int swipe: 60               // 画面上拖动画卷超过这个距离，松手翻到上 / 下一个
        readonly property real swipeVelocity: 0.5     // 拖得不够远但松手时速度 ≥ 此值（逻辑像素 / 毫秒）也算翻过去
    }

    // Segoe Fluent Icons（Win11）/ Segoe MDL2 Assets（Win10）
    readonly property QtObject icon: QtObject {
        readonly property string family: Qt.fontFamilies().indexOf("Segoe Fluent Icons") >= 0
                                         ? "Segoe Fluent Icons" : "Segoe MDL2 Assets"
        readonly property string play: String.fromCharCode(0xE768)
        readonly property string pause: String.fromCharCode(0xE769)
        readonly property string volume: String.fromCharCode(0xE767)
        readonly property string mute: String.fromCharCode(0xE74F)
        readonly property string fullscreen: String.fromCharCode(0xE740)
        readonly property string exitFullscreen: String.fromCharCode(0xE73F)
        readonly property string episodes: String.fromCharCode(0xE8FD)
        readonly property string minimize: String.fromCharCode(0xE921)
        readonly property string maximize: String.fromCharCode(0xE922)
        readonly property string restore: String.fromCharCode(0xE923)
        readonly property string close: String.fromCharCode(0xE8BB)
        readonly property string back: String.fromCharCode(0xE72B)
        readonly property string check: String.fromCharCode(0xE73E)
        readonly property string info: String.fromCharCode(0xE946)
        readonly property string refresh: String.fromCharCode(0xE72C)
        readonly property string search: String.fromCharCode(0xE721)
        readonly property string history: String.fromCharCode(0xE81C)
        // 收藏：空心星 / 实心星（已收藏）；标题栏的收藏夹入口用空心星
        readonly property string favorite: String.fromCharCode(0xE734)
        readonly property string favoriteFill: String.fromCharCode(0xE735)
        // 对话气泡：控件栏的弹幕开关（开着时海棠红）
        readonly property string danmaku: String.fromCharCode(0xE8BD)
        readonly property string settings: String.fromCharCode(0xE713)
        // 方框 + 四角标记：窗口按视频源比例适配
        readonly property string fitVideo: String.fromCharCode(0xE9A6)
    }
}
