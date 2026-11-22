# 本目录的来源与改动

本目录是 [beilunyang/openhongguo](https://github.com/beilunyang/openhongguo)（Apache License 2.0，见 `LICENSE`）
在提交 `33c888d` 时的部分源码，只保留 `ohgd` 编译需要的 Go 包：`adapters/`、`internal/`、`sdk/`。
没有收录 `signer/`、`bindings/`、`docs/`、`testdata/`、`cmd/`。

本项目做过的改动：

- `sdk/model/device.go`：默认渠道号 `xiaomi_8662_64` 改为 `69310258a`。渠道号带下划线时，播放接口会返回 HTTP 200 加 0 字节的空响应。
