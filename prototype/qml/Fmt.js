.pragma library

// 秒 → "01:12"
function timecode(sec) {
    const s = Math.max(0, Math.floor(sec))
    const m = Math.floor(s / 60)
    const r = s % 60
    return (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r
}

// 1 → "1.0x"，1.25 → "1.25x"
function speed(v) {
    return (v % 1 === 0 ? v.toFixed(1) : String(v)) + "x"
}
