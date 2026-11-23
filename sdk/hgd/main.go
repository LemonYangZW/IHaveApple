// ohgd — openhongguo 本地守护服务
//
// 把红果短剧的匿名读取、签名、媒体参数处理全部封在服务端，对外只暴露 HTTP。
// 客户端（Windows 桌面抖音式播放器）只需要播 /v1/stream/ 返回的 URL。
//
// 设计要点：
//   - 上游是 CENC-AES-CTR 加密 HEVC（hvc1），无 pssh，key 由 SDK 本地解包得出
//   - 媒体参数处理交给 `ffmpeg -decryption_key`，`-c copy` 不转码，仅做 AES-NI 运算，CPU 开销很低
//   - 缓存就绪后走标准 mp4 文件（支持 Range → 播放器可任意 seek）
//   - 缓存未就绪时走 fragmented mp4 实时流（首帧快，不可 seek）
//   - /v1/cache/prewarm/ 供客户端提前预热下一集，做到滑动即播
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/beilunyang/openhongguo/adapters"
	"github.com/beilunyang/openhongguo/sdk"
	"github.com/beilunyang/openhongguo/sdk/model"
)

var (
	// A 类：服务端地址参数
	apiOrigin      = flag.String("api-origin", "", "API 地址参数，空=内置 api5-normal-sinfonlinea.fqnovel.com")
	registerOrigin = flag.String("register-origin", "", "注册地址参数，空=内置 log5-applog-lq.fqnovel.com")
	distOrigin     = flag.String("distribution-origin", "", "分发地址参数，空=跟随 api-origin（勿设为 reading.snssdk.com）")
	signerURL      = flag.String("signer-url", "", "外部签名服务地址，空=内置签名实现")
	signerToken    = flag.String("signer-token", "", "签名服务鉴权 token")

	// B 类：本地运行参数
	addr       = flag.String("addr", "127.0.0.1:8899", "监听地址（播放器连这个）")
	profile    = flag.String("profile", "anonymous.json", "匿名设备档案路径")
	ffmpegBin  = flag.String("ffmpeg", "ffmpeg", "ffmpeg 可执行文件")
	cacheDir   = flag.String("cache", "./cache", "明文缓存目录")
	quality    = flag.String("quality", "1080p", "默认拉流清晰度")
	maxCacheMB = flag.Int("max-cache-mb", 2048, "缓存上限（MB），超出按最旧删除，0=不限")
	channel    = flag.String("channel", "真人剧", "默认 feed 频道")
	warmWork   = flag.Int("warm", 3, "feed 时后台预热前 N 条")
	exposeKey  = flag.Bool("expose-key", false, "是否在 /v1/play 响应里返回 content_key")
	configPath = flag.String("config", "config.json", "配置文件路径，不存在则忽略")
	padMode    = flag.Bool("pad", false, "以平板（PAD）设备身份注册（dragon_device_type=pad）")
)

// ---------- 应用 ----------

type app struct {
	cl    *sdk.Client
	ff    string
	cache string

	mu       sync.Mutex
	warming  map[string]bool // 正在预热/流式的集
	lastFeed []feedItem
}

type feedItem struct {
	ID           string `json:"id"`
	Title        string `json:"title"`
	Description  string `json:"description,omitempty"`
	CoverURL     string `json:"cover_url,omitempty"`
	EpisodeCount int    `json:"episode_count,omitempty"`
}

type episodeItem struct {
	ID       string  `json:"id"`
	SeriesID string  `json:"series_id"`
	Number   int     `json:"number"`
	Title    string  `json:"title,omitempty"`
	Duration float64 `json:"duration_seconds,omitempty"`
	Playable bool    `json:"playable"`
	Vertical bool    `json:"vertical,omitempty"`
	CoverURL string  `json:"cover_url,omitempty"`
}

type qualityItem struct {
	Definition string `json:"definition"`
	Width      int    `json:"width"`
	Height     int    `json:"height"`
	Bitrate    int64  `json:"bitrate,omitempty"`
	Size       int64  `json:"size,omitempty"`
	Codec      string `json:"codec,omitempty"`
	Encryption string `json:"encryption,omitempty"`
}

type playResponse struct {
	EpisodeID   string        `json:"episode_id"`
	SeriesID    string        `json:"series_id,omitempty"`
	Duration    float64       `json:"duration_seconds"`
	Protected   bool          `json:"protected"`
	ExpiresAt   int64         `json:"expires_at,omitempty"`
	Definition  string        `json:"definition,omitempty"`
	Width       int           `json:"width,omitempty"`
	Height      int           `json:"height,omitempty"`
	StreamURL   string        `json:"stream_url"`
	UpstreamURL string        `json:"upstream_url,omitempty"`
	ContentKey  string        `json:"content_key,omitempty"`
	KeyVersion  string        `json:"key_version,omitempty"`
	Cached      bool          `json:"cached"`
	Qualities   []qualityItem `json:"qualities,omitempty"`
}

