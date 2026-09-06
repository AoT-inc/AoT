# GIS全体設定

`/geo/setting` ページでは、システム全体のGISデフォルト設定を行います。設定は `geo_setting` テーブルにシングルトンレコードとして保存されます。

---

## デフォルトの初期位置

地図ウィジェットとデザインツールを最初に開いたときに表示されるデフォルトの位置です。

| 項目 | デフォルト | 説明 |
|-------|---------|-------------|
| Latitude（緯度） | 37.5665 | ソウル中心部 |
| Longitude（経度） | 126.9780 | ソウル中心部 |
| Zoom level（ズームレベル） | 13 | 初期ズーム（1=世界、22=建物） |

希望する位置とズームレベルに移動してから **Set to Current Position** をクリックすると、これらの項目に自動入力されます。

---

## デザインのテーマカラー

デザインツールと地図ウィジェットで使われる、レイヤーごとの色です。

| レイヤー | 意味 |
|-------|---------|
| Site | サイト境界 |
| Zone | ゾーン境界 |
| Facility | 施設の建物 |
| Equipment | 機器 |
| Device | AoTデバイスマーカー |
| Panel Background | プロパティパネルの背景 |

各項目には、カラーピッカーと不透明度スライダー（0〜100%）があります。

---

## 地図の挙動

### ズーム設定

| 項目 | デフォルト | 説明 |
|-------|---------|-------------|
| Max Zoom（最大ズーム） | 22 | 地図の最大ズームレベル |
| Equipment Cull Zoom（機器の間引きズーム） | 15 | このズームレベルより下ではEquipment/Deviceのマーカーが非表示になります |

**Equipment Cull Zoom** は、ズームアウトしたときに大量のデバイスマーカーで地図が見づらくなるのを防ぎます。ズームが `15` を下回ると、Equipment/Deviceのマーカーは自動的に非表示になります。

### ズーム方式

| 項目 | デフォルト | 説明 |
|-------|---------|-------------|
| Digital Zoom（デジタルズーム） | Off | タイルの解像度を超えてもCSSスケールでズームを継続する |
| Smooth Zoom（スムーズズーム） | On | ピンチズーム中になめらかに補間する |

---

## パフォーマンスと描画

| 項目 | デフォルト | 説明 |
|-------|---------|-------------|
| Tile Fade Animation（タイルのフェードアニメーション） | On | タイル読み込み時のフェードインアニメーション |
| Prefer Canvas（Canvasを優先） | Off | SVGよりCanvasレンダラーを優先する（Leafletモードのみ） |

### ポリゴン表示の上限

ダッシュボードの地図ウィジェットで一度に描画するポリゴンの数を制限します。上限を超えた分はクラスタリングされます。

| 項目 | デフォルト |
|-------|---------|
| Max Site polygons（Siteポリゴンの上限） | 500 |
| Max Zone polygons（Zoneポリゴンの上限） | 1000 |
| Max Device markers（Deviceマーカーの上限） | 2000 |

---

## 単位設定

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

現在のグローバル設定をJSONとして返します。

```http
POST /api/geo/settings
Content-Type: application/json

{
  "default_lat": 37.5665,
  "default_lng": 126.9780,
  "default_zoom": 13,
  "max_zoom": 22,
  "equipment_cull_zoom": 15,
  "digital_zoom": false,
  "smooth_zoom": true,
  "tile_fade_animation": true,
  "prefer_canvas": false,
  "length_unit": "m",
  "max_polygons_site": 500,
  "max_polygons_zone": 1000,
  "max_polygons_device": 2000,
  "theme_config": {
    "site": { "color": "#2563eb", "opacity": 0.3 },
    "zone": { "color": "#16a34a", "opacity": 0.3 },
    "facility": { "color": "#ea580c", "opacity": 0.4 },
    "equipment": { "color": "#6b7280", "opacity": 0.5 },
    "device": { "color": "#dc2626", "opacity": 1.0 }
  }
}
```

---

## 関連ページ

- [GIS Layers（GISレイヤー）](layers.md) — プロバイダーのAPIキー登録
- [Design Tool（デザインツール）](design-tool.md) — テーマカラーの反映確認
