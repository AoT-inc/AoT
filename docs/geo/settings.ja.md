# GIS全体設定

`/geo/setting` ページでは、システム全体のGISデフォルト設定を行います。設定は `geo_setting` テーブルにシングルトンレコードとして保存されます。

---

## デフォルトの初期位置 { #default-start-location }

地図ウィジェットとデザインツールを最初に開いたときに表示されるデフォルトの位置です。

| 項目 | デフォルト | 説明 |
|-------|---------|-------------|
| Latitude（緯度） | 37.5665 | ソウル中心部 |
| Longitude（経度） | 126.9780 | ソウル中心部 |
| Zoom Level（ズームレベル） | 12 | 初期ズーム（小さいほど広い範囲、大きいほど近く） |

希望する位置とズームに地図を移動してから、**Current View（現在の表示）** 行の **Get Location（位置を取得）** を押すと、3つの項目が現在の地図表示の値で埋まります。

---

## デザインのテーマカラー { #design-theme-colors }

デザインツールと地図ウィジェットで使われる、レイヤーごとの色です。

| レイヤー | 意味 |
|-------|---------|
| Site | サイト境界 |
| Zone | ゾーン境界 |
| Facility | 施設の建物 |
| Equipment | 機器 |
| Device | AoTデバイスマーカー |
| Panel Background | プロパティパネルの背景 |

各行にはカラーピッカーがあります。一度も保存していない色は、いま実際に使われている色（グローバルの既定値）を表示したまま未設定の状態で残り、自分で変更したときだけ保存されます。**Panel Opacity（パネルの不透明度）** のスライダー（0〜100%、5刻み）が1つあり、プロパティパネルの背景に適用されます。

---

## 地図の挙動

### ズーム設定 { #zoom-settings }

| 項目 | デフォルト | 説明 |
|-------|---------|-------------|
| Max Zoom（最大ズーム） | 25 | 地図の最大ズームレベル（1〜30を入力可能） |
| Equipment Hide Zoom（機器の非表示ズーム） | 15 | このズームレベルより下ではEquipmentの項目が非表示になります（1〜25を入力可能） |

**Equipment Hide Zoom** は、ズームアウトしたときに大量の機器の項目で地図が見づらくなるのを防ぎます。ズームが `15` を下回ると、配管、接続点、散水範囲、3D施設モデルが自動的に非表示になります。AoTデバイスのマーカーはこの設定の対象外で、どのズームでも表示され続けます。

### ズーム方式 { #zoom-method }

| 項目 | デフォルト | 説明 |
|-------|---------|-------------|
| Digital Zoom（デジタルズーム） | On | タイルの解像度を超えてもCSSスケールでズームを継続する |
| Smooth Zoom（スムーズズーム） | On | ピンチズーム中になめらかに補間する |

---

## パフォーマンスと描画 { #performance-rendering }

| 項目 | デフォルト | 説明 |
|-------|---------|-------------|
| Tile Fade Animation（タイルのフェードアニメーション） | On | タイル読み込み時のフェードインアニメーション |
| Serve MapLibre Locally（MapLibreをローカル配信） | On | MapLibre GLライブラリをCDNの代わりにローカルのファイルで配信します。オフにするとCDNからライブラリを読み込みます |
| Prefer Canvas Rendering（Canvas描画を優先） | Off | SVGよりCanvasレンダラーを優先する（Leafletモードのみ） |

### ポリゴン表示の上限 { #polygon-display-limits }

地図設定と一緒に保持される上限値です。保存され、ここで編集できますが、現在の地図の描画にはまだ反映されません。

| 項目 | デフォルト |
|-------|---------|
| Max Site Polygons | 1000 |
| Max Zone Polygons | 1000 |
| Max Device Polygons | 1000 |

---

## 単位設定 { #unit-settings }

施設の工学計算や寸法入力で使う長さの単位を選択します。

| コード | 表示 |
|------|---------|
| `m` | メートル（デフォルト） |
| `cm` | センチメートル |
| `mm` | ミリメートル |
| `ft` | フィート |
| `in` | インチ |

---

## API { #api }

```http
GET /api/geo/settings
```

現在のグローバル設定をJSONとして返します。設定編集の権限が必要で、権限がない場合はリクエストが拒否されます。

レスポンスは `{"ok": true, "saved_state": { ... }, "geo_layers": [...], "search_inputs": [...], "search_provider": "..."}` です。`saved_state` には保存済みの設定が入り（デフォルトの初期ズームは `zoom` キーで返ります）、保存された地図プロバイダーのキーも含まれます。

```http
POST /api/geo/settings
Content-Type: application/json

{
  "default_lat": 37.5665,
  "default_lng": 126.9780,
  "default_zoom": 12,
  "max_zoom": 25,
  "equipment_cull_zoom": 15,
  "digital_zoom": true,
  "smooth_zoom": true,
  "tile_fade_animation": true,
  "maplibre_local_serving": false,
  "prefer_canvas": false,
  "search_provider": "",
  "max_polygons_site": 1000,
  "max_polygons_zone": 1000,
  "max_polygons_device": 1000,
  "theme_site": "#2563eb",
  "theme_zone": "#16a34a",
  "theme_facility": "#ea580c",
  "theme_equipment": "#6b7280",
  "theme_device": "#dc2626",
  "theme_panel_bg": "#ffffff",
  "theme_panel_opacity": 90
}
```

すべてのキーは任意です。送らなかったキーは保存済みの値がそのまま残り、許可リストにないキーは黙って無視されます。JSONのほかフォームエンコードの本文も受け付けます。テーマの値は入れ子のオブジェクトではなく、フラットな `theme_*` キーとして送ります。デザインドロワーの表示トグルも同じ `theme_*` 系のキーで保存されます。`search_provider` が空の場合は「地図設定に従う」です。保存に成功すると `{"ok": true, "message": "Settings Saved"}` が返り、保存にも設定編集の権限が必要です。

長さの単位はこのエンドポイントには含まれず、専用のエンドポイントがあります。

```http
GET /api/geo/settings/length_unit
PUT /api/geo/settings/length_unit
Content-Type: application/json

{ "length_unit": "m" }
```

`GET` は現在の単位とサポートする単位の一覧を返し、`PUT` は一覧にない値を拒否します。

---

## 関連ページ

- [GIS Layers（GISレイヤー）](layers.md) — プロバイダーのAPIキー登録
- [Design Tool（デザインツール）](design-tool.md) — テーマカラーの反映確認