// padDevice 是平板身份的匿名注册档案（Xiaomi Pad 5 / Android 11）。
// 打开 Pad 后，注册与后续请求都带 dragon_device_type=pad、is_android_pad_screen=1，
// User-Agent 和播放接口的 kind 字段也按平板下发。
// 只影响之后新注册的档案；已有档案保留注册时的设备。
func padDevice() model.Device {
	d := model.DefaultDevice
	d.Model = "2612CRPFFC"
	d.OSVersion = "17"
	d.OSAPI = 37
	d.Build = "CP2A.260605.016"
	d.Resolution = "2136*3200"
	d.DPI = 400
	d.Pad = true
	return d
}

// localSignerURL 是 signer/ 里 docker-compose 默认映射到的本机签名服务地址。
const localSignerURL = "http://127.0.0.1:19830"

// resolveSigner 决定请求签名交给内置实现还是本机签名服务：
// signer-url 显式给了就用它，写成 none/off 强制用内置签名；
// 留空时探测本机 19830 端口，探到就用，探不到静默回内置签名——播放接口目前
// 只对「解不出来的」x-medusa 放行（见 sdk/media.go 的 degradePlaybackMedusa），
// 所以签名服务只影响目录请求，缺了它也不影响起播。
func resolveSigner() {
	switch strings.ToLower(strings.TrimSpace(*signerURL)) {
	case "none", "off", "builtin", "内置":
		*signerURL = ""
		log.Printf("请求签名：内置实现（signer-url 已禁用）")
		return
	case "":
	default:
		log.Printf("请求签名：%s", *signerURL)
		return
	}
	cl := &http.Client{Timeout: 300 * time.Millisecond}
	resp, err := cl.Get(localSignerURL + "/ready")
	if err != nil {
		log.Printf("请求签名：内置实现（本机未运行签名服务）")
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
	if resp.StatusCode == 200 && strings.Contains(string(body), `"ready":true`) {
		*signerURL = localSignerURL
		log.Printf("请求签名：本机签名服务 %s", localSignerURL)
		return
	}
	log.Printf("请求签名：内置实现（本机签名服务未就绪）")
}

func main() {
	flag.Parse()
	applyConfig(*configPath)

	if _, err := exec.LookPath(*ffmpegBin); err != nil {
		log.Fatalf("找不到 ffmpeg（%s）：%v\n提示：scoop install ffmpeg", *ffmpegBin, err)
	}
	if err := os.MkdirAll(*cacheDir, 0o755); err != nil {
		log.Fatalf("创建缓存目录失败: %v", err)
	}
	resolveSigner()

	opts := sdk.Options{
		RetryAttempts:      2,
		APIOrigin:          *apiOrigin,
		RegisterOrigin:     *registerOrigin,
		DistributionOrigin: *distOrigin,
		SignerURL:          *signerURL,
		SignerToken:        *signerToken,
	}
	if *padMode {
		opts.Device = padDevice()
	}
	cl, err := adapters.NewClient(*profile, opts)
	if err != nil {
		log.Fatalf("创建 SDK 客户端失败: %v", err)
	}

	a := &app{cl: cl, ff: *ffmpegBin, cache: *cacheDir, warming: map[string]bool{}}
	a.trimCache()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/health", a.handleHealth)

	// 发现与搜索
	mux.HandleFunc("GET /v1/feed", a.handleFeed)
	mux.HandleFunc("GET /v1/search", a.handleSearch)
	mux.HandleFunc("GET /v1/suggest", a.handleSuggest)
	mux.HandleFunc("GET /v1/hot-search", a.handleHotSearch)
	mux.HandleFunc("GET /v1/search-cues", a.handleSearchCues)
	mux.HandleFunc("GET /v1/new-releases", a.handleNewReleases)

	// 短剧与分集
	mux.HandleFunc("GET /v1/series/{seriesID}", a.handleSeries)
	mux.HandleFunc("GET /v1/series-batch", a.handleSeriesBatch)
	mux.HandleFunc("GET /v1/episodes/{seriesID}", a.handleEpisodes)
	mux.HandleFunc("GET /v1/danmaku/{seriesID}/{episodeID}", a.handleDanmaku)
	mux.HandleFunc("GET /v1/seasons/{seriesID}", a.handleSeasons)
	mux.HandleFunc("GET /v1/recommend/{seriesID}", a.handleRecommend)
	mux.HandleFunc("GET /v1/album/{albumID}", a.handleAlbum)

	// 榜单与分类
	mux.HandleFunc("GET /v1/rank", a.handleShortRank)
	mux.HandleFunc("GET /v1/rank/groups", a.handleRankGroups)
	mux.HandleFunc("GET /v1/rank/rows", a.handleRankRows)
	mux.HandleFunc("GET /v1/ranking", a.handleRanking)
	mux.HandleFunc("GET /v1/ranking/{activityID}/{rankListID}", a.handleRanking)
	mux.HandleFunc("GET /v1/filter/panel", a.handleFilterPanel)
	mux.HandleFunc("GET /v1/filter", a.handleFilter)
	mux.HandleFunc("GET /v1/categories/{categoryID}", a.handleCategories)
	mux.HandleFunc("GET /v1/categories/{categoryID}/landing", a.handleCategoryLanding)

	// 演员
	mux.HandleFunc("GET /v1/person/{userID}", a.handlePerson)
	mux.HandleFunc("GET /v1/person/{userID}/works", a.handlePersonWorks)

	// 播放与设备
	mux.HandleFunc("GET /v1/play/{episodeID}", a.handlePlay)
	mux.HandleFunc("GET /v1/stream/{episodeID}", a.handleStream)
	mux.HandleFunc("GET /v1/cache/prewarm/{episodeID}", a.handlePrewarm)
	mux.HandleFunc("POST /v1/device/reset", a.handleResetDevice)

	srv := &http.Server{Addr: *addr, Handler: withCORS(mux), ReadHeaderTimeout: 10 * time.Second}

	go func() {
		ch := make(chan os.Signal, 1)
		signal.Notify(ch, os.Interrupt, syscall.SIGTERM)
		<-ch
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = srv.Shutdown(ctx)
	}()

	log.Printf("ohgd 就绪: http://%s  (cache=%s, ffmpeg=%s, channel=%s)", *addr, *cacheDir, *ffmpegBin, *channel)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

func withCORS(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Headers", "*")
		h.ServeHTTP(w, r)
	})
}

