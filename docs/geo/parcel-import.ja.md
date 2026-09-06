# 筆地インポート

韓国の地籍データ（VWorld）を使って、地図上にサイト境界をすばやくインポートします。ポリゴンを手動で描く代わりに、住所検索やCSVファイルを使うことで、正確な地籍境界を即座に生成できます。

---

## 事前準備

VWorldのAPIキーを登録しておく必要があります。

1. `/geo/layer` でVWorldレイヤーを追加します。
2. 歯車アイコン → APIキーを入力 → Save。
3. Activateで有効化します。

---

## 住所からインポートする

1. `/geo/design` に移動します。
2. 上部ツールバーの **Parcel Import** ボタンをクリックします。
3. 住所を入力します（例: `123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do`）。
4. **Search** をクリックします。
5. 検索結果から筆地を選択します。
6. 筆地の境界が地図上にプレビューとして表示されます。
7. **Save as Site** をクリックします。

筆地の境界は `Site` タイプのGeoShapeとして保存されます。

---

## CSV一括インポート

複数の筆地を一度にインポートする場合に使います。

### CSVファイル形式

```csv
address,name
123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do,Greenhouse Site 1
124 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do,Greenhouse Site 2
456 Ipbuk-dong, Gwonseon-gu, Suwon-si, Gyeonggi-do,Admin Building Site
```

項目:
- `address`（必須）: 道路名住所または地番住所
- `name`（任意）: サイト名。省略した場合、住所の文字列が名前として使われます。

### インポート方法

1. `/geo/design` の上部ツールバーで **Parcel Import → CSV Import** を選択します。
2. CSVファイルを選択するか、ドラッグ&ドロップします。
3. プレビューテーブルでデータを確認します。
4. エラーのある行は赤色で強調表示されます（住所が認識できない場合）。
5. **Import** をクリックします。

処理結果が表示されます。
- Success（成功）: Siteフィーチャーが作成されました
- Failure（失敗）: 住所検索に失敗しました（住所の形式を確認してください）

---

## APIを直接使用する

自動化スクリプトから筆地インポートを呼び出すには、REST APIを使用します。

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
  "pnu": "4159025300100230000",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[...], ...]]
  },
  "address": "123 Gojung-ri, ...",
  "area_m2": 3256.7
}
```

### CSV一括インポート

```http
POST /api/geo/parcel/from_csv
Content-Type: multipart/form-data

file=<CSV file>
```

### Siteとして保存する

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "geo_id": "<map UUID>",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "name": "Greenhouse Site 1"
}
```

---

## 注意事項

- 対応しているのは韓国国内の住所のみです（VWorld PNU APIを使用）。
- 住所認識に失敗する場合は、道路名住所と地番住所の両方を試してください。
- 大きなCSV（100行以上）は処理に時間がかかることがあります。
- インポートした筆地は、他のSiteフィーチャーと同じように編集できます。

---

## 関連ページ

- [Design Tool（デザインツール）](design-tool.md) — Siteモードでの手動描画
- [GIS Layers（GISレイヤー）](layers.md) — VWorld APIキーの登録
