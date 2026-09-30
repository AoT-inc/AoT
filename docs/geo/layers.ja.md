# GISレイヤー管理

`/geo/layer` ページは、外部の地図データソースを登録・管理する場所です。登録したレイヤーは、デザインツールやダッシュボードの地図ウィジェットでベースレイヤーやオーバーレイとして使用できます。

---

## 対応プロバイダー

### 国内（韓国） { #domestic-korea }

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| VWorld | `gis_vworld` | 政府公式地図、地籍、航空写真、住所からの筆地照会 | 必須 |
| Kakao Maps | `gis_kakao` | 韓国の標準地図・衛星・ハイブリッドのタイル | 不要 |
| Naver Maps | `gis_naver` | 韓国の標準地図・衛星・地形のタイル | 不要 |

### 海外一般 { #international-general }

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| OpenStreetMap | `gis_osm` | 無料のオープンソース地図 | 不要 |
| Google Maps | `gis_google` | 衛星写真／道路地図／ハイブリッド | 必須 |
| ESRI | `gis_esri` | World Imagery の衛星写真 | 不要 |
| Mapbox | `gis_mapbox` | プリセット8スタイルの地図タイル | 必須 |
| MapTiler | `gis_maptiler_vector` | ベクタータイル、多様なスタイル | 必須 |
| Bing | `gis_bing` | 航空写真、ラベル付き航空写真、道路地図 | 任意 |
| Carto | `gis_carto` | 抑えたデザインの地図（Positron、Dark Matter、Voyager） | 不要 |
| Stadia Maps | `gis_stadia` | 高品質なデザイン地図 | 必須 |
| Thunderforest | `gis_thunderforest` | サイクリング／ハイキング／交通に特化 | 必須 |

### 衛星／航空写真 { #satellite-aerial }

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| NASA GIBS | `gis_nasa_gibs` | 衛星画像と環境レイヤー、日付を選択可能 | 不要 |
| Soil Moisture (NASA SMAP) | `gis_esa` | 約9kmの表層土壌水分（0〜5cm）オーバーレイ、日付を選択可能 | 不要 |
| Sentinel Hub | `gis_sentinelhub` | Sentinel-2 10m 解像度の NDVI・水分・水域指数 | 必要（OAuth クライアント） |

### 気象オーバーレイ { #weather-overlays }

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| RainViewer | `gis_rainviewer` | リアルタイムおよび過去の降雨レーダー | 不要（プレミアムのみ必要） |
| OpenWeather | `gis_openweather` | 雲、降水、気圧、風、気温のレイヤー | 必須 |
| KMA Weather | `gis_kma` | 韓国気象庁の500m観測値を地図の凡例として表示 | 必須 |
| Open-Meteo | (組み込みプロキシ) | 気象予報データ | 不要 |

### 専門データ { #specialized-data }

| プロバイダー | タイプコード | 特徴 | APIキーが必要か |
|----------|-----------|----------|-----------------|
| OpenTopoMap | `gis_opentopomap` | 等高線・地形図 | 不要 |
| ISRIC | `gis_isric` | 世界の土壌データ（SoilGrids） | 不要 |
| GSI | `gis_gsi` | 日本の国土地理院 | 不要 |
| SGIS | `gis_sgis` | 韓国統計庁の統計地理情報 | 必要 |
| Agromonitoring | `gis_agromonitoring` | 圃場単位の NDVI 統計・土壌水分・地温 | 必要 |

---

## レイヤーを登録する方法 { #how-to-register-a-layer }

1. `/geo/layer` に移動します。
2. 画面上部の **Select GIS Service** ドロップダウンから目的のプロバイダーを選択します。
3. **Add** をクリックします。レイヤーは無効の状態で作成されます。
4. 新しく追加された項目の **Settings（歯車）アイコン** をクリックします。
5. 必要なオプション（APIキー、レイヤータイプなど）を入力します。
6. **Save** をクリックし、続けて **Activate** をクリックして有効化します。

---

## プロバイダー別設定

### VWorld { #vworld }