// ---------- handlers ----------

func (a *app) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{"ok": true, "cache_dir": *cacheDir, "ffmpeg": *ffmpegBin, "channel": *channel})
}

func (a *app) handleFeed(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	ch := q.Get("channel")
	if ch == "" {
		ch = *channel
	}
	ctx, cancel := context.WithTimeout(r.Context(), 40*time.Second)
	defer cancel()

	page, err := a.cl.Discover(ctx, sdk.DiscoverOptions{Channel: ch, Cursor: q.Get("cursor")})
	if err != nil {
		writeErr(w, 502, "discover failed", err)
		return
	}

	items := make([]feedItem, 0, len(page.Items))
	for _, s := range page.Items {
		items = append(items, feedItem{
			ID: s.ID, Title: s.Title, Description: s.Description,
			CoverURL: s.CoverURL, EpisodeCount: s.EpisodeCount,
		})
	}
	a.mu.Lock()
	a.lastFeed = items
	a.mu.Unlock()

	// 后台预热：让客户端滑到第二条时第一集已经处理完成
	if *warmWork > 0 {
		go a.warmFeed(items)
	}

	writeJSON(w, 200, map[string]any{
		"items":    items,
		"cursor":   page.Cursor,
		"has_more": page.HasMore,
		"channel":  ch,
	})
}

func (a *app) handleSearch(w http.ResponseWriter, r *http.Request) {
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	if q == "" {
		writeErr(w, 400, "missing q", nil)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 40*time.Second)
	defer cancel()

	page, err := a.cl.Search(ctx, q, sdk.SearchOptions{
		Cursor:   r.URL.Query().Get("cursor"),
		PageSize: atoi(r.URL.Query().Get("page_size"), 20),
	})
	if err != nil {
		writeErr(w, 502, "search failed", err)
		return
	}

	items := make([]feedItem, 0, len(page.Items))
	for _, s := range page.Items {
		items = append(items, feedItem{
			ID: s.ID, Title: s.Title, Description: s.Description,
			CoverURL: s.CoverURL, EpisodeCount: s.EpisodeCount,
		})
	}
	// 预热前两条，命中后能直接开播
	if len(items) > 0 && *warmWork > 0 {
		go a.warmFeed(items)
	}
	writeJSON(w, 200, map[string]any{
		"query": q, "items": items,
		"cursor": page.Cursor, "has_more": page.HasMore,
	})
}

// sdkCall 统一「调 SDK → 返回 JSON」：错误一律 502，超时给足 60s（榜单/筛选偶发慢）
func (a *app) sdkCall(w http.ResponseWriter, r *http.Request, fn func(ctx context.Context) (any, error)) {
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	v, err := fn(ctx)
	if err != nil {
		writeErr(w, 502, "upstream failed", err)
		return
	}
	writeJSON(w, 200, v)
}

// handleSuggest 搜索联想词：GET /v1/suggest?prefix=死考
func (a *app) handleSuggest(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.Suggest(ctx, r.URL.Query().Get("prefix"))
	})
}

// handleHotSearch 搜索页的「猜你想搜」与热搜榜：GET /v1/hot-search
func (a *app) handleHotSearch(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) { return a.cl.HotSearch(ctx) })
}

// handleSearchCues 搜索框轮播提示词：GET /v1/search-cues
func (a *app) handleSearchCues(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) { return a.cl.SearchCues(ctx) })
}

// handleNewReleases 上新日历：GET /v1/new-releases?date=YYYYMMDD&cursor=
func (a *app) handleNewReleases(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.NewReleases(ctx, sdk.NewReleaseQuery{
			Date:   r.URL.Query().Get("date"),
			Cursor: r.URL.Query().Get("cursor"),
		})
	})
}

// handleSeries 单部短剧详情：GET /v1/series/{seriesID}
func (a *app) handleSeries(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.GetSeries(ctx, r.PathValue("seriesID"))
	})
}

// handleSeriesBatch 批量详情：GET /v1/series-batch?ids=a,b,c
func (a *app) handleSeriesBatch(w http.ResponseWriter, r *http.Request) {
	ids := splitList(r.URL.Query().Get("ids"))
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		if len(ids) == 0 {
			return nil, errors.New("missing ids")
		}
		return a.cl.GetSeriesBatch(ctx, ids)
	})
}

