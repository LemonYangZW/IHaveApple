package sign

import (
	"fmt"
	"time"
)

// VideoTab 是取流用的 video_tab 请求（2026-11-25 由可见客户端抓包对齐）。
// 服务端只校验 x-medusa：它的消息体必须与查询串一致，否则回 200 空体。
type VideoTabDevice struct {
	AppVersion string
	Channel    string
	Model      string
	Brand      string
}

type videoTabMsg struct {
	DeviceID string
	Nonce    string
	Version  string
	Channel  string
	Model    string
	Brand    string
	TS       uint32
	MsgRand  int64
	Digest   []byte
	Sm3      []byte
	Counters []byte
	Env13    []byte
	DevT1    int64
	DevT2    int64
}

var videoTabFlags = []byte{0x44, 0x80, 0, 0, 0, 0, 0, 0}

// 计数器与环保留可见客户端的取值：服务端只校验它们与设备形状自洽，
// 不要求与真机逐字节一致（MiniReel 也是自己造的）。
var videoTabCounters = []byte{0x08, 0xe2, 0x04, 0x10, 0x08, 0x18, 0xbe, 0xe1, 0x54, 0x28, 0xc4, 0xec, 0xfc, 0x89, 0x0c}
var videoTabEnv13 = []byte{0x08, 0xd0, 0xdd, 0xb3, 0xb0, 0x0d, 0x10, 0x03, 0x20, 0x90, 0x03}

func buildVideoTabMessage(m videoTabMsg) []byte {
	dev := concat(
		protoSInt(1, 1), protoSInt(2, 2), protoString(3, appID), protoString(4, m.DeviceID),
		protoString(5, m.Nonce), protoString(6, noPerm),
		protoSInt(7, noPermInt), protoSInt(8, noPermInt), protoSInt(9, 3), protoSInt(10, noPermInt),
		protoString(11, notSet), protoString(12, "Asia/Shanghai,8"), protoString(13, "zh_CN"),
		protoSInt(14, 4),
		protoFloat(16, 0), protoFloat(17, 0), protoFloat(18, 0), protoFloat(19, 0), protoFloat(20, 0), protoFloat(21, 0),
		protoString(22, "12"), protoSInt(23, 41), protoSInt(24, 36),
		protoSInt(25, m.DevT1), protoSInt(26, m.DevT1), protoSInt(27, m.DevT1), protoSInt(28, m.DevT2), protoSInt(29, -1),
		protoString(30, m.Model), protoString(31, m.Brand), protoString(32, m.Model), protoString(33, m.Model),
		protoString(34, m.Brand), protoString(35, m.Brand), protoString(36, m.Brand), protoSInt(38, 31),
	)
	env := concat(
		protoSInt(1, 104), protoSInt(2, 247235599), protoSInt(3, 247235596), protoSInt(5, 7),
		protoString(6, "v04.10.03.04-bugfix"), protoSInt(7, 10482), protoString(8, m.Channel),
		protoBytes(12, dev), protoBytes(13, videoTabEnv13), protoString(14, m.Version),
	)
	return concat(
		protoBytes(1, playbackV5Magic),
		protoSInt(2, 5),
		protoSInt(3, m.MsgRand),
		protoString(4, appID),
		protoString(5, m.DeviceID),
		protoString(6, playbackV5License),
		protoString(7, m.Version),
		protoString(8, medusaV5SDKVersion),
		protoSInt(9, medusaV5SDKCode),
		protoBytes(10, videoTabFlags),
		protoSInt(12, int64(m.TS)),
		protoBytes(13, m.Digest),
		protoBytes(14, m.Sm3),
		protoBytes(15, m.Counters),
		protoString(16, m.Nonce),
		protoSInt(17, int64(m.TS)),
		protoString(20, "none"),
		protoSInt(21, 312),
		protoBytes(23, env),
		protoString(24, `{"cmr":16777216,"cmr2":16777216,"un_h":11,"vpn":0,"kd":0,"dyn":"","do":1,"tk":true}`),
	)
}

// SignVideoTab 为 video_tab 的查询串生成整套签名头（x-gorgon/argus/ladon + x-medusa/helios）。
// 返回实际要发送的查询串（含 _rticket）。
func SignVideoTab(pairs [][2]string, nowMillis int64, deviceID, versionName string, dev VideoTabDevice) (string, map[string]string, error) {
	device := dev
	if device.AppVersion == "" {
		device.AppVersion = versionName
	}
	var query string
	var headers map[string]string
	var in medusaV5Input
	ok := false
	for attempt := int64(0); attempt < 64 && !ok; attempt++ {
		query, headers = SignPOST("/reading/bookapi/video_tab/multi_video_model/v1/", pairs,
			nowMillis+attempt*1000, deviceID, versionName, nil, nil)
		rt := queryValue(query, "_rticket")
		var ms int64
		fmt.Sscanf(rt, "%d", &ms)
		in, ok = newMedusaV5Input(query, nil, uint32(ms/1000))
	}
	if !ok {
		return "", nil, fmt.Errorf("video_tab: no supported digest variant")
	}
	nonce := randomVideoTabNonce(25)
	msg := buildVideoTabMessage(videoTabMsg{
		DeviceID: deviceID, Nonce: nonce, Version: versionName,
		Channel: device.Channel, Model: device.Model, Brand: device.Brand,
		TS: in.ts, MsgRand: int64(time.Now().UnixNano() & 0x7fffffff),
		Digest: in.digest[:], Sm3: in.querySM3[:6], Counters: videoTabCounters,
		DevT1: int64(in.ts)*1000 - 2023, DevT2: int64(in.ts)*1000 + 48,
	})
	ent := drawEntropy(int64(in.ts) * 1000)
	headers["x-medusa"] = sealMedusaV5(msg, in, ent.medusaRandom(), videoTabFlags)
	headers["x-helios"] = heliosV5(in.ts, ent.HeliosRandom)
	headers["x-khronos"] = fmt.Sprintf("%d", in.ts)
	return query, headers, nil
}

func randomVideoTabNonce(n int) string {
	const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
	ent := drawEntropy(time.Now().UnixNano())
	seed := uint64(ent.MessageRandom)<<32 | uint64(ent.Random)
	out := make([]byte, n)
	for i := 0; i < n; i++ {
		seed = seed*6364136223846793005 + 1442695040888963407
		out[i] = alphabet[(seed>>33)%uint64(len(alphabet))]
	}
	return string(out)
}
