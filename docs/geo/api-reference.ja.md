# GIS APIリファレンス

すべてのGIS APIエンドポイントはログインが必要です。データを変更するエンドポイントには `edit_settings` または `edit_controllers` の権限が必要です。

---

## 地図デザイン

### 新しいデザインを初期化する

```http
GET /api/geo/init_design
```

新しい空の地図デザインを作成し、そのUUIDを返します。

### デザインを取得する

```http
GET /api/geo/designs/<map_uuid>
```

保存された地図の全状態（フィーチャー、ズーム、中心座標、レイヤー設定）を返します。

### デザインを一覧表示する

```http
GET /api/geo/designs
```

登録されているすべての地図の一覧を返します。

### デザインを保存する

```http
POST /api/geo/designs
Content-Type: application/json

{
  "name": "Main Farm Map",
  "lat": 37.5665,
  "lng": 126.9780,
  "zoom": 16
}
```

### デザインを削除する

```http
DELETE /api/geo/designs/<map_uuid>
```

---

## オーバーレイ（フィーチャー）

### オーバーレイを一覧表示する

```http
GET /api/geo/overlays/list
```

すべてのGeoShapeフィーチャーの一覧を返します。

### オーバーレイを読み込む

```http
GET /api/geo/overlays?geo_id=<map_uuid>
```

指定した地図のすべてのフィーチャーを、GeoJSONのFeatureCollectionとして返します。

### オーバーレイを保存する（全件）

```http
POST /api/geo/overlays
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [...] },
      "properties": {
        "type": "site",
        "name": "Site 1",
        "unique_id": "<uuid>"
      }
    }
  ]
}
```

### 差分保存（効率化）

全フィーチャーの代わりに、追加・変更・削除されたフィーチャーだけを送信します。大規模な地図でのパフォーマンスが向上します。

```http
POST /api/geo/overlays/delta
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "added": [...],
  "modified": [...],
  "deleted": ["<uuid1>", "<uuid2>"]
}
```

---

## 施設

### 施設を一覧表示する

```http
GET /api/geo/facility/list
```

### 施設を取得する

```http
GET /api/geo/facility/<facility_uuid>
```

外皮パラメータ、センサー・アクチュエーターの割り当て、3D設定を含む、施設の全データを返します。

### 施設を作成／更新する

```http
POST /api/geo/facility
Content-Type: application/json

{
  "unique_id": "<uuid>",
  "name": "Greenhouse Block 1",
  "shape_uuid": "<geo_shape_uuid>",
  "preset": "greenhouse",
  "structure": "single",
  "bay_count": 1,
  "envelope": {
    "material": "vinyl_double",
    "bay_width_m": 8.0,
    "length_m": 50.0,
    "eave_height_m": 3.5,
    "ridge_height_m": 2.0
  },
  "sensors": [
    {
      "role": "indoor_temp",
      "device_id": "<input_uuid>",
      "measurement_id": "<measurement_uuid>",
      "name": "Indoor Temperature Sensor"
    }
  ],
  "actuators": [
    {
      "role": "heater",
      "device_id": "<output_uuid>",
      "name": "Heater"
    }
  ]
}
```

### 施設を削除する

```http
DELETE /api/geo/facility/<facility_uuid>
```

### 容量計算のプレビュー

保存せずに、外皮パラメータに対する工学計算の結果を返します。

```http
POST /api/geo/facility/compute
Content-Type: application/json

{
  "envelope": {
    "material": "vinyl_double",
    "bay_width_m": 8.0,
    "length_m": 50.0,
    "eave_height_m": 3.5,
    "ridge_height_m": 2.0
  },
  "bay_count": 3
}
```

レスポンス:
```json
{
  "area_m2": 1200.0,
  "volume_m3": 5400.0,
  "heating_load_kw": 42.3,
  "cooling_load_kw": 31.7,
  "forced_ventilation_m3h": 32400,
  "natural_ventilation_m3h": 15000
}
```

### 統合状態

施設に割り当てられたすべてのセンサー・アクチュエーターの現在値を返します。

```http
GET /api/geo/facility/<facility_uuid>/integration
```

### 実行時状態

リアルタイムのセンサー値、アクチュエーターの状態、アラートの概要を返します。

```http
GET /api/geo/facility/<facility_uuid>/runtime
```

### 換気シミュレーション

自然換気の風圧シミュレーション結果を返します。

```http
GET /api/geo/facility/<facility_uuid>/wind?wind_speed=3.5&wind_dir=270
```

### 設定を適用する

施設に割り当てられたアクチュエーターにコマンドを送信します。

```http
POST /api/geo/facility/<facility_uuid>/apply
Content-Type: application/json

{
  "actions": [
    { "role": "heater", "state": true }
  ]
}
```

---

## 試運転

### 試運転を開始する

```http
POST /api/geo/facility/<facility_uuid>/commissioning/start
```

レスポンス:
```json
{
  "check_id": "<uuid>",
  "status": "running"
}
```

### 試運転結果を取得する

```http
GET /api/geo/facility/<facility_uuid>/commissioning/<check_id>
```

### 判定を送信する

```http
POST /api/geo/facility/<facility_uuid>/commissioning/<check_id>/verdict
Content-Type: application/json

{
  "device_id": "<uuid>",
  "verdict": "approved"
}
```

---

## 筆地インポート

### 住所で筆地を検索する

```http
POST /api/geo/parcel/from_address
Content-Type: application/json

{
  "address": "123 Gojung-ri, Songsan-myeon, Hwaseong-si"
}
```

### CSV一括インポート

```http
POST /api/geo/parcel/from_csv
Content-Type: multipart/form-data

file=<CSV file>
```

### 筆地をSiteとして保存する

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "name": "Greenhouse Site 1"
}
```

---

## プロキシサービス

AoTサーバーは、CORSポリシーによりクライアントから直接アクセスするのが難しい外部サービスを中継します。

| エンドポイント | 対象サービス |
|----------|---------------|
| `GET /api/geo/proxy/rainviewer/*` | RainViewerの降雨レーダー |
| `GET /api/geo/proxy/isric` | ISRIC SoilGridsの土壌データ |
| `GET /api/geo/proxy/openweather` | OpenWeatherの気象オーバーレイ |
| `GET /api/geo/proxy/openmeteo` | Open-Meteoの気象予報 |
| `GET /api/geo/proxy/wms/<unique_id>` | WMSレイヤータイル |
| `GET /api/geo/tile_proxy` | 汎用タイルプロキシ（NASA、Naver、Kakao） |

---

## 設定

### グローバル設定を取得する

```http
GET /api/geo/settings
```

### グローバル設定を保存する

```http
POST /api/geo/settings
Content-Type: application/json

{ ... }
```

リクエストの完全なスキーマについては[GIS Settings（GIS設定）](settings.md#api)を参照してください。

---

## デバイス一覧

地図に配置できるAoTデバイスの一覧を返します。

```http
GET /api/geo/devices
GET /api/geo/inputs
GET /api/geo/outputs
```

---

## 配管の自動生成

デバイス間の最適な配管ルートを自動的に生成します。

```http
POST /api/geo/generate-pipes
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "device_ids": ["<uuid1>", "<uuid2>", "<uuid3>"]
}
```

---

## レスポンスコード

| コード | 意味 |
|------|---------|
| 200 | 成功 |
| 201 | 作成成功 |
| 400 | 不正なリクエスト（入力エラー） |
| 401 | 認証が必要 |
| 403 | 禁止 |
| 404 | リソースが見つからない |
| 500 | サーバーエラー |
