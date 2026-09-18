# 筆地インポート

韓国の地籍データ（VWorld）を使って、地図上にサイト境界をすばやくインポートします。ポリゴンを手動で描く代わりに、住所検索やCSVファイルを使うことで、正確な地籍境界を即座に生成できます。

---

## 事前準備

VWorldのAPIキーを登録しておく必要があります。

1. `/geo/layer` でVWorldレイヤーを追加します。
2. 歯車アイコン → APIキーを入力 → Save。
3. Activateで有効化します。

---

## インポートダイアログを開く

1. `/geo/design` に移動します。
2. 地図下のモードバーで **Site** モードに切り替えます。
3. Site設定ドロワーで **Add from Address** 横の **Search** ボタンをクリックします。

これで **Import Site by Address** ダイアログが開きます。**Address Input** と **CSV Batch** の2つのタブがあります。

---

## 住所からインポートする（Address Input）

1. 住所を入力します（例: `東京都渋谷区…` のように）。カンマ区切りで複数入力するか、**Add Address** ボタンで入力欄を増やせます。
2. **Search** をクリックします。
3. 見つかった筆地が下のプレビューリストに表示され、地図上にも境界が描かれます。失敗した住所は理由とともに表示されます。

---

## CSV一括インポート（CSV Batch）

複数の筆地を一度にインポートする場合に使います。

### CSVファイル形式

住所のみを1行に1つ、**1列目**に入力します。ヘッダー行も名前列もありません — 他の列があっても無視され、インポートされる各Siteの名前は住所そのもの（または保存時の **Site Name** 欄）から決まります。

```csv
123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do
124 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do
456 Ipbuk-dong, Gwonseon-gu, Suwon-si, Gyeonggi-do
```

### インポート方法

1. **CSV Batch** タブでCSVファイルを選択します。
2. **Upload and Process** をクリックします。
3. 結果は住所検索と同じプレビューリストに表示されます — 成功した筆地には✓、失敗した住所には理由が付きます。

---

## 確認して保存する

どちらのタブも同じプレビュー領域を共有します。

- **Merge Adjacent Parcels**（チェックボックス、デフォルトはオフ）— プレビュー内で隣接するポリゴンをturf.jsで1つのSiteに統合してから保存します。オフのままだと、プレビューの各筆地がそれぞれ個別のSiteとして保存されます。
- **Site Name** — 最初の結果の名前が自動入力されます（複数件のときは「+ N件」が付きます）。保存前に編集できます。統合しない複数の筆地を保存する場合（結果がちょうど1件でない限り）、このフィールドではなく各筆地が自分自身の名前で保存されます。
- **Save as Site** — プレビュー中のすべての筆地（または統合結果1件）を保存します。

保存後、ステータス行に **saved**（保存済み）・**already imported**（既にインポート済み、下記参照）・**failed**（失敗）の件数がそれぞれ表示されます。

!!! note "同じ筆地を2回インポートしても重複は作られません"
    現在の地図に同じジオメトリのSiteが既にある場合、再度保存を試みてもエラーではなくスキップとして扱われ、「既にインポート済み」として別集計されます。

保存された筆地は `Site` タイプのGeoShapeであり、手描きのSiteフィーチャーと同じように編集できます。

---

## APIを直接使用する

自動化スクリプトから筆地インポートを呼び出すには、REST APIを使用します。上記のUIも、結局は以下の3つのエンドポイントをそのまま呼び出す薄いクライアントです。

### 住所からインポートする

```http
POST /api/geo/parcel/from_address
Content-Type: application/json

{
  "address": "123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do"
}
```

レスポンス:
```json
{
  "ok": true,
  "feature": {
    "type": "Feature",
    "geometry": { "type": "Polygon", "coordinates": [[[...], ...]] },
    "properties": { "name": "..." }
  },
  "name": "123 Gojung-ri, ...",
  "pnu": "4159025300100230000"
}
```
失敗時: `{"ok": false, "error": "..."}`。

### CSV一括インポート

```http
POST /api/geo/parcel/from_csv
Content-Type: multipart/form-data

file=<CSVファイル、1行に住所1つ、1列目のみ使用>
```

レスポンス:
```json
{
  "ok": true,
  "features": [ /* 成功した住所ごとのGeoJSON Feature */ ],
  "names": [ "..." ],
  "errors": [ "<住所>: <理由>", "..." ]
}
```

### Siteとして保存する

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "feature": { "type": "Feature", "geometry": { "type": "Polygon", "coordinates": [...] }, "properties": {} },
  "name": "Greenhouse Site 1",
  "map_uuid": "<map UUID>"
}
```

`map_uuid` は実在する地図である必要があります。同じ地図に同じジオメトリのSiteが既にある場合、新規作成の代わりに `409` と `{"ok": false, "duplicate": true, "shape_id": ..., "existing_name": "..."}` を返します。

---

## 注意事項

- 対応しているのは韓国国内の住所のみです（VWorld PNU APIを使用）。
- 住所認識に失敗する場合は、道路名住所と地番住所の両方を試してください。
- 大きなCSV（100行以上）は、行ごとにVWorldへの問い合わせが発生するため処理に時間がかかることがあります。
- インポートした筆地は、他のSiteフィーチャーと同じように編集できます。

---

## 関連ページ

- [Design Tool（デザインツール）](design-tool.md) — Siteモードでの手動描画
- [GIS Layers（GISレイヤー）](layers.md) — VWorld APIキーの登録