// handleDanmaku 一集弹幕：GET /v1/danmaku/{seriesID}/{episodeID}?cursor=&page_size=
func (a *app) handleDanmaku(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.ListDanmaku(ctx, r.PathValue("seriesID"), r.PathValue("episodeID"), sdk.DanmakuOptions{
			Cursor:   r.URL.Query().Get("cursor"),
			PageSize: atoi(r.URL.Query().Get("page_size"), 0),
		})
	})
}

// handleSeasons 多季短剧的全部季：GET /v1/seasons/{seriesID}
func (a *app) handleSeasons(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.Seasons(ctx, r.PathValue("seriesID"))
	})
}

// handleRecommend 相关推荐：GET /v1/recommend/{seriesID}
func (a *app) handleRecommend(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.SeriesRecommend(ctx, r.PathValue("seriesID"))
	})
}

// handleAlbum 合集（多季合集）：GET /v1/album/{albumID}
func (a *app) handleAlbum(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.GetAlbum(ctx, r.PathValue("albumID"), sdk.AlbumOptions{})
	})
}

// handleShortRank 短剧排行榜：GET /v1/rank?content=&board=&cursor=
func (a *app) handleShortRank(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.ShortRank(ctx, sdk.ShortRankQuery{
			Content: q.Get("content"), Board: q.Get("board"), Cursor: q.Get("cursor"),
		})
	})
}

// handleRankGroups 书城榜单类型：GET /v1/rank/groups
func (a *app) handleRankGroups(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) { return a.cl.RankGroups(ctx) })
}

// handleRankRows 书城榜单的一页：GET /v1/rank/rows?cell=&offset=（cell 为空即服务端默认榜单）
func (a *app) handleRankRows(w http.ResponseWriter, r *http.Request) {
	cell := r.URL.Query().Get("cell")
	offset := atoi(r.URL.Query().Get("offset"), 0)
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.RankRows(ctx, cell, offset)
	})
}

// handleRanking 活动榜单：GET /v1/ranking/{activityID}/{rankListID}
func (a *app) handleRanking(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.Ranking(ctx, r.PathValue("activityID"), r.PathValue("rankListID"))
	})
}

// handleFilterPanel 短剧筛选面板：GET /v1/filter/panel?genre=short_play
func (a *app) handleFilterPanel(w http.ResponseWriter, r *http.Request) {
	genre := r.URL.Query().Get("genre")
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.ShortFilterPanel(ctx, genre)
	})
}

// handleFilter 按条件筛选短剧：GET /v1/filter?genre=&cursor=&sel=tag:value,tag:value
func (a *app) handleFilter(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.ShortFilter(ctx, sdk.ShortFilterQuery{
			Selections: parseSelections(q.Get("sel")),
			Cursor:     q.Get("cursor"),
		})
	})
}

// handleCategories 书籍分类标签页：GET /v1/categories/{categoryID}
func (a *app) handleCategories(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.Categories(ctx, r.PathValue("categoryID"))
	})
}

// handleCategoryLanding 分类下列表的一页：GET /v1/categories/{id}/landing?tab=&cursor=&filter=k:v
func (a *app) handleCategoryLanding(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.CategoryLanding(ctx, r.PathValue("categoryID"), sdk.LandingOptions{
			Tab: q.Get("tab"), Cursor: q.Get("cursor"), Filters: parseFlatPairs(q.Get("filter")),
		})
	})
}

// handlePerson 演员主页：GET /v1/person/{userID}
func (a *app) handlePerson(w http.ResponseWriter, r *http.Request) {
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.Person(ctx, r.PathValue("userID"))
	})
}

// handlePersonWorks 演员参演的短剧：GET /v1/person/{userID}/works?cursor=
func (a *app) handlePersonWorks(w http.ResponseWriter, r *http.Request) {
	userID, cursor := r.PathValue("userID"), r.URL.Query().Get("cursor")
	a.sdkCall(w, r, func(ctx context.Context) (any, error) {
		return a.cl.PersonWorks(ctx, userID, cursor)
	})
}

// handleResetDevice 丢弃当前匿名设备并注册新设备：POST /v1/device/reset
func (a *app) handleResetDevice(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	if err := a.cl.ResetDevice(ctx); err != nil {
		writeErr(w, 502, "reset device failed", err)
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true})
}

