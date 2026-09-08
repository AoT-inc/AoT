# GISレイヤー管理

`/geo/layer` ページは、外部の地図データソースを登録・管理する場所です。登録したレイヤーは、デザインツールやダッシュボードの地図ウィジェットでベースレイヤーやオーバーレイとして使用できます。

---

## 対応プロバイダー

### 国内（韓国）

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| VWorld | `gis_vworld` | 政府公式地図、地籍、航空写真、PNU筆地検索 | 必須 |
| Kakao Maps | `gis_kakao` | 韓国国内で最も精度の高い道路地図 | 必須 |
| Naver Maps | `gis_naver` | リアルタイム交通情報付きの韓国地図 | 必須 |

### 海外一般

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| OpenStreetMap | `gis_osm` | 無料のオープンソース地図 | 不要 |
| Google Maps | `gis_google` | 衛星写真／道路地図／ハイブリッド | 必須 |
| ESRI | `gis_esri` | 衛星写真、地形図、道路地図 | 不要（一部レイヤーを除く） |
| Mapbox | `gis_mapbox` | ベクタータイル、カスタムスタイル | 必須 |
| MapTiler | `gis_maptiler_vector` | ベクタータイル、多様なスタイル | 必須 |
| Bing | `gis_bing` | 衛星写真、鳥瞰図 | 必須 |
| Carto | `gis_carto` | すっきりとしたベクターデザイン地図 | 不要 |
| Stadia Maps | `gis_stadia` | 高品質なデザイン地図 | 任意 |
| Thunderforest | `gis_thunderforest` | サイクリング／ハイキング／交通に特化 | 必須 |

### 衛星／航空写真

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| NASA GIBS | `gis_nasa_gibs` | 科学衛星画像、WMS | 不要 |
| ESA | `gis_esa` | 欧州宇宙機関の衛星画像 | 不要 |
| Sentinel Hub | `gis_sentinelhub` | Sentinel-2 10m 解像度の NDVI・水分・水域指数 | 必要（OAuth クライアント） |

### 気象オーバーレイ

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| RainViewer | `gis_rainviewer` | リアルタイムおよび過去の降雨レーダー | 不要 |
| OpenWeather | `gis_openweather` | 気温、降水、雲、風のレイヤー | 必須 |
| Open-Meteo | (組み込みプロキシ) | 気象予報データ | 不要 |

### 専門データ

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| OpenTopoMap | `gis_opentopomap` | 等高線・地形図 | 不要 |
| ISRIC | `gis_isric` | 世界の土壌データ（SoilGrids） | 不要 |
| GSI | `gis_gsi` | 日本の国土地理院 | 不要 |
| SGIS | `gis_sgis` | 韓国統計庁の統計地理情報 | 必要 |
| Agromonitoring | `gis_agromonitoring` | 圃場単位の NDVI 統計・土壌水分・地温 | 必要 |

---

## レイヤーを登録する方法

1. `/geo/layer` に移動します。
2. 右上の **Input Type** ドロップダウンから目的のプロバイダーを選択します。
3. **Add** をクリックします。
4. 新しく追加された項目の **Settings（歯車）アイコン** をクリックします。
5. 必要なオプション（APIキー、レイヤータイプなど）を入力します。
6. **Save** をクリックし、続けて **Activate** をクリックして有効化します。

---

## プロバイダー別設定

### VWorld

韓国の国家空間情報基盤プラットフォームです。VWorld開発者サイト（https://map.vworld.kr）でAPIキーを取得する必要があります。

| Option | 説明 |
|--------|-------------|
| API Key | VWorld APIキー |
| Layer Type | `Base`（標準地図）／`Satellite`（航空写真）／`Hybrid`／`Gray` |

VWorldは**筆地インポート**にも使用されます。住所検索を機能させるには、APIキーの登録が必要です。

### Google Maps

Google Cloud ConsoleでMaps JavaScript APIキーを取得します。

| Option | 説明 |
|--------|-------------|
| API Key | Google Maps APIキー |
| Map Type | `roadmap` / `satellite` / `hybrid` / `terrain` |

### Mapbox / MapTiler

MapLibre GLとネイティブに統合され、なめらかな描画を実現するベクタータイルプロバイダーです。

