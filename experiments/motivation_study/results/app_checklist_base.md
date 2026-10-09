# 需要安装的 App 清单（子集: base）

来源: `data/MobileBench-OL - top12.csv`，共 310 个任务 / 12 个 App

设备已装 12 个，**还需要装 0 个**。

| 装好了 | App | 中文名 | 包名 | 入口 Activity | 任务数 | 其中需重置 | 版本线索 |
|---|---|---|---|---|---|---|---|
| ☑ | `bili` | 哔哩哔哩 | `tv.danmaku.bili` | `tv.danmaku.bili/tv.danmaku.bili.MainActivityV2` | 30 | 11 | — |
| ☑ | `neteasemusic` | 网易云音乐 | `com.netease.cloudmusic` | `com.netease.cloudmusic/.activity.IconChangeDefaultAlias` | 30 | 15 | — |
| ☑ | `fanqieread` | 番茄免费小说 | `com.dragon.read` | `com.dragon.read/.pages.splash.SplashActivity` | 30 | 6 | — |
| ☑ | `pinduoduo` | 拼多多 | `com.xunmeng.pinduoduo` | `com.xunmeng.pinduoduo/.ui.activity.MainFrameActivity` | 30 | 3 | — |
| ☑ | `qq` | QQ | `com.tencent.mobileqq` | `com.tencent.mobileqq/.activity.SplashActivity` | 30 | 4 | — |
| ☑ | `wuba` | 58同城-招聘找工作租房家政买车 | `com.wuba` | `com.wuba/.home.activity.HomeActivity` | 30 | 0 | — |
| ☑ | `tonghuashun` | 同花顺-股票炒股 | `com.hexin.plat.android` | `com.hexin.plat.android/.Hexin` | 30 | 3 | — |
| ☑ | `articlenews` | 今日头条 | `com.ss.android.article.news` | `com.ss.android.article.news/.activity.MainActivity` | 20 | 9 | — |
| ☑ | `minimap` | 高德地图 | `com.autonavi.minimap` | `com.autonavi.minimap/com.autonavi.map.activity.SplashActivity` | 20 | 0 | — |
| ☑ | `baidubrowser` | 百度-AI智能搜索 | `com.baidu.searchbox` | `com.baidu.searchbox/.MainActivity` | 20 | 5 | — |
| ☑ | `rimet` | 钉钉 | `com.alibaba.android.rimet` | `com.alibaba.android.rimet/.biz.LaunchHomeActivity` | 20 | 5 | — |
| ☑ | `seeyou` | 美柚 | `com.lingan.seeyou` | `com.lingan.seeyou/.ui.activity.main.SeeyouActivity` | 20 | 6 | — |

## 说明

- **版本线索**列只有 `longtail.csv` 有（形如 `keep_8.5.30.apk`）；`base` 任务集**没有任何版本约束**，
  所以任意较新的商店版本先试，xpath 匹配不上再换版本。
- APK 需要你自己获取（仓库不提供）：各 App 官网 / 应用宝 / 华为·小米应用商店 / APKMirror / APKPure 均可，
  注意遵守各平台的许可与使用条款。
- 装完后用 `mbl_app_checklist.py --adb <adb> --device <serial>` 复查一遍打勾情况。
- 只用 base 的话，**B站独占 30 个任务**（最大单 App 任务块），所以哪怕只装 B站也能先做第一轮实验。