// splitList 把 "a,b,c" 拆成 [a b c]（忽略空白与空项）
func splitList(s string) []string {
	out := make([]string, 0, 4)
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

// parseFlatPairs 把 "k:v,k:v" 拆成 map[string]string（分类筛选面板用）
func parseFlatPairs(s string) map[string]string {
	out := map[string]string{}
	for _, p := range splitList(s) {
		k, v, ok := strings.Cut(p, ":")
		if ok && k != "" {
			out[k] = v
		}
	}
	return out
}

// parseSelections 把 "k:v,k:v2,k2:v" 拆成 map[k][]v（短剧筛选用，同一个 key 可多值）
func parseSelections(s string) map[string][]string {
	out := map[string][]string{}
	for _, p := range splitList(s) {
		k, v, ok := strings.Cut(p, ":")
		if ok && k != "" {
			out[k] = append(out[k], v)
		}
	}
	return out
}

func (a *app) handleEpisodes(w http.ResponseWriter, r *http.Request) {
	seriesID := r.PathValue("seriesID")
	ctx, cancel := context.WithTimeout(r.Context(), 40*time.Second)
	defer cancel()

	page, err := a.cl.ListEpisodes(ctx, seriesID, sdk.EpisodeOptions{
		Cursor:   r.URL.Query().Get("cursor"),
		PageSize: atoi(r.URL.Query().Get("page_size"), 0),
	})
	if err != nil {
		writeErr(w, 502, "episodes failed", err)
		return
	}

	items := make([]episodeItem, 0, len(page.Items))
	for _, e := range page.Items {
		items = append(items, episodeItem{
			ID: e.ID, SeriesID: e.SeriesID, Number: e.Number, Title: e.Title,
			Duration: e.Duration.Seconds(), Playable: e.Playable,
			Vertical: e.Vertical, CoverURL: e.CoverURL,
		})
	}
	writeJSON(w, 200, map[string]any{
		"series_id": seriesID, "items": items,
		"cursor": page.Cursor, "has_more": page.HasMore,
	})
}

func (a *app) handlePlay(w http.ResponseWriter, r *http.Request) {
	epID := r.PathValue("episodeID")
	def := r.URL.Query().Get("definition")
	strict := r.URL.Query().Get("strict") == "1"

	// 缓存优先：已经落过盘的集直接用本地文件，不再向上游解析。
	// 上游播放接口会拒掉“用过的设备”（返回 200 + 空体），已缓存的集不该因此不可播。
	// strict=1（客户端主动换清晰度）只认请求的那一档缓存，没有就向上游解析。
	if cachedDef, ok := a.cacheLookup(epID, def, strict); ok {
		scheme := "http"
		if r.TLS != nil {
			scheme = "https"
		}
		resp := playResponse{
			EpisodeID:  epID,
			Definition: cachedDef,
			StreamURL:  streamURL(scheme, r.Host, epID, cachedDef, strict),
			Cached:     true,
			Qualities:  []qualityItem{{Definition: cachedDef}},
		}
		if a.probeCached(epID, cachedDef, &resp) {
			writeJSON(w, 200, resp)
			return
		}
	}

	pb, st, key, err := a.resolve(r.Context(), epID, def)
	if err != nil {
		writeErr(w, 502, "play failed", err)
		return
	}

	qualities := make([]qualityItem, 0, len(pb.Streams))
	for _, s := range pb.Streams {
		if s.HLS || s.Dash {
			continue
		}
		qualities = append(qualities, qualityItem{
			Definition: s.Definition, Width: s.Width, Height: s.Height,
			Bitrate: s.Bitrate, Size: s.Size, Codec: s.Codec, Encryption: s.Encryption,
		})
	}

	scheme := "http"
	if r.TLS != nil {
		scheme = "https"
	}
	resp := playResponse{
		EpisodeID: pb.EpisodeID, Duration: float64(pb.DurationSeconds),
		Protected: pb.Protected, ExpiresAt: pb.ExpiresAt,
		Definition: st.Definition, Width: st.Width, Height: st.Height,
		StreamURL:   streamURL(scheme, r.Host, epID, st.Definition, strict),
		UpstreamURL: st.URL,
		Cached:      a.cacheReady(epID, st.Definition),
		Qualities:   qualities,
	}
	if *exposeKey && key != "" {
		resp.ContentKey = key
		resp.KeyVersion = ""
	}
	writeJSON(w, 200, resp)
}

// handleStream 是客户端真正播放的入口。
// 缓存就绪 → 标准 mp4（支持 Range/seek）；未就绪 → fragmented mp4 实时流。
func (a *app) handleStream(w http.ResponseWriter, r *http.Request) {
	epID := r.PathValue("episodeID")
	def := r.URL.Query().Get("definition")
	strict := r.URL.Query().Get("strict") == "1"

	// 不调 resolve 也能服务已缓存的集：上游不可用时缓存仍然可播
	if cachedDef, ok := a.cacheLookup(epID, def, strict); ok {
		a.serveCached(w, r, epID, cachedDef)
		return
	}

	pb, st, key, err := a.resolve(r.Context(), epID, def)
	if err != nil {
		writeErr(w, 502, "resolve failed", err)
		return
	}
	path := a.cachePath(epID, st.Definition)

	// 1) 缓存已就绪：直接当静态 mp4 服务，Range/seek 全支持
	if a.cacheReady(epID, st.Definition) {
		w.Header().Set("Content-Type", "video/mp4")
		w.Header().Set("Accept-Ranges", "bytes")
		http.ServeFile(w, r, path)
		return
	}

	// 2) 未就绪：fragmented mp4 边解边发，同时后台落缓存
	w.Header().Set("Content-Type", "video/mp4")
	w.Header().Set("Cache-Control", "no-store")
	flusher, _ := w.(http.Flusher)

	seek := atoi(r.URL.Query().Get("seek"), 0)
	// -tls_verify 0：本机 ffmpeg(gyan/OpenSSL) 从 MSYS 的 CA 目录取证书，
	// 而 ohgd 是纯 Windows 进程，拿不到那套路径 → 上游 CDN 一律报
	// "Peer certificate failed verification"，/v1/stream 返回 0 字节。
	// 上游地址本身带 token 签名、且时刻在变，这里跳过证书校验风险可控。
	args := []string{"-v", "error", "-nostdin", "-tls_verify", "0"}
	if seek > 0 {
		args = append(args, "-ss", strconv.Itoa(seek))
	}
	if key != "" {
		args = append(args, "-decryption_key", key)
	}
	args = append(args,
		"-i", st.URL,
		"-c", "copy",
		"-movflags", "frag_keyframe+empty_moov+default_base_moof",
		"-f", "mp4", "pipe:1",
	)

	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	cmd := exec.CommandContext(ctx, a.ff, args...)
	cmd.Stderr = logWriter("ffmpeg/stream " + epID)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		writeErr(w, 500, "pipe failed", err)
		return
	}
	if err := cmd.Start(); err != nil {
		writeErr(w, 500, "ffmpeg start failed", err)
		return
	}

	// 顺带写缓存（不影响播放进度）
	go a.fillCache(epID, st.Definition, st.URL, key)

	buf := make([]byte, 64*1024)
	for {
		n, rerr := stdout.Read(buf)
		if n > 0 {
			if _, werr := w.Write(buf[:n]); werr != nil {
				break
			}
			if flusher != nil {
				flusher.Flush()
			}
		}
		if rerr != nil {
			break
		}
	}
	_ = cmd.Wait()
	_ = pb
}