| Option | 説明 |
|--------|-------------|
| API Key / Token | 各サービスのダッシュボードから取得 |
| Style | スタイルURLまたはプリセットを選択 |

### RainViewer

APIキー不要で無料で使用できます。リアルタイムレーダーと最大2時間分の過去データに対応します。

AoTサーバーがCORSプロキシ（`/api/geo/proxy/rainviewer/*`）経由でリクエストを中継するため、クライアントが外部サービスに直接アクセスすることはありません。

### ISRIC (SoilGrids)

WMS経由で世界の土壌データ（有機物、pH、窒素含有量）を提供します。スマートファームにおける土壌分析に役立ちます。

### Sentinel Hub (Sentinel-2)

10m 解像度の Sentinel-2 画像です。MODIS NDVI が 250m 画素 1つで覆う 6.25ha を、ここでは 625画素で見るため、圃場内の生育のばらつきが見えるようになります。

[Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/) で無料アカウントを作成し、ダッシュボードで OAuth クライアントを作成して Client ID と Secret を入力します。Sentinel Hub は OAuth2 client credentials 方式のため、タイルは AoT サーバーが代わりに取得します(`/api/geo/proxy/sentinelhub/<unique_id>`) — Secret がブラウザに渡ることはありません。

| オプション | 説明 |
|--------|-------------|
| レイヤー | NDVI、トゥルーカラー、NDMI（水分）、NDWI（水域）、フォールスカラー |
| コレクション | L2A（大気補正済み）または L1C |
| 検索期間 | 単一の日付では雲で画面が欠けるため、この期間内で利用可能な直近のシーンを描画します |
| 最大雲量 / シーン優先度 | その期間内でどのシーンを選ぶか |

無料枠は月 30,000 PU です。地図画面 1回で約 4 PU、タイルは 1日キャッシュし、ズーム 9 未満では取得しません — 10m データを広域で見ても予算を使うだけで得るものがありません。

### Agromonitoring（圃場 NDVI・土壌）

登録した圃場境界の NDVI 統計と、**土壌水分・地温を数値で**返す唯一のレイヤーです。SMAP オーバーレイは 9km の画像であり、NASA GIBS の凡例に出る土壌水分の数値は Open-Meteo のモデル値を借りたものです。

圃場は Agromonitoring のダッシュボードで描きます（1〜3000ha）。ポリゴン ID を貼り付けるか、空欄にすればクリック地点を含むポリゴンを自動で照合します。API キーは OpenWeatherMap と同じアカウントのものです。

値はサーバー経由で取得し(`/api/geo/proxy/agromonitoring/<unique_id>`)、30分キャッシュします — 無料枠の呼び出し上限が公開されていないためです。

---

## WMSレイヤー

WMS（Web Map Service）1.3.0準拠のサーバーであれば、どれでも統合できます。

| Option | 説明 |
|--------|-------------|
| URL | WMSサーバーのGetCapabilities URL |
| Layers | 表示するレイヤー名（カンマ区切り） |
| Format | `image/png` または `image/jpeg` |
| CRS | 座標系（通常は `EPSG:3857`） |

AoTサーバーはWMSタイルのリクエスト（`/api/geo/proxy/wms/<unique_id>`）をプロキシし、CORSの問題を解決します。

---

## レイヤーの順序と表示

GridStackレイアウト内でレイヤーをドラッグすると並び順を変更できます。順序は自動的に保存されます。

各レイヤーの**目のアイコン**を使うと、一時的に表示・非表示を切り替えられます。**Activate/Deactivate** はレイヤーを恒久的に有効・無効にします。

---

## レイヤープレビュー

レイヤー項目の **Preview** ボタンをクリックすると、そのレイヤーが地図上でどう見えるかをポップアップで確認できます。

- MapTilerとRainViewerについては、APIキーの有効性も同時に確認されます。
- プレビューが表示されない場合は、APIキーまたはネットワーク接続を確認してください。

---

## 関連ページ

- [Global GIS Settings（GIS全体設定）](settings.md) — デフォルトレイヤーの選択、テーマカラー
- [Design Tool（デザインツール）](design-tool.md) — レイヤー制御パネルの使い方
- [Parcel Import（筆地インポート）](parcel-import.md) — VWorldの使い方