韓国の国家空間情報基盤プラットフォームです。VWorld開発者サイト（https://map.vworld.kr）でAPIキーを取得する必要があります。

| Option | 説明 |
|--------|-------------|
| API Key | VWorld APIキー |
| Registered Domain | キーを登録したドメイン。空欄の場合は現在のアクセスURLが使われます |
| Map Layer / Style | 背景: `Base Map` / `Satellite` / `Hybrid` / `Gray Map` / `Dark Map`。オーバーレイ: 地籍図、農業振興地域、生態自然度、開発制限区域、個別公示地価 |
| Show Legend | そのレイヤーの凡例を地図に表示するか |

VWorldは**筆地インポート**にも使用されます。住所検索を機能させるにはAPIキーの登録が必要で、登録済みのVWorldレイヤーが有効化されていなくても、そのレイヤーのキーが読み取られます。

### Google Maps { #google-maps }

Google Cloud ConsoleでMaps JavaScript APIキーを取得します。

| Option | 説明 |
|--------|-------------|
| Google Maps API Key | Google Maps APIキー |
| Map Style | `Roadmap` / `Satellite` / `Hybrid` / `Terrain` のいずれか1つ |

### Mapbox / MapTiler { #mapbox-maptiler }

MapTiler はベクタータイルを提供し、MapLibre GL が直接描画します。Mapbox は選んだスタイルで描画された地図タイルとして提供されます。

| Option | 説明 |
|--------|-------------|
| API Key / Token | 各サービスのダッシュボードから取得 |
| Map Style | プリセットのスタイルから1つ選択（Mapbox 8種、MapTiler 6種） |
| Label Language | MapTiler のみ — 地図ラベルの言語（例: `ko`、`en`、`auto`） |

### RainViewer { #rainviewer }

APIキーなしで使用できます — キー入力欄は RainViewer のプレミアム機能用です。リアルタイムレーダーと最大2時間分の過去データ（10分間隔で12コマ）に対応します。レーダーの詳細度はズーム7あたりで頭打ちになります。

レーダータイルはブラウザーが RainViewer から直接取得し、AoT サーバーを経由するのは利用可能なコマの一覧だけです（`/api/geo/proxy/rainviewer/*`）。一覧を取得できない場合はエラーを出さず、コマがない状態のままになります。

### ISRIC (SoilGrids) { #isric-soilgrids }

pH（水）、粘土・砂・シルト含量、土壌有機炭素、仮比重を、いずれも 0〜5cm 深さについて WMS 経由で提供します。詳細度は元データの 250m グリッドで頭打ちになるため、それ以上拡大しても同じ画像が大きくなるだけです。スマートファームにおける土壌分析に役立ちます。

### Sentinel Hub (Sentinel-2) { #sentinel-hub-sentinel-2 }

10m 解像度の Sentinel-2 画像です。MODIS NDVI が 250m 画素 1つで覆う 6.25ha を、ここでは 625画素で見るため、圃場内の生育のばらつきが見えるようになります。

[Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/) で無料アカウントを作成し、ダッシュボードで OAuth クライアントを作成して Client ID と Secret を入力します。Sentinel Hub は OAuth2 client credentials 方式のため、タイルは AoT サーバーが代わりに取得します(`/api/geo/proxy/sentinelhub/<unique_id>`) — Secret がブラウザに渡ることはありません。

| オプション | 説明 |
|--------|-------------|
| レイヤー | NDVI、トゥルーカラー、NDMI（水分）、NDWI（水域）、フォールスカラー |
| コレクション | L2A（大気補正済み）または L1C |
| 検索期間 | 単一の日付では雲で画面が欠けるため、この期間内で利用可能な直近のシーンを描画します |
| 最大雲量 / シーン優先度 | その期間内でどのシーンを選ぶか |

無料枠は月 30,000 PU です。地図画面 1回で約 4 PU、タイルは 1日キャッシュし、ズーム 9 未満では取得しません — 10m データを広域で見ても予算を使うだけで得るものがありません。

### Agromonitoring（圃場 NDVI・土壌） { #agromonitoring-field-ndvi-soil }

