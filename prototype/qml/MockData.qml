pragma Singleton
import QtQuick
import IHaveApple 1.0

// 数据源：本地 SDK（Backend.dramas）。加载完成前用占位，保证界面不空。
// covers 是「封面美术占位」的两种主色，属于内容而非 UI 色板。
QtObject {
    readonly property var placeholder: [
        { id: "loading", title: "正在载入…", total: 1, covers: ["#2A2230", "#3A3040"] }
    ]

    readonly property var dramas: Backend.dramas.length > 0 ? Backend.dramas : placeholder

    // 演示用台词，模拟视频内嵌字幕
    readonly property var subtitles: [
        "你以为，我还是三年前那个任人欺负的人吗？",
        "从今天开始，属于我的东西，我会一样一样拿回来。",
        "这份合同，你签也得签，不签也得签。",
        "我早就知道是你。",
        "如果我说，我从来没有忘记过你呢？",
        "跪下道歉，我可以考虑放你一马。"
    ]

    function drama(id) {
        for (let i = 0; i < dramas.length; ++i)
            if (String(dramas[i].id) === String(id)) return dramas[i]
        // 启动参数 --drama 用的是 1 起的序号（演示数据 1–9），真实 id 都是 19 位数字，
        // 所以纯小数字的 id 命中不了上面时按序号取
        const n = Number(id)
        if (Number.isInteger(n) && n >= 1 && n <= dramas.length) return dramas[n - 1]
        // id 无效（首屏还没决定播哪部）：跟随推荐，不要退化成一成不变的第一部
        const rec = String(Backend.recommendId)
        if (rec) {
            for (let i = 0; i < dramas.length; ++i)
                if (String(dramas[i].id) === rec) return dramas[i]
        }
        return dramas[0]
    }

    // 单集时长（秒）：来自播放模型，未知时用 90 秒兜底
    function duration(dramaId, ep) {
        const d = Backend.durationOf(String(dramaId), ep)
        return d > 0 ? d : 90
    }
}
