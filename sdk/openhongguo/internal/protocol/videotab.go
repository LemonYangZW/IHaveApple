package protocol

import (
	"strconv"
)

// PathVideoTab 是取流接口：一次 GET 直接返回播放模型（data.video_model_data）。
const PathVideoTab = "/reading/bookapi/video_tab/multi_video_model/v1/"

// VideoTabPairs 是 video_tab 的查询参数，顺序照 2026-11-25 可见客户端的实际请求排。
// 顺序和集合都参与签名，缺字段会被服务端当成异常请求回空体。
func VideoTabPairs(episodeID string, id SearchIdentity) [][2]string {
	d := id.Device.OrDefault()
	kind, pad := "phone", "0"
	if d.Pad {
		kind, pad = "pad", "1"
	}
	version := strconv.Itoa(PlaybackVersionCode)
	return [][2]string{
		{"device_platform", DevicePlatform},
		{"os", "android"},
		{"ssmix", "a"},
		{"channel", d.Channel},
		{"aid", AID},
		{"app_name", AppName},
		{"version_code", version},
		{"version_name", PlaybackVersionName},
		{"manifest_version_code", version},
		{"update_version_code", version},
		{"pv_player", version},
		{"resolution", d.Resolution},
		{"dpi", strconv.Itoa(d.DPI)},
		{"device_type", d.Model},
		{"device_brand", d.Brand},
		{"language", "zh"},
		{"os_api", strconv.Itoa(d.OSAPI)},
		{"os_version", d.OSVersion},
		{"ac", "wifi"},
		{"rom_version", d.Build},
		{"klink_egdi", id.KlinkEGDI},
		{"iid", id.InstallID},
		{"device_id", id.DeviceID},
		{"host_abi", "arm64-v8a"},
		{"dragon_device_type", kind},
		{"compliance_status", "0"},
		{"need_personal_recommend", "1"},
		{"player_so_load", "1"},
		{"is_android_pad_screen", pad},
		{"cdid", id.CDID},
		{"video_id", episodeID},
		{"video_id_type", "0"},
		{"device_level", "1"},
		{"need_all_video_definition", "1"},
		{"need_mp4_align", "0"},
		{"use_os_player", "0"},
		{"video_platform", "1024"},
		{"source", "0"},
		{"from_video_id", ""},
	}
}
