# GIS API リファレンス

このページのすべてのエンドポイントはログイン(セッションクッキー、または[APIキー](../Security.md#api-keys))が必要です。データを変更するエンドポイントはリソースに応じて `edit_settings`・`edit_controllers`・`edit_plots` のいずれかの権限も必要とし、特定の地図・施設に紐づくエンドポイントはさらに呼び出し元のアクセスグループがその地図・施設をカバーしているかも検査します(`scope.can_operate`)。必要な権限が `edit_settings` 以外の場合は各節に明記しています。

> **既知の重複:** `POST /api/geo/designs`、`GET`/`DELETE /api/geo/designs/<uuid>`、`GET`/`POST /api/geo/overlays` は、コード上でそれぞれ2か所(flask-restxのリソースとして1つ、通常のFlaskルートとして1つ)定義されています。Flaskのルート登録順序により、この5つの経路は実際にはflask-restx側だけが動作し、通常ルート側の実装は呼び出されません。以下の説明は実際に動作するflask-restx側の挙動を基準にしています。この重複は内部的な整理課題であり、ドキュメント化された契約の一部ではないため、予告なく整理される可能性があります。

---

## 地図デザイン { #design-maps }

「デザイン」とは1件の `GeoMap` レコードのことです — 独自の中心座標・ズーム・レイヤー状態を持ち、その上に描かれたすべての図形(サイト、ゾーン、施設、デバイス)を保持する、名前の付いた地図です。地図の作成・変更・削除・復元には `edit_settings` が必要で、その地図が呼び出し元に付与された範囲内にある必要があります(でなければ `403`)。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/init_design` | 最後に更新された地図を読み込みます — ユーザーごとではなく、全員が同じ地図に入ります。地図が1件もなければ、設定された既定の位置・ズームで `Design Map 1` を作成します。全体の状態を返します。 |
| GET | `/api/geo/designs` | すべての地図を `{unique_id, name, latitude, longitude, zoom}` 形式で一覧します。中心座標とズームは各地図に保存されたカメラから取得し、保存されたカメラがまったく無い地図だけが `[37.5665, 126.9780]` / ズーム13に落ちます。 |
| GET | `/api/geo/designs/list` | 地図セレクターが使う、ほぼ同じ内容の2つ目の一覧です。レスポンス形式も値も上と同じです。 |
| GET | `/api/geo/designs/<map_uuid>` | 地図1件の全状態: `{ok, uuid, name, state}`。見つからなければ404。 |
| POST | `/api/geo/designs` | 地図を作成(`map_uuid` を省略)、または名前・状態を更新します。ボディ: `{map_uuid?, name, state}` — `state` は既存の状態に**マージ**され、丸ごと置き換わるわけではありません。すでに存在しない `map_uuid` を送った場合はエラーにせず、その idで新規作成します。作成時はボディの `center`/`zoom` を使わず、設定された既定の開始ビューで新しい地図を開きます。レスポンス: `{ok, uuid, name}`。 |
| DELETE | `/api/geo/designs/<map_uuid>` | 地図とその上のすべて(施設の設定値 → 施設 → 図形 → 地図レコードの順)を削除します。この地図の外から参照されているものが残っていれば `409 {blocked: true}` を返します。 |
| POST | `/api/geo/maps/<map_uuid>/restore-original` | マイグレーション前のスナップショット(`original_data`)を持つ図形をすべてそのスナップショットへ復元します。レスポンス: `{ok, map_uuid, restored, skipped}`。マイグレーション追跡用カラムが未適用の場合(`alembic upgrade head` が必要)は400。 |

---

## オーバーレイと図形(GeoJSON) { #overlays-shapes-geojson }

「オーバーレイ」とは地図上に描かれたGeoJSON図形 — サイト、ゾーン、施設の外形、デバイスマーカー、機器のことです。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/overlays/list?map_uuid=&target_type=&parent_id=&device_id=` | 下と同じ、地図1つ分の `FeatureCollection` です — ただしここでは絞り込みの引数名が `type` ではなく `target_type` です。`map_uuid` がない場合は空のコレクションが返ります。 |
| GET | `/api/geo/overlays?map_uuid=<uuid>&type=&parent_id=&device_id=` | 1つの地図の図形をGeoJSONの `FeatureCollection` として返します。`type` は旧名称もマッチします(`equipment` ⇒ `equipment_collection`、`aot_device` ⇒ `device`)。各図形にはサーバー側で `db_id`、`shape_uuid`(図形自身の識別子 — クライアントが作る `node_id` とは別の値)、解決済みの `device_id`/`device_type`、`parent_id`、(`type=facility` の場合)3Dメタデータが付与されます。まとめて保存された機器は、返すときに再び個々の図形に展開されます。 |
| POST | `/api/geo/overlays` | 1つの `map_uuid` + `type` に対する一括保存/置換です。このページで最も複雑なエンドポイントなので、下の**詳細**で別途説明します。 |
| POST | `/api/geo/overlays/delta` | 全図形の代わりに変更分だけを送ります — 大規模な地図で有利です。ボディ: `{map_uuid, upserts: [...], deletes: [node_idまたはdb_id, ...]}`。機器の upsert はまとめ行にマージされ、一時的なスプリンクラーの点マーカーはこの経路でも除外されます。こちらも `edit_settings` と地図スコープが必要です。 |
| GET | `/api/geo/sites` | `site` タイプの図形すべてをGeoJSONで。`?map_uuid=` は任意。 |
| GET | `/api/geo/zones` | `zone` タイプの図形すべてをGeoJSONで。`?map_uuid=` は任意。 |
| GET | `/api/geo/shapes/<category>` | 任意の図形カテゴリ(`site`、`zone`、`facility`、`feature` など)をGeoJSONで。 |
| POST | `/api/geo/generate-pipes` | 保存せずにデバイス間の配管ルートだけを計算します。ボディ: `{parent_feature, ref_line, config, map_uuid}`。 |

### 詳細: `POST /api/geo/overlays` { #details-post-apigeooverlays }

- 受け取った図形は `db_id`、次に `node_id` の順で既存レコードと照合されます。それ以外はすべてここから派生します。
- **ボディに含まれていないというだけでは削除されません。** 明示的な `deletes: [node_idまたはdb_id, ...]` リスト、または `features: []` と `allow_empty: true` の組み合わせだけがレコードを削除します(過去に「ボディにない」を「削除」として扱ってしまい、図形が丸ごと消えた事故があったための仕様です)。
- `aot_device` の空のボディは、すべてのマーカーを消す代わりにそのまま拒否されます — デバイスの配置は `POST /api/geo/device/location` を通してのみ行います。
- `equipment` の図形は1つにまとめられた `equipment_collection` レコードとして保存されます(セット全体を丸ごと置換)。それ以外は図形単位で保存されます。まとめ保存の経路は既存のセットを先に削除するため、空の機器ボディは `allow_empty: true` で確認しない限り拒否され、何件削除しようとしたかも併せて返します。
- 一時的に表示されるスプリンクラーの点マーカーは保存されずに除外されます — そのマーカーだけのボディは空として扱われます。
- 幾何ルールは何かを書き込む前に検査され、不正な図形が1つでもあれば保存全体が幾何エラーで中断されます(機器はこの検査の対象外)。
- `aot_type`・`device_id`・`channel_id` は保存されるJSONから取り除かれます — 読み取り時に導出される値のため、そのまま往復保存されることは期待できません。
- レスポンス: `{ok, count, id_map: {node_id: db_id}, stats: {deleted, updated, inserted}}`(機器の一括保存経路では `stats.mode: 'bulk_bundle'` 形式)。

---

## 検索 { #search }

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/geo/search` | 検索プロバイダとして設定されたGISインプットモジュール経由のジオコーディング/住所検索です。ボディ: `{query, type: 'address'(デフォルト), layer_id?}`。`layer_id` で特定の `GeoLayer` を指定でき、なければ地図の `search_provider` 設定、最終的には `gis_osm` にフォールバックします。レスポンス: `{ok, results}`(形式はプロバイダごとに異なります)。 |

---

## デバイスの割り当て { #device-binding }

「割り当て」とは、デバイス(センサーまたはアクチュエーター)を空間上のスロット — ゾーンのポリゴン、施設のフィッティング、センサーロールなど — に結びつけることです。割り当ては履歴を持つ独立したオブジェクトです — 1つを解除しても、レコード自体は(監査のために)残ります。書き込みには `edit_settings` が必要です。

共通フィールド(`spatial_kind`、`spatial_id`、`role`、`device_id`、`device_kind`、`channel_id`、`measurement_id`)は下の**詳細**を参照してください。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/binding?spatial_kind=&spatial_id=&role=` | 1つのスロットの現在の割り当てと過去の履歴。レスポンス: `{ok, bindings, history}`(`history` は終了済みのものだけ)。`spatial_kind` か `spatial_id` が欠けていれば `400`。 |
| POST | `/api/geo/binding` | 空いているスロットにデバイスを割り当てます。すでに割り当て済みなら `409 {conflict: true}`、未知のデバイス/図形なら `400`。 |
| PUT | `/api/geo/binding` | スロットのデバイスを差し替えます — 既存の割り当てを終了(履歴に保持)し、新しい割り当てを1回の呼び出しで作成します。 |
| GET | `/api/geo/binding/unbound?kinds=&facility_uuid=&map_uuid=` | まだ何も割り当てられていないスロットの一覧(空のゾーンポリゴン、デバイスを失った施設フィッティングなど) — 「何を配線すべきか」の画面用です。`kinds` は常に具体的な空間種別に絞り込んで使うべきです。 |
| DELETE | `/api/geo/binding/<binding_uid>` | 割り当てを終了します(`valid_to` を設定、レコードは保持)。ボディ/クエリ: `reason`(デフォルト `unbound`)。存在しないIDなら `404`。 |

### 詳細: 割り当てのフィールド { #details-binding-fields }

- `spatial_kind`: `shape` \| `fitting` \| `actuator` \| `sensor_role` \| `weather`。
- `spatial_id`: スロットの識別子。`spatial_kind=shape` の場合、保存済みの `GeoShape.unique_id` でも、まだ保存されていないクライアント側の `node_id` でもよく、サーバー側でどちらも解決します(保存前の識別子の検索が1つの地図の中に収まるよう、`map_uuid` も一緒に送ってください)。
- `role`: そのスロットの用途(`marker`、`area`、`actuator`、`sensor` など)。図形スロットの場合、roleはその図形自身の `type` からサーバー側で導出されます — 図形についてはクライアントから送られた値は信頼されません。デバイスを掛ける場所ではない種別の図形は(ゾーンのポリゴンと位置マーカーのみ可能です)そのまま拒否されます。
- `device_id`: `<device_uuid>::<channel>` というサフィックスを受け付け、分離されて `channel_id` になります。
- `device_kind` はクライアントが送っても、サーバー側で常に再検証・再解決されます。

---

## デバイスの位置・一覧・詳細 { #device-location-lists-detail }

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/geo/device/location` | デバイスの地図上の位置を設定/移動します。他の地図編集の書き込みと同じく `edit_settings` が必要です。ボディ: `{unique_id, type, lat, lng, map_uuid?, channel_id?}` — `type` は `input\|output\|pid\|trigger\|conditional\|device\|function\|custom\|generic_function` のいずれかで、`channel_id` の代わりに `unique_id` に `::<channel>` サフィックスを付けてもかまいません。デバイス自身の座標はチャンネル `0` のときだけ書き込まれ、他のチャンネルで呼ぶとそのチャンネルのマーカーだけが動き、デバイスの座標はそのままです。`map_uuid` が指定されていれば、その地図上にもマーカーを配置/更新し、所属ゾーンを導出します。成功時はデーモンに対して該当デバイスの設定再読み込みをベストエフォートで要求します(位置変更でタイムゾーンが変わった場合に即座に反映されるように)。該当するデバイスが無ければ `404`、デバイスまたは `map_uuid` が指す地図が呼び出し元に付与された範囲外なら `403`。レスポンス: `{ok, message, overlay_id}`。 |
| GET | `/api/geo/devices?map_uuid=&device_ids=&include_all=` | 地図に配置可能なデバイスの一覧。レスポンス: `{ok, devices, all_measurements_map}`。条件付き(304)レスポンスに対応。 |
| GET | `/api/geo/inputs` | センサーフィッティングの割り当て画面用、チャンネル単位のフラットな一覧(`DeviceMeasurements`) — 有効化された入力のみで、各項目にデバイス・チャンネルと換算後の単位を含むラベルが入ります。 |
| GET | `/api/geo/outputs` | アクチュエーターフィッティングの割り当て画面用の `Output` フラット一覧。出力ごとに種類とインターフェースも含まれます。 |
| GET | `/api/geo/device/<device_uuid>/detail` | デバイスモーダルの全データ: 識別情報、所属エリア、制御方式(オン/オフ、値、PWM、3方向)、チャンネル、複合デバイスの子デバイス、ランタイム情報(経過時間/前回作動時間/保留中のスケジュール)。`?channel=`(デフォルト `0`)でランタイムの数値をどのチャンネルから見るかを決めます。 |
| POST | `/api/geo/link_status` | 地図バッジ用のバッテリー/RSSI一括取得。ボディ: `{ids: [...]}`(最大100件)。バッテリーや通信品質が `null` の場合、その値を持つチャンネルが無いという意味です — このときバッジは0%として描かず、まったく描きません。 |
| POST | `/api/geo/device/split-apply` | ゾーンを複数の区画(ストリップ/グリッド)に分割し、各区画にデバイスマーカーの図形を作成して、その区画内にあるデバイスマーカーへ自動的に割り当てます。`edit_plots` が必要です。`name` で名前のベースを決め、`device_kind` でどの種類のデバイスが区画を取れるかを絞れます — 空にすると全種類が候補になり、マーカーが混在する地図ではほとんどが曖昧なまま残ります。サーバーはプレビューが見せたポリゴンを信頼せず、同じパラメータで幾何を再計算します。その分割パラメータと*プレビュー*エンドポイント(下記 `GET /api/geo/plot/split-preview`)は、栽培区画の分割機能と共有しています — 分割結果がデバイスになろうと区画になろうと、幾何計算自体は同じだからです。レスポンス: `{ok, created, info, assigned, unassigned, message?}` で、`message` は中のデバイスが1つに特定できなかった区画がいくつあるかを伝えます。 |

---

## ゾーン { #zones }

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/zone/<zone_uuid>/contents` | ゾーンの「[環境・制御]」モーダル用デバイス一覧(ゾーン内のセンサー/出力/ファンクション)。サーバーキャッシュ30秒。 |
| GET | `/api/geo/zone/<zone_uuid>/allocation?on=YYYY-MM-DD` | ゾーンの面積が配下の各区画にどう配分されているか(区画ごとの面積/割合 + 未割り当ての残り)。区画同士が重なっていると合計が100%を超えることがあり、その場合は `overlaps` で示されます。 |
| GET | `/api/geo/zone/<zone_uuid>/output_history?output_id=<uuid>&hours=` | 下記 `GET /api/geo/output/<uuid>/history` の旧エイリアスです。パスのゾーンは存在確認にのみ使われ、履歴そのものは `output_id` だけで参照します。 |
| POST | `/api/geo/zone/<zone_uuid>/photo` | ゾーンの代表画像アップロード(マルチパート `photo`)。 |
| POST | `/api/geo/zone/<zone_uuid>/rep_key` | ゾーンの「代表」測定値を設定/解除します。 |
| POST | `/api/geo/zone/<zone_uuid>/hidden_rows` | ボディ: `{card, keys}` — このゾーンで非表示にするステータスカードの行。 |
| POST | `/api/geo/zone/<zone_uuid>/output_order` | ボディ: `{order}` — ゾーンのデバイス一覧の表示順を保存します。 |
| POST | `/api/geo/shape/<shape_uuid>/description` | サイトまたはゾーンの自由記述(2000文字以内)。 |

---

## サイト { #sites }

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/site/<site_uuid>/contents` | サイト内のデバイス一覧(施設のフィッティングとして使われているアクチュエーターは除く — それらはサイトではなく所属する施設に属します)。 |
| GET | `/api/geo/site/<site_uuid>/summary?force=` | サイトのステータス/本日のタスク/ノートの集計。30秒キャッシュ(`force=1` で無視)。 |
| GET | `/api/geo/site/<site_uuid>/weather` | 現在割り当てられている気象観測デバイス。レスポンス: `{selected, source, candidates}`。 |
| POST | `/api/geo/site/<site_uuid>/weather` | ボディ: `{device_ids: [...]}`(空配列でもキー自体は必須) — サイトの気象ソースを設定します。 |

---

## 施設 { #facilities }

「施設」とは、外皮(寸法・素材)を持ち、センサー・アクチュエーターが割り当てられた構造物(温室、畜舎など)です。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/facility/list?geo_id=<map_uuid>` | すべての施設。地図1つに絞り込むことも可能。各項目に `rep_key` と外周形状を含みます。 |
| GET | `/api/geo/facility/<facility_uuid>` | 施設の全データ: 外皮、デバイスの割り当て、3D形状・表示オプション、ベイ、最後に計算された容量。 |
| POST | `/api/geo/facility` | 作成または更新(本体・外皮スペック・ベイをひとつのトランザクションとして原子的に処理)。ボディ: `facility_uuid?`(作成時は省略)、`geo_id`(必須)、`outer_geometry`(GeoJSONジオメトリ、作成時は必須)、`name`、`preset`、`structure`、`bay_count`、`geometry_3d: {span_width_m, length_m, eave_height_m, ridge_height_m, spacing_m, roof_type}`、`envelope`(被覆層と側窓・天窓・カーテンの設定)、`actuators`、`fittings`、`bays`、`notes`。 |
| POST | `/api/geo/facility/<facility_uuid>/clone` | 施設を複製し、デバイスの割り当てはリセットします(複製先は元の配線を引き継ぎません)。複製は元の真上ではなく隣に配置されます。 |
| DELETE | `/api/geo/facility/<facility_uuid>` | ボディ/クエリ: `confirm_name` が現在の施設名と一致している必要があります。外周形状とベイ形状も一緒に削除されます。 |
| POST | `/api/geo/facility/compute` | 保存せずに、与えられたスペックに対する工学計算プレビュー(面積/体積/暖房・冷房負荷/換気量)を返します。ボディは保存と同じ形 — `geometry_3d`、`envelope`、`bay_count`、`structure`、あれば `outer_geometry`/`fittings`/`actuators`。数値は一次算定の参考値(±5〜10%)で、免責の注記が付きます。計算モジュールが利用できない場合は `501`。 |
| GET | `/api/geo/facility/<facility_uuid>/integration` | 統合されたセンサー/アクチュエーター割り当てビュー — 環境コーディネーター自身が読み取るものと同じデータで、外皮・換気開口部・計算された容量も併せて返します。 |
| GET | `/api/geo/facility/<facility_uuid>/wind?speed=&dir=&pct=` | 自然換気の風圧シミュレーション。`speed`=風速 m/s(デフォルト3.0)、`dir`=気象風向 0〜359°(デフォルト0)、`pct`=開口率 0〜100(デフォルト100)。実効換気回数(ACH)、流入・流出量、開口部ごとの流量、アクチュエーターごとの風向重みを返します。 |
| POST | `/api/geo/facility/<facility_uuid>/apply` | 施設に割り当てられたアクチュエーターへ命令を送ります。ボディ: `{horizon, commands: [{kind, action, pct?}, ...]}`、`action` は `off`/`on`/`set` のいずれか。`horizon`(`now`/`1h`/`6h`)は予約ではありません — 命令は即時に送られ、この値はシミュレーション区間だけを決めます。`set` はその出力が実際に対応する方式(アナログ値、PWM、時間指定のon/off)に変換され、割り当てのない `kind` はリクエスト全体を失敗させず `failed` に入ります。VEE(仮想実行エンジン)機能フラグが有効な場合、まずアドバイザリの事前シミュレーションを実行し、実際の命令送信はいずれの場合もデーモンを経由します。 |

作成・複製・削除・計算・実行には `edit_settings` が必要で、参照系のエンドポイントはログインのみで足ります。実行にはその施設に対する操作権限も必要です。命令と点検は施設にまだ紐づいているデバイスにしか届きません — 切れた紐づけはスキップされます。

施設のリアルタイム状態確認/制御(実時間のアクチュエーター状態、安全範囲の設定値、手動制御、非常停止)は**別のURLプレフィックスを使う別系統のAPI**です — 下記の[施設のリアルタイム制御](#facility-runtime-control-apiaotfacility-apiaotcoordinator)を参照してください。

### 施設の3Dモデルアセット { #facility-3d-model-assets }

施設のデフォルトのパラメトリック形状の代わりに取り付けられる再利用可能な3Dモデル(プリミティブ、または取り込んだ `.glb`/`.gltf` ファイル)です。ログインのみで利用でき(追加の権限チェックなし)、一覧/作成は `owner_user_id = current_user.id` に絞られます(取得/更新/削除/アタッチをidで直接行う場合は所有者チェックはありません)。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/model_assets?kind=&tag=` | 現在のユーザーが持つモデルアセットの一覧。 |
| POST | `/api/geo/model_assets` | 作成。JSONボディまたはマルチパート(`kind=imported_gltf` の場合は `file` フィールドが必須)。フィールド: `name`、`kind`(デフォルト `primitive`)、`spec_json`、`authored_unit`(デフォルト `m`)、`tags`、`notes`。アップロードファイル: 25MB以下、許可された拡張子のみ、`.glb` はマジックバイト(`glTF` ヘッダー)検証あり。作成後にプレビュー画像のレンダリングをトリガーします。 |
| GET | `/api/geo/model_assets/<asset_uuid>` | アセット1件を取得。なければ404。 |
| PUT | `/api/geo/model_assets/<asset_uuid>` | `name`/`spec_json`/`authored_unit`/`tags`/`notes`/`sort_order` を更新(ボディに含まれるキーのみ反映)。プレビューを再レンダリングします。 |
| DELETE | `/api/geo/model_assets/<asset_uuid>` | アセットのレコードとディスク上のファイルを削除します。まだ参照している施設があれば `409`(`referencing_facilities` を含む)。 |
| POST | `/api/geo/model_assets/<asset_uuid>/regenerate_preview` | サムネイルを強制的に再レンダリングします。 |
| POST | `/api/geo/facility/<facility_uuid>/attach_model` | 施設にモデルアセットを取り付けます(`render_mode='asset'`)。ボディ: `{asset_uuid, transform?}`(`transform` のデフォルトは位置・回転が単位元、スケール1)。 |
| DELETE | `/api/geo/facility/<facility_uuid>/attach_model` | 取り付けを解除します(`render_mode` は `parametric` に戻ります)。 |

### 施設の試運転 { #facility-commissioning }

設置後の検証: 施設のアクチュエーターに対して自動チェックを実行し、アクチュエーターごとに人が判定を記録します。結果の取得を除き `edit_settings` が必要です。チェックはメモリ上にのみ保持されるため、再起動すると進行中のものは失われます。測定段階は周期的なセンサー値を与えないと進みませんが、現在それを供給する箇所がないため、開始したチェックは最初のベースライン段階に留まり、アクチュエーターごとの結果は出ず、判定もまだ提出できません。

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/geo/facility/<facility_uuid>/commissioning/start` | ボディ: `{actuator_ids?}`(省略時は施設の全アクチュエーター)。レスポンス: `{ok, check_id, actuator_count}`。施設が存在しなければ `404`、チェック対象がなければ `400`。 |
| GET | `/api/geo/facility/<facility_uuid>/commissioning/<check_id>` | チェックの状態/結果をポーリングします。ログインのみ必要、追加の権限は不要。チェックが別の施設のものであれば `403`、存在しなければ `404`。 |
| POST | `/api/geo/facility/<facility_uuid>/commissioning/<check_id>/verdict` | ボディ: `{actuator_id, verdict: 'ok'\|'sensor'\|'device'\|'external'\|'skip', note?}`。判定によって、レスポンスの `actions` 一覧として返るフォローアップが決まります: `ok` はキャリブレーション基準値の登録、`sensor` はセンサーを信頼不可としてマークし点検期間のデータを除外、`device` は制御ゲインの上限を下げてアラームを登録、`external` は点検期間のデータ除外のみ、`skip` は何も行いません。データ除外を除くものは施設側に記録されます。判定値が不正、またはそのアクチュエーターの結果がまだ無い場合は `400`。 |

---

## 施設のリアルタイム制御 (`/api/aot/facility`、`/api/aot/coordinator`) { #facility-runtime-control-apiaotfacility-apiaotcoordinator }

ここは**別のURLプレフィックス**(`/api/geo/` ではなく `/api/aot/`)を使います — 施設の環境コーディネーターが稼働し始めた後のリアルタイム側: ステータス、安全範囲の設定値、手動介入、非常停止、履歴です。上記の施設と概念的には同じオブジェクト(同じ `facility_uuid`)ですが、ルートの系統が異なるだけです。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/aot/facility/<facility_uuid>/status?function_uuid=` | ポーリング用の軽量ステータスバッジ(約5秒間隔): `{level: 'idle'\|'warn'\|'active'\|'emergency', reasons, active_count, total_count, function_active, function_stale, function_name}`。 |
| GET | `/api/aot/facility/<facility_uuid>/setpoints` | 保存済みの**安全範囲**の上下限に加え、`effective`(制御ループが実際に追従しているリアルタイムの目標 — これはここではなく区画のプログラム/ステージから来ます)。 |
| POST | `/api/aot/facility/<facility_uuid>/setpoints` | `edit_settings` が必要。ボディ: `guide_t_min_c`/`guide_t_max_c`、`guide_rh_min_pct`/`guide_rh_max_pct`、`temp_min_c`/`temp_max_c`、`humid_min_pct`/`humid_max_pct` のいずれか(すべて範囲検証あり)。`target_vpd_kpa`/`target_co2_ppm` をここに送ると拒否されます — 目標値は栽培プログラム経由でのみ設定します。変更値は連携しているすべての環境コーディネーターのファンクションに反映され、即座に再読み込みがトリガーされます。 |
| POST | `/api/aot/facility/<facility_uuid>/control` | コーディネーターを経由しない単一アクチュエーターの手動制御で、安全ゲートのインターロックが働きます(例: 風速の安全ゲートが強制的に閉じている換気窓を開けようとするリクエストは拒否されます)。`edit_settings` + 施設スコープが必要。ボディ: `{slot_key, action: 'on'\|'off'\|'set', percent?, reason?}`。オン/オフ機器に `set` でパーセントを与えると、60秒周期内の比例ON時間に変換されます(5%未満はオフ扱い)。ゲートに阻まれた場合は `400`、命令が機器に届かなかった場合は `502`。 |
| POST | `/api/aot/facility/<facility_uuid>/estop` | 非常停止 — **出力だけでなく、環境制御そのものを止めます。** この施設を制御していて稼働中の環境コーディネーターがあれば、そのコーディネーター自身の非常停止コマンドを使います: すべてのアクチュエーターを安全値へ(安全値がなければオフへ)送り、コーディネーターの次サイクルを60秒保留して、直後に機器を動かし直せないようにします。紐づくコーディネーターが無い、または停止している場合 — もしくはそのうち1つでも停止を確認できなかった場合 — に限り、出力を直接、安全な既定状態へ送る経路にフォールバックします(暖房/換気窓/ファン/CO2/灌水/照明はオフ、保温カーテンは展開、遮光カーテンは収納)。このフォールバックで命令を受けるのは、今この施設に紐づいている機器だけです。ボディ: `{confirm: "STOP"}`(この文字列と完全一致が必要)。`edit_settings` が必要。レスポンスはどちらの経路を通ったかに加え、適用/失敗の台数と、コーディネーターごと・機器ごとの結果を返します。アクチュエーターかコーディネーターのいずれか1つでも届かなかった場合、レスポンスは `ok` に**なりません**。 |
| GET | `/api/aot/facility/<facility_uuid>/runtime` | 重量級のリアルタイムスナップショット: 稼働履歴を含むアクチュエーター状態、保存済みの表示順、室内外センサー、ベイ、区画(予定のものも含む)、ベイごとの容量。オン/オフ機器には平常値(直近7日の日平均、当日は除外)も付き、稼働履歴は120秒キャッシュです。センサー値はコーディネーターが稼働していればそのサイクルスナップショットから、そうでなければバックグラウンドで更新されるキャッシュ(20秒)から来るため、最初の呼び出しではセンサーがまだ埋まりきっていないことがあります。条件付き(304)レスポンス対応。 |
| GET | `/api/aot/facility/<facility_uuid>/env_summary` | コーディネーターが直近サイクルでデーモンに保存したサマリー(時系列クエリなし — 1行だけを読む軽量な呼び出し)。古くなっているかどうかと、その判定に実際に使った基準(制御周期の3倍、最低300秒)も併せて返します。 |
| GET | `/api/aot/facility/<facility_uuid>/env_week?bay=&days=` | 日次の環境推移シリーズ(デフォルト7日、1〜31)。10分キャッシュ。描画した区間(開始・終了の日付)を施設自身のタイムゾーンで併せて返します。 |
| GET | `/api/aot/facility/<facility_uuid>/actuator_history?slot_key=&hours=` | アクチュエーター1件の稼働履歴(パーセント/デューティのシリーズ、なければオン/オフの継続時間で代替)。`hours` はデフォルト24、1〜168に制限。 |
| GET | `/api/aot/facility/<facility_uuid>/overview?fresh=` | 地図のポップアップが複数のリクエストを同時に発行しないよう、status + env_summary + info + irrigation + 気象リスク + プログラムの上下限 + サイト + エリアステータス + 代表値 + 非表示行 + 区画のGDD/DLIを1回にまとめて返します。30秒キャッシュ + シングルフライトロック(`fresh=1` で無視)。 |
| POST | `/api/aot/facility/<facility_uuid>/function_state` | ボディ: `{action: 'activate'\|'deactivate'}` — 連携している環境コーディネーターのファンクションをオン/オフします。`edit_controllers` + スコープが必要。 |
| GET | `/api/aot/facility/<facility_uuid>/info` | 地図ポップアップ用の代表写真/説明/寸法。 |
| POST | `/api/aot/facility/<facility_uuid>/info` | ボディ: `{description}`(2000文字以内)。`edit_settings` が必要。 |
| POST | `/api/aot/facility/<facility_uuid>/photo` | 代表写真のアップロード(マルチパート、png/jpg/jpeg/gif/webp)。`edit_settings` が必要。 |
| GET | `/facility_photo/<filename>` | アップロード済みの施設写真を配信します(ログイン必須、パストラバーサル対策あり)。 |
| POST | `/api/aot/facility/<facility_uuid>/rep_key` | 施設の代表測定値を設定/解除します。紐づく図形がなければ `422`。`edit_settings` が必要。 |
| POST | `/api/aot/facility/<facility_uuid>/hidden_rows` | 上記ゾーン版と同じ形式を施設に対して。`edit_settings` が必要。 |
| POST | `/api/aot/facility/<facility_uuid>/actuator_order` | ボディ: `{order: [slot_key, ...]}`。`edit_settings` が必要。 |
| GET | `/api/aot/facility/<facility_uuid>/bays` | ベイ選択用の `{ok, bays: [{id, name}]}`。 |
| POST | `/api/aot/facility/<facility_uuid>/bay_capacity` | ボディ: `{bay_id, unit, total}`(`total<=0` で解除)。`edit_settings` ではなく、**意図的に** `edit_plots`(シーズン運用者の権限)を要求します。 |
| GET | `/api/aot/facility/<facility_uuid>/calibration_status` | 連携するコーディネーターのアクチュエーターごとの制御ループのキャリブレーション状態と試運転状態、さらにモデル精度チェック(温度・湿度の誤差)が合格していればその結果も。 |
| GET | `/api/aot/coordinator/<function_uuid>/overview` | 環境コーディネーターの設定ページ用ヘッダー: どの施設を制御しているか、その施設の稼働中の区画とプログラム、その施設に実際にあるアクチュエーターの種類(存在しない設備を設定していることを画面が示せるように)、(同じ施設に非アクティブな重複コーディネーターがあれば)`other_coordinator` 警告。 |
| GET | `/api/aot/coordinator/<function_uuid>/actuators` | このコーディネーターが制御できるアクチュエーター、現在無効化されているもの(`disabled_actuators` オプション)、そして無効化されたエントリのうちもはや実在するデバイスに解決できないもの。コーディネーターが1つのベイにスコープされている場合は、そのベイの機器だけが並びます。 |

---

## 栽培プログラム { #cultivation-programs }

「プログラム」とは、区画が従う再利用可能な生育ステージのテンプレート(ステージ、GDD/DLI目標、灌水・施肥スケジュール)です。書き込みには `edit_plots` が必要です。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/programs?subject=&kind=&tab_id=` | 区画が使用できるプログラムの一覧。`subject` は `crop` もエイリアスとして受け付けます。並び順は subject → 品種の順です。 |
| GET | `/api/geo/program/<program_uuid>` | ステージ一覧を含むプログラムの全詳細。 |
| POST | `/api/geo/program` | 作成。ボディ: `name`、`subject`/`crop`、`kind`(デフォルト `vegetation`)、`stages`、`photosynthesis`、`target_defs`、`resource_defs`、`notes`、または組み込みテンプレートから始める `template_key`。テンプレートのステージ・目標は*コピー*されるため、後でテンプレートが変わってもそのプログラムには影響しません。常に `source: 'user'` として保存されます。 |
| POST / PUT | `/api/geo/program/<program_uuid>` | 更新。組み込み/外部プログラムは内容の編集を拒否します — 先に複製してください(下記)。`tab_id` のみのペイロードは組み込みプログラムでも許可されます(タブの移動は内容の編集ではないため)。AIエージェントが制御が実際に読む項目(ステージ、目標項目の定義、目標カーブ、光合成定数)を書いた場合、`source` が `ai` に変わり既存のレビュー履歴はクリアされ、その状態のプログラムは誰かがレビューするまで制御には使われません。名前・説明・タブだけの編集はこれに該当しません。 |
| DELETE | `/api/geo/program/<program_uuid>` | まだ参照している区画があれば拒否されます。 |
| POST | `/api/geo/program/<program_uuid>/clone` | 組み込み/外部プログラムを編集する唯一の方法 — 編集可能なコピーとして複製します。ボディで `name`、`subject`/`crop`、`kind`、`variety`、`stages`、`target_defs`、`photosynthesis`、`targets_methods`、`notes`、`tab_id` を上書きでき、コピーは元のタブではなく渡したタブ(渡さなければ既定のタブ)に置かれます。参照用に `derived_from` を記録します(生きたリンクではありません)。 |
| GET | `/api/geo/program-templates` | 組み込みのシードテンプレートのカタログ(データベースには保存されていません)。各項目は、ステージ数、目標を含むかどうか、そして広く(カテゴリ1つとその所属対象)始めるものか、特定の対象1つから始めるものかを併せて返します。 |
| GET | `/api/geo/target-methods` | プログラムのステージごとの固定値の代わりに目標として使える `Method`(時間軸カーブ)コントローラーの一覧。新しいカーブはここではなく専用の画面で作成します。 |
| GET | `/api/geo/target-measurements` | 目標がバインドできる測定値の語彙と、すべての種類の固定目標項目 — 保存する前に別の種類の項目一覧を画面で見せられます。バインドは任意です: 裏に測定値がない目標は表示専用のまま残ります。 |
| GET | `/api/geo/coordinator/<function_uuid>/plot-targets?on=YYYY-MM-DD` | 環境コーディネーターのファンクションが現在追従している区画とそのステージ目標を読み取り専用で表示します — 実際の制御が使うのと同じコードパスで計算するため、ここでの表示と実際の動作がずれることはありません。現在のユーザーが基準区画を指定できるかも併せて返すため、そのボタンは実際に通る場合だけ表示されます。 |
| POST | `/api/geo/coordinator/<function_uuid>/reference-plot` | ボディ: `{plot_uuid}`(空文字列で解除)。間作などで重なり合う候補区画が複数あるとき、コーディネーターが基準とする区画を固定します。存在しない区画なら `404`。値をコピーしないため、制御は次のサイクルからその区画のステージ目標に従います。 |

---

## 栽培区画

「区画」とは、ある土地または施設のベイ1か所での1回の作付けサイクルです — それ自体のステージのタイムライン・目標・スケジュールを持ち、従っている共有プログラムとは独立しています。書き込みには `edit_plots` が必要です。

### 一覧・詳細 { #listing-detail }

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/plots?map_uuid=&on=&include_ended=&include_planned=&facility_uuid=` | 区画の一覧。デフォルトは1つの地図の稼働中の区画のみ。`include_ended`/`include_planned` で範囲を広げられます。`map_uuid` を省略すると地図をまたいだ「運用」ビューになります。 |
| GET | `/api/geo/plot/<plot_uuid>` | 区画1件の詳細(保留中のステージ遷移があれば先に自動承認)。`can_edit`、`can_design`、その区画自身の今後のデバイススケジュールを含みます。 |
| GET | `/api/geo/plot/<plot_uuid>/contents` | 「[環境・制御]」モーダル用の一覧 — デバイスを区画内(plot)、区画まで届く灌水(irrigation)、デバイス種別ごとの最も近いもの(nearest)として分類します。自前のポリゴンを持たない施設ベースの区画には、ベイスコープの派生版が使われます。30秒キャッシュ。 |
| GET | `/api/geo/plot/<plot_uuid>/resource_usage?days=` | 「[現況]」カード用の灌水稼働時間/水量。`days` は1〜30。 |
| GET | `/api/geo/plot/<plot_uuid>/env_series` / `/env_week?days=&end=&stage=&unit=` | 区画自身のタイムゾーン基準の環境推移シリーズ。`stage=<key>` を指定すると `days`/`end` の代わりにそのステージの期間を使います。 |
| GET | `/api/geo/plot/<plot_uuid>/sensors` | この区画が現在参照しているデバイス(保存値ではなく導出値)。 |
| GET | `/api/geo/zone/<zone_uuid>/allocation?on=` | [ゾーン](#zones)の節を参照 — ゾーン視点で見た配下区画の面積配分。 |
| POST | `/api/geo/plots/history` | 「ここに以前何が植えられていたか」— 指定した図形と幾何学的に重なる過去の区画(輪作/連作障害の確認用)。ボディ: `plot_uuid`、`zone_uuid`、生の `geometry` のいずれか、および推測できない場合の `map_uuid`。 |

### ライフサイクルとステージ { #lifecycle-stage }

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/geo/plot` | 作成(`unique_id` なし)または更新(ありの場合 — 部分保存、指定したフィールドのみ変更)。`feature`(GeoJSON)または `facility_uuid`(+`bay_id`)のいずれかが必要で、`map_uuid`/`geo_id` は `facility_uuid` を与えない場合にのみ必要です(施設は自分がどの地図にあるかを既に知っています)。 |
| DELETE | `/api/geo/plot/<plot_uuid>` | **完全**削除 — 誤入力の訂正用。通常の作付け終了は下記の `/end` を使ってください。 |
| POST | `/api/geo/plot/<plot_uuid>/end` | サイクルをソフトに終了します(終了日を設定するだけで削除はしません)。ボディ: `{ended_on, reason: デフォルト 'harvested'}`。 |
| POST | `/api/geo/plot/<plot_uuid>/succeed` | 現在のサイクルを終了し、同じ場所に即座に再定植する処理を1回で行います。ボディ: `{ended_on, reason, subject, started_on, program_uuid?, variety?}` — `program_uuid` を省略すると以前のプログラムを引き継ぎ、明示的に `null` を指定すると解除します(休閑)。 |
| POST | `/api/geo/plot/<plot_uuid>/copy` | 過去のサイクルの幾何情報を再利用して新しい区画を作成します(同じ場所への再定植)。ボディ: `{started_on, subject}`。 |
| POST | `/api/geo/plot/<plot_uuid>/stage` | ステージ遷移を確定します — これが、以降のすべてのステージ計算の基準日となる書き込みです。ボディ: `{stage_key, stage_index, started_on, source, note}`。 |
| DELETE | `/api/geo/plot/<plot_uuid>/stage` | 直近に確定したステージ遷移を取り消します(レコードは残り、取り消し済みとしてマークされます)。 |
| POST | `/api/geo/plot/<plot_uuid>/stage-guidance` | プログラムのガイダンスとは別に、この区画だけのステージ別自由記述ガイダンスを設定します。ボディ: `{stage_key, guidance}`。 |
| POST | `/api/geo/plot/<plot_uuid>/stage-name` | この区画だけでステージ名を変更します。ボディ: `{stage_key, name}`。stage-guidanceと異なり、すでに過ぎたステージの名前も変更できます。 |
| POST | `/api/geo/plot/<plot_uuid>/stage-target` | この区画だけステージの目標値を上書きします。ボディ: `{stage_key, target_key, value}` — `value` を空にするとプログラムの値に戻ります。**表示のためだけの値ではありません** — 制御はプログラムの参照値よりも区画の上書き値を優先して読み取ります。 |
| POST | `/api/geo/plot/<plot_uuid>/stages` | 共有プログラムには触れずに、この区画だけにカスタムステージを追加します。ボディ: `{name, days, after, guidance}`。 |
| DELETE | `/api/geo/plot/<plot_uuid>/stages/<stage_key>` | 区画専用のステージを削除します。すでに経過したステージであれば拒否されます。 |
| POST | `/api/geo/plot/<plot_uuid>/save-as-program` | この区画の現在のステージスケジュールを再利用可能なプログラムとして登録します — 生きたリンクではなくコピーです(この区画自体はこれまで通りのプログラムに従い続けます)。ボディ: `{name, adopt_targets}` — `adopt_targets` は、曖昧さのない範囲でこの区画の実測中央値を新しいプログラムの目標として採用します。 |
| POST | `/api/geo/plot/<plot_uuid>/resources` | 区画の現在のステージに紐づくリソース系ファンクション(灌水など)を手動で作動させます。水を出す操作のため、ステージ遷移や自動承認では**絶対に**自動実行されません。 |

### スケジュール { #schedule }

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/geo/plot/<plot_uuid>/schedule` | ステージの境界を一括で調整します。ボディ: `days`(`{stage_key: 日数}`、期間ベース)または `plan`(`{stage_key: date|null}`、絶対日付ベース)のどちらか一方。 |
| POST | `/api/geo/plot/<plot_uuid>/schedule/shift` | 1つのステージ境界を相対的にずらします。ボディ: `{stage_key, days: ±N}` — 保存時点で絶対日付に変換されるため、後で再度ずらしても以前の「+7日」が意味していた日付自体は変わりません。 |

### ゾーンを区画に分割する { #splitting-a-zone-into-plots }

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/plot/split-preview?zone_id=&parts=\|strip_width_cm=\|widths_cm=&edge_margin_m=&min_length_cm=&orientation=&angle_deg=` | 図形をストリップ/グリッドに分割する案を**何も保存せずに**計算します — 分割は決定的なので(同じ図形+パラメータ ⇒ 同じ結果)、プレビューを別途保存しておく必要がありません。 |
| POST | `/api/geo/plot/split-apply` | ボディ: 同じ分割パラメータに加えて `subject`(必須)、`kind`(デフォルト `vegetation`)、`variety`、`started_on`、`expected_end_on`、`color`、`name`。**クライアントから送られたプレビューのポリゴンは一切信頼せず、同じパラメータでサーバー側が分割を再計算**したうえで、結果の各ストリップごとに区画を1件ずつ作成します。1つでも失敗すれば、決して全体を成功として報告しません: `{ok, created, errors: [{index, message}], message}`。 |

(デバイスマーカー版の分割機能は `POST /api/geo/device/split-apply` で、[デバイスの位置・一覧・詳細](#device-location-lists-detail)の節にあります — 分割結果が何になろうと幾何計算は同じなので、この `split-preview` をそのまま再利用しています。)

---

## 手動スケジュール { #manual-schedule }

デバイスを直接作動させない、軽量なスケジュール項目です(特定の日に作業者が何かをすべき、というメモ) — デバイスを自動で作動させる通常のスケジューラーとは別物です。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/schedule/<target_id>` | 図形/区画/施設の今後の予定(配下の項目を含む)。 |
| POST | `/api/geo/schedule` | ボディ: `{target_id, date, time, content, worker}`。`edit_controllers` が必要 — スケジューラー画面が要求する編集者権限と同じです。それより下の役割は一覧を見るだけで、追加はできません。 |

---

## 出力の制御(地図ポップアップ) { #output-control-map-popups }

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/geo/output/<output_uuid>/state` | デーモン経由で出力をオン/オフします。ボディ: `{state, channel, duration}`。`edit_controllers` + デバイススコープが必要。 |
| POST | `/api/geo/output_states` | ゾーンポップアップ用のバッチ処理によるon/off生状態の取得。ボディ: `{ids: [...]}`。読み取り専用 — ログインのみ必要、追加の権限は不要。 |
| POST | `/api/geo/output_runtimes` | より重いバッチ取得(経過時間、前回の稼働時間、次回の予定)— ポーリング用ではなく、モーダルを開いた時だけ使います。ボディ: `{items: [{id, channel}, ...]}`(最大60件)。 |
| GET | `/api/geo/output/<output_uuid>/history?hours=` | デューティサイクル/オンオフの履歴シリーズ。`hours` は1〜168、デフォルト24。 |
| POST | `/api/geo/function/<kind>/<func_uuid>/activate` | `kind` は `custom`\|`conditional`\|`pid`\|`trigger`\|`function`。ボディ: `{active: bool}`。`edit_controllers` が必要。 |

---

## 筆(地番)のインポート { #parcel-import }

実際の筆(地番)/公園境界を地図の図形として取り込みます。

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/geo/parcel/from_address` | ボディ: `{address}`。VWorld経由で韓国の地籍筆ポリゴンを検索します(APIキーは登録済みの `gis_vworld` レイヤーから解決)。 |
| POST | `/api/geo/parcel/from_csv` | マルチパート `file` — 1列目に住所が入ったCSVを一括で取り込みます。 |
| POST | `/api/geo/parcel/save_as_site` | ボディ: `{feature, name, map_uuid}`(`map_uuid` は必須)。`edit_settings` + 対象の地図に対するスコープが必要。取り込んだ筆を `site` 図形として保存します。同じ筆をジオメトリキー基準で重複してインポートしようとすると `409` で拒否され、あわせてラベル図形も自動作成されます。 |
| GET | `/api/geo/import/gg_parks/preview?sigun_nm=&limit=` | 京畿道の公共公園境界のインポートプレビュー(実際の保存はしません)。 |
| POST | `/api/geo/import/gg_parks` | ボディ: `{map_uuid, sigun_nm, limit, delay_sec}`。`edit_settings` + 対象の地図に対するスコープが必要。プレビューした公園を `site` 図形として保存します。 |

---

## 空撮/ドローン画像オーバーレイ { #aerial-drone-image-overlays }

地図の上に重ねる、地理参照済みのラスター画像(ドローン写真、空撮画像)です。アップロードと保存には `edit_controllers` が必要で、進捗のポーリングはログインのみで行えます。

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/geo/overlay_image/upload` | マルチパート `file` + `layer_id`。`.jpg`、`.jpeg`、`.png`、`.tif`、`.tiff`、`.webp` を60MBまで受け付けます。そのレイヤーに以前の配置がなければEXIF/XMPメタデータから自動で地理参照し、あれば既存の4隅にテクスチャだけを差し替えて、維持した4隅も併せて返します。大きい画像はタイルピラミッドを生成し、その間すぐ表示できる縮小プレビューも作ります。小さい画像は単一画像としてそのまま使います。 |
| POST | `/api/geo/overlay_image/save` | ボディ: `{layer_id, coordinates: [[lng,lat], ...](4隅), opacity}`。4隅の座標が変わった場合はタイル生成を再実行します — アップロード時点で配置がなかった大きい画像は、ここで初めてタイル生成が始まります。 |
| GET | `/api/geo/overlay_image/tile_status/<layer_id>` | タイル生成の進捗をポーリング: `{tile_status, render_mode, tile_eligible, tile_url, minzoom, maxzoom, tile_count, tile_error}`。 |

---

## プロキシサービス { #proxy-services }

ブラウザ側のクライアントが上流サービスのAPIキーを一切見ずに済み、CORS制約も回避できるよう、サーバーがこれらの外部サービスを中継します。すべて `GET` で、ほとんどは上流のレスポンスを短時間キャッシュします(分かる範囲で明記)。

| エンドポイント | 対象 |
|---|---|
| `/api/geo/layer_secrets?ids=` | 登録済みレイヤー最大12件分の、マスクされていないAPIキー/URL(ページに表示される一覧はマスクされ、有効化されているレイヤーだけがここで開示されます)。 |
| `/api/geo/proxy/rainviewer/meta` | RainViewerのレーダーメタデータ(5分キャッシュ)。 |
| `/api/geo/proxy/rainviewer/timestamps` | RainViewerの利用可能なフレームのタイムスタンプ。 |
| `/api/geo/proxy/isric?lon=&lat=&property=&depth=&value=` | ISRIC SoilGridsの土壌データ(5分キャッシュ)。 |
| `/api/geo/proxy/openweather?lat=&lon=&units=&input_id=` | OpenWeatherのオーバーレイ(キーはサーバー側で解決 — `input_id` で指定したレイヤー、なければグローバルの地図キーを使い、クライアントから送られたキーは無視されます)。 |
| `/api/geo/proxy/kma?lat=&lon=&input_id=` | 韓国気象庁APIハブの地上観測データ。 |
| `/api/geo/proxy/openmeteo` | Open-Meteoの予報(上流サービスがダウンしている間はクエリごとに60秒のクールダウンを設けます)。 |
| `/api/geo/proxy/wms/<layer_id>?BBOX=&WIDTH=&HEIGHT=` | WMSの `GetMap` タイルプロキシ。2段キャッシュ(ディスク + ブラウザのETag)、上流が失敗した場合はエラーの代わりに透明な1×1のPNGを返します。 |
| `/api/geo/tile/<layer_id>/<z>/<x>/<y>` | 汎用のキー付きXYZタイルプロキシ(OpenWeatherのタイルオーバーレイなど)。 |
| `/api/geo/proxy/sentinelhub/<layer_id>?z=&x=&y=` | Sentinel HubのProcess APIタイル(OAuth2の認証情報はサーバー側から外に出ません)。 |
| `/api/geo/proxy/sentinelhub/<layer_id>/value?lat=&lon=` | 凡例表示用の、ある地点における指数値(NDVIなど)。15分キャッシュ。 |
| `/api/geo/proxy/agromonitoring/<layer_id>?lat=&lon=` | 登録済みポリゴンの土壌水分/温度/NDVI。30分キャッシュ。 |
| `/api/geo/tile_proxy?url=` | 汎用タイルプロキシ。許可リストは `gibs.earthdata.nasa.gov`、`map.pstatic.net`(Naver)、`daumcdn.net`(Kakao)のみです。 |

---

## 設定 { #settings }

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/settings` | GISのグローバル設定: `saved_state`、`geo_layers`(有効なレイヤーのみ)、`search_inputs`、`search_provider`。設定編集権限が必要です — `saved_state` には地図プロバイダのAPIキーが平文で含まれるため、権限がなければ権限エラーになります。 |
| POST | `/api/geo/settings` | グローバル設定の更新 — 検索プロバイダ、地図ライブラリをローカルで配信するかCDNから取得するか、既定の中心座標とズーム、ズーム/カリングのしきい値、レンダリングのトグル、`theme_*` のキー(色 + ラベル・表示のトグル、パネル背景)。設定編集権限が必要です。書き込みは(1件ずつ)直列化され、更新のロストを防ぎます。 |
| GET | `/api/geo/settings/length_unit` | `{length_unit, supported: ["mm","cm","m","in","ft"]}`。 |
| PUT | `/api/geo/settings/length_unit` | ボディ: `{length_unit}`。TTLを待たずに、キャッシュされているクライアント側の地図設定を即座に無効化します。 |

---

## 地図の並び順 { #map-ordering }

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/map/<map_uuid>/site_order` | 保存済みのサイト一覧の表示順と、サイトごとのゾーンの並び順。ログインのみ必要。 |
| POST | `/api/geo/map/<map_uuid>/site_order` | ボディ: `{order}` および/または `{site_key, zone_order}`。`edit_settings` + 地図スコープが必要。 |

---

## 時刻・太陽 { #time-solar }

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/geo/local_time?lat=&lng=` | 地図ウィジェットの時計ドック用 — 現地のタイムゾーン/時刻、および日の出・日の入りのイベントウィンドウ(昨日から明後日まで)。 |
| GET | `/api/geo/sun_event?target_id=` | 対象が継承している位置に基づく、今日の日の出・日の入り(1日のうちの秒数)。 |

---

## 区画/ゾーン日誌 (`/geo/journal`) { #plotzone-journal-geojournal }

**別のプレフィックスです** — `/api/geo` ではなく `/geo/journal` の下にあります。日誌は、区画・ゾーン・サイトについて、指定した期間のGDD、DLI、日長、灌水量、気象をまとめた生成レポートで、バックグラウンドで1度だけ作成され、以降は保存済みのスナップショットからそのまま配信されます。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/geo/journal/plot_history?area_id=` | 指定した地図エリアを通過した区画/作物の一覧 — 日誌の対象選択に使用します。 |
| GET | `/geo/journal` | 日誌ハブページ(最近の日誌 + 作成フォーム)。このページを開くと、再起動などで中断された生成も回収されます — そうしないとその日誌は永遠に「生成中」のままになります。 |
| POST | `/geo/journal` | ボディ: `{target_type: 'plot'\|'zone'\|'site', target_id, start, end, measurements?, granularity?}`。要求された期間/チャンネル数が高コストになる場合、作業を始める前に拒否します。非同期のバックグラウンド生成を開始します。JSONの呼び出し元には `{ok, unique_id, url}`、それ以外はリダイレクトが返されます。`edit_plots` が必要。 |
| GET | `/geo/journal/<journal_uuid>?format=html\|md\|json\|csv\|odt&granularity=` | **保存済みの**スナップショットを読み取ります — 元データは再計算しません(カーブの差分など、表示専用の値の一部だけは表示時に計算されます)。`granularity` は `day`\|`week`\|`month`\|`stage`\|`all` で、保存された単位より粗くしか表示できません。ステージのある日誌はステージ単位で開き、ない場合は保存単位のまま開きます。生成が完了する前にファイル形式をリクエストすると `409`。`csv` はExcel互換のためUTF-8のBOM付き、`odt` は `application/vnd.oasis.opendocument.text`。 |
| DELETE | `/geo/journal/<journal_uuid>` | 日誌と、それに添付されたノートを削除します。`edit_plots` が必要。 |
| GET | `/geo/journal/target_info?target_type=&target_id=` | 対象について取得可能な最も古いデータの日付、その対象のタイムゾーン基準の今日の日付、利用可能な測定グループ — 作成フォームの事前入力に使用します。ベストエフォートで、失敗しても静かに続行します。 |

---

## その他 { #other }

- `POST /api/tools/kma_lookup` — 小さな独立したユーティリティです(別プレフィックス、`/api/geo/` ではなく `/api/tools/`): 与えられた緯度経度に対する韓国気象庁の格子座標(nx, ny)の最近傍検索。

---

## レスポンスコード

| コード | 意味 |
|------|------|
| 200 | 成功 |
| 201 | 作成成功 |
| 400 | 不正なリクエスト(検証エラー) |
| 401 | 認証が必要 |
| 403 | 権限なし(権限、スコープ、または読み取り専用APIキー) |
| 404 | リソースが見つからない |
| 409 | 競合(例: すでに使用中の割り当てスロット、参照が残っているための削除拒否、筆の重複インポート) |
| 500 | サーバーエラー |