func (a *app) handlePrewarm(w http.ResponseWriter, r *http.Request) {
	epID := r.PathValue("episodeID")
	def := r.URL.Query().Get("definition")

	// 指定了清晰度时先查本地状态：已落盘 / 正在落盘都不必再向上游解析，客户端可以放心轮询
	if def != "" {
		if a.cacheReady(epID, def) {
			writeJSON(w, 200, map[string]any{"episode_id": epID, "definition": def, "state": "ready"})
			return
		}
		a.mu.Lock()
		busy := a.warming[a.cachePath(epID, def)]
		a.mu.Unlock()
		if busy {
			writeJSON(w, 202, map[string]any{"episode_id": epID, "definition": def, "state": "warming"})
			return
		}
	}

	pb, st, key, err := a.resolve(r.Context(), epID, def)
	if err != nil {
		writeErr(w, 502, "resolve failed", err)
		return
	}
	if a.cacheReady(epID, st.Definition) {
		writeJSON(w, 200, map[string]any{"episode_id": epID, "definition": st.Definition, "state": "ready"})
		return
	}
	go a.fillCache(epID, st.Definition, st.URL, key)
	writeJSON(w, 202, map[string]any{"episode_id": epID, "definition": st.Definition, "state": "warming", "duration_seconds": pb.DurationSeconds})
}

// ---------- 核心逻辑 ----------

// resolve 取播放模型 + 目标清晰度 + 内容密钥。
func (a *app) resolve(ctx context.Context, epID, def string) (*model.Playback, *model.Stream, string, error) {
	if def == "" {
		def = *quality // 未指定时用配置的默认清晰度
	}
	c, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()

	pb, err := a.cl.ResolvePlayback(c, epID, sdk.PlaybackOptions{})
	if errors.Is(err, sdk.ErrDRMProtected) && pb != nil {
		err = nil // 加密分集属于正常返回
	}
	if err != nil {
		return nil, nil, "", err
	}
	if pb == nil || len(pb.Streams) == 0 {
		return nil, nil, "", errors.New("no streams")
	}

	st, err := pickStream(pb, def)
	if err != nil {
		return nil, nil, "", err
	}

	key := ""
	if pb.Protected {
		ck, kerr := sdk.ContentKey(pb)
		if kerr != nil {
			return nil, nil, "", fmt.Errorf("content key: %w", kerr)
		}
		key = ck.Hex
	}
	return pb, st, key, nil
}

// pickStream 选择单文件流；def 为空时取分辨率最高的一档。
func pickStream(pb *model.Playback, def string) (*model.Stream, error) {
	var cands []model.Stream
	for _, s := range pb.Streams {
		if s.HLS || s.Dash || s.URL == "" {
			continue
		}
		cands = append(cands, s)
	}
	if len(cands) == 0 {
		return nil, errors.New("no single-file stream (only hls/dash)")
	}
	if def != "" {
		for i := range cands {
			if strings.EqualFold(cands[i].Definition, def) {
				return &cands[i], nil
			}
		}
		// 允许传 720 / 1080 这种裸数字
		for i := range cands {
			if strings.TrimSuffix(cands[i].Definition, "p") == strings.TrimSuffix(def, "p") {
				return &cands[i], nil
			}
		}
	}
	sort.Slice(cands, func(i, j int) bool { return cands[i].Height > cands[j].Height })
	return &cands[0], nil
}

func (a *app) cachePath(epID, def string) string {
	return filepath.Join(a.cache, fmt.Sprintf("%s_%s.mp4", epID, def))
}

