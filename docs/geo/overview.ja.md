# GIS & 地図システム概要

AoT GISシステムは、MapLibre GLベクター地図エンジンの上に、デバイス監視・施設設計・外部GISレイヤー統合を一つにまとめた統合地理空間プラットフォームです。

---

## システム構成

```
GIS & Map System
├── 地図エンジン
│   ├── MapLibre GL（主力 — ベクター/3D）
│   └── Leaflet 互換シム（レガシー対応）
│
├── 管理ページ
│   ├── /geo/design   — 地図デザインツール
│   ├── /geo/facility — 施設管理
│   └── /geo/layer    — GISレイヤー管理
│
├── ダッシュボードウィジェット
│   ├── AoT_map      — リアルタイムデバイス監視マップ
│   └── AoT_facility — 3D施設環境モニター
│
└── API
    └── /api/geo/*   — 30以上のRESTエンドポイント
```

---

## 主な機能

### 地図デザインツール

- **6つの編集モード**: Site（サイト）→ Zone（ゾーン）→ Facility（施設）→ Plot（区画）→ Equipment（機器）→ Device（デバイス、モードバーでは「A」と表示）
- **ベクター描画**: ポリゴン、ポリライン、円、マーカーの作成・編集
- **筆地インポート**: VWorld住所検索またはCSV一括インポートで、サイト境界を即座に生成
- **差分保存**: 変更されたフィーチャのみを送信するため、大規模な地図でも高速に保存できます

### 区画とプログラム

- **区画（Plot）**: どこで、いつから、何を目標に育てているか — Plotモードで図形を描きますが、記録（作物・品種・日付・生育段階のスケジュール）は図形とは別に保存され、図形を描き直しても、シーズンが終わっても残ります。
- **プログラム（Program）**: 再利用可能なテンプレート（「トマトを5段階で、この目標に向けて」）。区画に紐づけると、現在の生育段階・目標環境・終了予定日が自動的に反映されます。
- **種類（Kind）**: 区画とプログラムはどちらも種類を持ちます — 作物、家畜、施設、その他 — 同じ種類同士でしか紐づけられません。
- **日誌（Journal）**: 選んだ期間について、区画・ゾーン・サイトが何を育て、何を計測し、どう制御されたかをその時点のまま記録する（再計算されない）スナップショットで、引き継ぎや認証提出に使います。

### 施設管理

- **3Dパラメトリックレンダリング**: Three.jsを使い、建物構造パラメータから自動生成
- **建物外皮の設定**: 資材（ビニール／ガラス／PC）、断熱材、開口部（窓／ドア／換気窓）
- **工学計算**: 暖房・冷房負荷、換気能力、自然換気の風圧シミュレーション（±5〜10%の参考値）
- **センサー・アクチュエーターの割り当て**: 役割（温度／湿度／CO₂など）ごとにAoTデバイスを関連付け
- **試運転**: デバイスの通信確認と診断ワークフロー
- **AIアドバイス**: 施設の学習に基づく自動化の提案

### GISレイヤー

23の外部GISプロバイダーと連携しています。

| カテゴリ | プロバイダー |
|----------|-----------|
| 国内（韓国） | VWorld、Kakao Maps、Naver Maps |
| 海外 | OpenStreetMap、Google Maps、ESRI、Bing、Mapbox、MapTiler、Carto、Stadia |
| 衛星 | NASA GIBS、ESA |
| 気象 | RainViewer（レーダー）、OpenWeather、Open-Meteo |
| 地形 | OpenTopoMap、Thunderforest |
| 専門分野 | ISRIC（土壌）、GSI（日本）、SGIS（シンガポール） |

---

## 技術スタック

| レイヤー | 技術 |
|-------|-----------|
| 地図レンダリング | MapLibre GL JS |
| 3D表示 | Three.js + GLTF |
| 描画ツール | terra-draw（Geoman API互換） |
| 空間演算 | Turf.js |
| マーカークラスタリング | Leaflet.MarkerCluster |
| WMS対応 | MapLibre + CORSプロキシ |
| バックエンド | Python/Flask、SQLAlchemy |
| データベース | SQLite（設定）、InfluxDB（時系列） |

---

## データモデル

| テーブル | 役割 |
|-------|------|
| `geo_map` | 保存された地図ビュー（中心座標、ズーム、プロバイダー、スタイル） |
| `geo_setting` | GISのグローバル設定（シングルトン） |
| `geo_shape` | GeoJSONオーバーレイフィーチャ（サイト／ゾーン／施設／デバイス） |
| `geo_layer` | 外部GISレイヤーのソース登録 |
| `geo_facility` | 施設建物の仕様（外皮、センサー、アクチュエーター、棟） |
| `geo_model_asset` | 3Dアセットライブラリ（プリミティブ／GLTF） |

---

## 機能階層

```
Site          ← Top-level boundary (polygon)
  └── Zone    ← Growing blocks / sections
        ├── Facility   ← Building unit
        ├── Plot       ← What/since when/toward what (区画とプログラム参照)
        ├── Equipment  ← Pumps, valves, piping, irrigation
        └── Device     ← AoT Input/Output/Function markers
```

上から順に、サイト（最上位の境界・ポリゴン）→ ゾーン（栽培ブロック・区分）→ その下に施設・区画・機器・デバイスが並ぶ階層になります。区画・機器・デバイスがどのゾーンに属するかは地図上に描かれた位置で決まり、一覧から選ぶものではありません。

---

## 関連ページ

- [Getting Started（はじめに）](getting-started.md)
- [Design Tool（デザインツール）](design-tool.md)
- [筆地インポート](parcel-import.md)
- [Facility Management（施設管理）](facility.md)
- [区画](plots.md)
- [管理プログラム](programs.md)
- [日誌](journal.md)
- [GIS Layers（GISレイヤー）](layers.md)
- [Map Widget（地図ウィジェット）](map-widget.md)
- [Facility Widget（施設ウィジェット）](facility-widget.md)
- [AoT_plot ウィジェット](plot-widget.md)
- [Settings（設定）](settings.md)
- [API Reference（APIリファレンス）](api-reference.md)