登録した圃場境界の NDVI 統計と、**土壌水分・地温を数値で**返す唯一のレイヤーです。SMAP オーバーレイは 9km の画像であり、NASA GIBS の凡例に出る土壌水分の数値は Open-Meteo のモデル値を借りたものです。

圃場は Agromonitoring のダッシュボードで描きます（1〜3000ha）。ポリゴン ID を貼り付けるか、空欄にすればクリック地点を含むポリゴンを自動で照合します。どのポリゴンにも含まれない地点を押した場合は、中心が最も近いポリゴンが代わりに使われます。API キーは OpenWeatherMap と同じアカウントのものです。

**Active Channels** で表示する値を選びます — NDVI（平均）、土壌水分、地表地温、10cm 地温。**NDVI Search Window**（14・30・60・90日、既定は30日）は直近の観測をどこまで遡って探すかを決めます。雲が続くと数週間、使えるシーンがないこともあります。

値はサーバー経由で取得し(`/api/geo/proxy/agromonitoring/<unique_id>`)、30分キャッシュします — 無料枠の呼び出し上限が公開されていないためです。

---

## WMSレイヤー { #wms-layers }

一部の提供元は、オーバーレイを完成したタイルではなく WMS（Web Map Service）方式で配信します — VWorld のデータオーバーレイ（地籍図、農業振興地域、生態自然度、開発制限区域、個別公示地価）と ISRIC SoilGrids です。WMS を個別に入力する項目はありません。提供元を登録し、その設定で必要なチャンネルを選びます。

| リクエストの項目 | 値 |
|--------|-------------|
| リクエスト | `GetMap`、タイル1枚は 256×256 の画像 |
| バージョン | `1.3.0`。提供元が別の値を宣言していればそれに従います |
| 座標系 | 常に `EPSG:3857` |
| 画像形式 | 透過ありの `image/png`。提供元が別の値を宣言していればそれに従います |

これらの画像は AoT サーバーが代わりに取得します（`/api/geo/proxy/wms/<unique_id>`）。対象のサービスがブラウザーから直接読み取ることを許可していないためです。地図上で見える違いは2点あります。

- 上流のサーバーがエラーを返す、または15秒以内に応答しない場合、そのオーバーレイだけが空のまま残り、地図の他の部分はそのまま動作し、エラーとしては通知されません。失敗は保持しないため、サービスが復旧すればオーバーレイもすぐに再表示されます。
- 一度取得した画像はサーバーで1週間、ブラウザーで1日再利用されるため、上流での変更がその分遅れて見えることがあります。レイヤー自体の設定を変更した場合は即座に反映されます。

---

## レイヤーの順序と表示 { #layer-order-and-visibility }

各レイヤー左側のつまみをドラッグすると並び順を変更できます。ドロップした時点で新しい順序が保存されます。画面が狭く一覧が1列になっている場合は、そこでドラッグしても保存された順序は変わりません。

各行の **Activate**／**Deactivate** は、そのレイヤーを地図で使うかどうかを決めます。どのチャンネルを表示するかは設定画面のプレビュー地図にあるレイヤーボタンで選び、その選択はレイヤーと一緒に保存されます。

---

## レイヤープレビュー { #layer-preview }

レイヤーの設定画面（歯車アイコン）を開くと、上部にプレビュー地図が現れ、その時点で入力されているオプションのまま描画されます。オプションを変えるたびに再描画されるため、保存する前にキーやスタイルを確認できます。

- プレビュー右上のレイヤーボタンで背景地図を切り替え、オーバーレイのチャンネルを表示・非表示できます。この選択はレイヤーと一緒に保存されます。
- プレビューが表示されない場合は、APIキーまたはネットワーク接続を確認してください。

---

## 関連ページ

- [Global GIS Settings（GIS全体設定）](settings.md) — デフォルトレイヤーの選択、テーマカラー
- [Design Tool（デザインツール）](design-tool.md) — レイヤー制御パネルの使い方
- [Parcel Import（筆地インポート）](parcel-import.md) — VWorldの使い方