func (a *app) cacheReady(epID, def string) bool {
	fi, err := os.Stat(a.cachePath(epID, def))
	return err == nil && fi.Size() > 32*1024
}

// fillCache 后台把整集参数处理并落盘为普通 mp4（可 seek）。
func (a *app) fillCache(epID, def, upstream, key string) {
	final := a.cachePath(epID, def)
	if a.cacheReady(epID, def) {
		return
	}
	a.mu.Lock()
	if a.warming[final] {
		a.mu.Unlock()
		return
	}
	a.warming[final] = true
	a.mu.Unlock()
	defer func() {
		a.mu.Lock()
		delete(a.warming, final)
		a.mu.Unlock()
	}()

	tmp := final + ".part"
	// -tls_verify 0：本机 ffmpeg(gyan/OpenSSL) 从 MSYS 的 CA 目录取证书，
	// 而 ohgd 是纯 Windows 进程，拿不到那套路径 → 上游 CDN 一律报
	// "Peer certificate failed verification"，/v1/stream 返回 0 字节。
	// 上游地址本身带 token 签名、且时刻在变，这里跳过证书校验风险可控。
	args := []string{"-v", "error", "-nostdin", "-y", "-tls_verify", "0"}
	if key != "" {
		args = append(args, "-decryption_key", key)
	}
	args = append(args,
		"-i", upstream,
		"-c", "copy",
		"-movflags", "+faststart",
		"-f", "mp4", tmp,
	)
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, a.ff, args...)
	cmd.Stderr = logWriter("ffmpeg/fill " + epID)
	if err := cmd.Run(); err != nil {
		_ = os.Remove(tmp)
		log.Printf("预热失败 %s: %v", epID, err)
		return
	}
	if fi, err := os.Stat(tmp); err != nil || fi.Size() < 32*1024 {
		_ = os.Remove(tmp)
		return
	}
	if err := os.Rename(tmp, final); err != nil {
		_ = os.Remove(tmp)
		return
	}
	log.Printf("预热完成 %s -> %s", epID, filepath.Base(final))
	a.trimCache()
}

// warmFeed 后台预热前 N 条的第一集，让滑动切换尽量秒开。
func (a *app) warmFeed(items []feedItem) {
	n := *warmWork
	if n > len(items) {
		n = len(items)
	}
	for _, it := range items[:n] {
		ep, ok := a.firstEpisode(it.ID)
		if !ok {
			continue
		}
		pb, st, key, err := a.resolve(context.Background(), ep, "")
		if err != nil {
			continue
		}
		_ = pb
		a.fillCache(ep, st.Definition, st.URL, key)
	}
}

func (a *app) firstEpisode(seriesID string) (string, bool) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	page, err := a.cl.ListEpisodes(ctx, seriesID, sdk.EpisodeOptions{})
	if err != nil || len(page.Items) == 0 {
		return "", false
	}
	for _, e := range page.Items {
		if e.Playable {
			return e.ID, true
		}
	}
	return page.Items[0].ID, true
}

// ---------- 小工具 ----------

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string, err error) {
	writeJSON(w, code, map[string]any{"error": msg, "detail": fmt.Sprint(err)})
}

func atoi(s string, def int) int {
	if s == "" {
		return def
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return def
	}
	return n
}

func urlEnc(s string) string {
	return strings.ReplaceAll(s, " ", "%20")
}

func logWriter(prefix string) io.Writer {
	return &prefixWriter{prefix: prefix}
}

type prefixWriter struct{ prefix string }

func (p *prefixWriter) Write(b []byte) (int, error) {
	for _, line := range strings.Split(strings.TrimRight(string(b), "\n"), "\n") {
		if line != "" {
			log.Printf("[%s] %s", p.prefix, line)
		}
	}
	return len(b), nil
}

// ---------------- 配置文件 ----------------

// configFile 是 config.json 的结构。所有字段可选，未出现的字段回落到 flag 默认值。
// 优先级：命令行 flag（显式指定）> config.json > 内置默认值。
type configFile struct {
	APIOrigin          *string `json:"api_origin"`
	RegisterOrigin     *string `json:"register_origin"`
	DistributionOrigin *string `json:"distribution_origin"`
	SignerURL          *string `json:"signer_url"`
	SignerToken        *string `json:"signer_token"`

	Addr       *string `json:"addr"`
	Profile    *string `json:"profile"`
	FFmpeg     *string `json:"ffmpeg"`
	Cache      *string `json:"cache"`
	Quality    *string `json:"quality"`
	MaxCacheMB *int    `json:"max_cache_mb"`
	Channel    *string `json:"channel"`
	Warm       *int    `json:"warm"`
	ExposeKey  *bool   `json:"expose_key"`
	Pad        *bool   `json:"pad"`
}

func applyConfig(path string) {
	b, err := os.ReadFile(path)
	if err != nil {
		return // 没有配置文件是正常情况
	}
	var c configFile
	if err := json.Unmarshal(b, &c); err != nil {
		log.Printf("配置文件解析失败，已忽略: %v", err)
		return
	}
	explicit := map[string]bool{}
	flag.Visit(func(f *flag.Flag) { explicit[f.Name] = true })

	str := func(name string, dst *string, v *string) {
		if v != nil && !explicit[name] {
			*dst = *v
		}
	}
	num := func(name string, dst *int, v *int) {
		if v != nil && !explicit[name] {
			*dst = *v
		}
	}
	bln := func(name string, dst *bool, v *bool) {
		if v != nil && !explicit[name] {
			*dst = *v
		}
	}

	str("api-origin", apiOrigin, c.APIOrigin)
	str("register-origin", registerOrigin, c.RegisterOrigin)
	str("distribution-origin", distOrigin, c.DistributionOrigin)
	str("signer-url", signerURL, c.SignerURL)
	str("signer-token", signerToken, c.SignerToken)
	str("addr", addr, c.Addr)
	str("profile", profile, c.Profile)
	str("ffmpeg", ffmpegBin, c.FFmpeg)
	str("cache", cacheDir, c.Cache)
	str("quality", quality, c.Quality)
	str("channel", channel, c.Channel)
	num("max-cache-mb", maxCacheMB, c.MaxCacheMB)
	num("warm", warmWork, c.Warm)
	bln("expose-key", exposeKey, c.ExposeKey)
	bln("pad", padMode, c.Pad)

	log.Printf("已加载配置: %s", path)
}

// ---------------- 缓存上限 ----------------

// trimCache 按总容量上限删除最旧的缓存文件（LRU 近似：按修改时间）。
// 上限 0 表示不限制。
func (a *app) trimCache() {
	limit := int64(*maxCacheMB) * 1024 * 1024
	if limit <= 0 {
		return
	}
	entries, err := os.ReadDir(a.cache)
	if err != nil {
		return
	}
	type entry struct {
		path string
		size int64
		mod  time.Time
	}
	var files []entry
	var total int64
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".mp4") {
			continue
		}
		info, ierr := e.Info()
		if ierr != nil {
			continue
		}
		files = append(files, entry{filepath.Join(a.cache, e.Name()), info.Size(), info.ModTime()})
		total += info.Size()
	}
	if total <= limit {
		return
	}
	sort.Slice(files, func(i, j int) bool { return files[i].mod.Before(files[j].mod) })
	var freed int64
	for _, f := range files {
		if total <= limit {
			break
		}
		if err := os.Remove(f.path); err == nil {
			total -= f.size
			freed += f.size
		}
	}
	if freed > 0 {
		log.Printf("缓存清理: 释放 %.1fMB，当前 %.1fMB / 上限 %dMB",
			float64(freed)/1048576, float64(total)/1048576, *maxCacheMB)
	}
}

// ---------- 缓存优先 ----------

// cachedDefinition 返回这个集已经存在的缓存清晰度：请求的优先，否则取任意一档。
// 第二个返回值为 false 表示没有可用缓存。
func (a *app) cachedDefinition(epID, def string) (string, bool) {
	if def != "" && a.cacheReady(epID, def) {
		return def, true
	}
	for _, d := range []string{def, *quality, "1080p", "720p", "540p", "480p", "360p"} {
		if d != "" && a.cacheReady(epID, d) {
			return d, true
		}
	}
	return "", false
}

// cacheLookup 按模式查缓存：strict 时只认请求的清晰度（为空则用默认清晰度），否则同 cachedDefinition。
func (a *app) cacheLookup(epID, def string, strict bool) (string, bool) {
	if !strict {
		return a.cachedDefinition(epID, def)
	}
	if def == "" {
		def = *quality
	}
	return def, a.cacheReady(epID, def)
}

// streamURL 生成 /v1/stream 地址；strict 要一路带下去，否则 /v1/stream 又会退回任意一档缓存。
func streamURL(scheme, host, epID, def string, strict bool) string {
	u := fmt.Sprintf("%s://%s/v1/stream/%s?definition=%s", scheme, host, epID, urlEnc(def))
	if strict {
		u += "&strict=1"
	}
	return u
}

// serveCached 把已落盘的 mp4 当静态文件发出去（支持 Range / seek）。
func (a *app) serveCached(w http.ResponseWriter, r *http.Request, epID, def string) {
	w.Header().Set("Content-Type", "video/mp4")
	w.Header().Set("Accept-Ranges", "bytes")
	http.ServeFile(w, r, a.cachePath(epID, def))
}

// probeCached 用 ffprobe 填上时长与分辨率；失败时保留零值但不影响播放。
func (a *app) probeCached(epID, def string, resp *playResponse) bool {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, "ffprobe", "-v", "error",
		"-select_streams", "v:0",
		"-show_entries", "stream=width,height:format=duration",
		"-of", "default=noprint_wrappers=1", a.cachePath(epID, def)).Output()
	if err != nil {
		return true
	}
	for _, line := range strings.Split(string(out), "\n") {
		k, v, ok := strings.Cut(strings.TrimSpace(line), "=")
		if !ok {
			continue
		}
		switch k {
		case "width":
			if n, e := strconv.Atoi(v); e == nil {
				resp.Width = n
			}
		case "height":
			if n, e := strconv.Atoi(v); e == nil {
				resp.Height = n
			}
		case "duration":
			if f, e := strconv.ParseFloat(v, 64); e == nil {
				resp.Duration = f
			}
		}
	}
	return true
}
