# AI機能の概要

AoTは、MCP(Model Context Protocol)ベースのAIエージェントを使って、温室や栽培施設の環境を観察・診断・制御します。AIはあくまでアドバイス役に徹し、機器を動かす操作はすべて実行前にユーザーの承認が必要です(設定だけを変更する編集は例外です。詳しくはシーケンスの節を参照してください)。

---

## はじめに: スイッチは2つあります { #enable-and-start }

AIを使うには、別々の場所にある2つのスイッチを入れる必要があります。あえて1つにまとめていません。

| スイッチ | 場所 | オンにすると起きること |
|--------|------|------------------------|
| **AIサービスの有効化** | 設定 > 一般 | AIメニューがナビゲーションに現れ、AIページに入れるようになります。チャットとアドバイス要求が動作します。 |
| **AIサービスの稼働** | AI > AIエージェント | 誰も呼ばなくても動く作業が始まります — 定期サマリー、コンテキストのブロードキャスト、天気サマリー、MCPヘルスチェック、リアルタイムアラート。 |

順序は **設定で有効化 → AIページでモデル(エージェント)を登録 → 稼働を開始** です。

- **モデルを1つも登録していないと稼働を開始できません。** 尋ねる相手がいないままバックグラウンド処理だけが回ると、サイクルのたびにログにエラーが積み重なるだけです。このスイッチは、少なくとも1つのエージェントが有効化されている場合にのみ使えるようになります。
- **最後のモデルを無効化または削除すると、稼働も止まります。** 後でモデルを再度有効化しても、自律稼働は黙って再開しません — AIページであらためて開始してください。
- **稼働をオフにしていてもチャットとアドバイス要求は動作します。** そのおかげで、自律稼働にコミットする前に、登録したばかりのモデルを試すことができます。

---

## AIシステムのアーキテクチャ { #agents }

AoTのAIは、2つの経路でツールを使用します。

- **アプリ内AIアシスタント** — ダッシュボードのチャットアシスタントです。単一のエージェントループがツールカタログ全体を把握し、自らツールを選択・実行します。状態を変更する操作(デバイス制御、エンティティの作成・編集・削除など)は、チャットの**承認カード**でユーザーが確認したあとにのみ実行されます。
- **外部MCPサーバー** — `aot/aot_mcp_server.py`(標準MCPプロトコル、stdio/HTTP)。Claude Desktopなどの外部MCPクライアントがAoTのツールを直接呼び出せるように公開します。

```
ユーザーチャット ─────────┐            外部MCPクライアント(Claude Desktopなど)
                         ↓                          ↓
            アプリ内エージェントループ       aot_mcp_server.py (stdio/HTTP)
                         └──────────┬───────────────┘
                                    ↓
                    ツールレジストリ (tool_registry.py, 単一のソース)
                                    ↓
                       AoTシステム (Daemon / InfluxDB / SQLite)
```

どちらの経路も同じレジストリ(`aot/ai/services/tool_registry.py`)からツールを取得するため、両者のツール一覧がずれることはありません。

---

## MCPツール一覧

外部MCPサーバーと内部の`mcp_aot`エンジンが公開するツールです。読み取り系ツールと設定編集系ツールは即座に実行されます。制御・スケジューリング・有効化系ツールは、どちらの経路でも承認ゲートを通ります — アプリ内アシスタントのチャット承認カード、または外部MCPサーバーの承認キュー(`pending_approval` + `respond_to_confirmation`。詳しくは後述の「MCPサーバーの実行」を参照)です。

### 観察(読み取り — 即時)

| ツール | 説明 |
|------|-------------|
| `get_spatial_tree` | 空間階層(サイト > ゾーン > デバイス)のツリー |
| `resolve_target` | 場所やデバイスの名前を正確なエンティティへ解決 — コンテナ(子を持つか)かどうかを事前に確認 |
| `get_device_list` | 登録済みの全デバイス(入力・出力・カメラ)の一覧 |
| `search_devices` | 名前や種類のキーワードでデバイスを検索 |
| `get_sensor_detail` | センサーの時系列履歴(最小・最大・平均の統計) |
| `get_weather` | 圃場・ゾーンの現在の天気(気温、湿度、風、降水) |
| `get_energy_report` | 期間・ゾーン別のエネルギー使用量レポート |
| `get_cumulative_status` | EnvCoordinatorのDLI / GDD累積状況 |
| `search_notes` | ゾーンやデバイスのノート・メモ・作業記録を読み取る |
| `get_note_attachment` | ノートに添付された写真を実画像として表示(1回の呼び出しにつき1枚) |
| `list_notices` | 掲示板の投稿一覧 |
| `get_system_update_status` | インストール済みバージョンと最新のGitHubリリースの比較 |
| `list_available_devices` | AI判断に使えるデバイス(ネイティブブリッジ) |
| `get_sensor_reading` | 特定センサーの最新の測定値(ネイティブブリッジ) |

### 記録 / タスク

| ツール | 説明 | 承認 |
|------|-------------|----------|
| `create_note` | 日付のないメモ・ノートをエンティティに作成し、即座に保存 | 不要 |
| `add_schedule` | 人が行う作業タスク(除草、点検、清掃)を登録 | 必要 |
| `add_schedule_batch` | 複数の対象(ゾーンごとなど)へのスケジュールを1回の承認でまとめて登録 | 必要 |

### 制御(ユーザー承認が必要)

| ツール | 説明 |
|------|-------------|
| `operate_device` | バルブ・ポンプ・照明の即時物理制御 |
| `set_output_state` | 出力のオン・オフ切り替え(継続時間の指定は任意、ネイティブブリッジ) |
| `schedule_device_control` | 特定の時刻に1回限りのデバイス操作を予約 |

> アプリ内アシスタントでは、上記の制御ツールと`add_schedule`は、承認カードでの確認を経てはじめて実行されます。外部MCPサーバーから直接呼び出す場合も同種のゲートを通ります — 最初の呼び出しは実行されず、`confirmation_id`付きの`pending_approval`として返ってきます。ユーザーがチャット(`respond_to_confirmation`で処理)またはWebレビュー画面でそのconfirmation_idを明示的に承認または却下したのち、呼び出し側が同じ引数に`_confirmation_id`を加えて再試行してはじめて実際に実行されます。全体の流れは後述の「MCPサーバーの実行」を参照してください。

### シーケンス(設定編集には承認不要)

[シーケンス](../Functions.md#trigger-sequence)は複数の出力を決まった順序で動かします — かんがいでよくある形で、バルブが順番に切り替わり、ポンプが運転全体にまたがって動きます。以下のツールはシーケンスを読み取り、組み立てます。

| ツール | 説明 |
|------|-------------|
| `configure_sequence_day` | ある曜日の実行計画全体を1回の呼び出しで設定 — どのデバイスを、どの順序で、どれだけの時間、どれをまとめて動かすか |
| `modify_sequence_step` | 1ステップのグループ・所要時間・単独/合計モード・合計ステップの先行/遅延マージン・実行順序・有効状態・ラベルを、全曜日一括または特定の曜日だけに設定 |
| `modify_sequence_schedule` | 1日の実行時間帯、サイクル周期、シーケンスを実行する曜日 |

> **シーケンスの設定編集は、承認なしで即座に反映されます。** 上記の3つの
> ツールに加えて`create_sequence_function`と`modify_function_options`も、
> 設定を変更するだけで、機器を動かすことはありません。編集が現場で効果を持つのは
> `activate_function`を経たあとだけで、有効化そのものは引き続き承認の対象です。
> 受け入れているトレードオフはこうです — *すでに有効な*シーケンスのスケジュールを
> 編集すると、承認なしで次回実行が変わります(2026-08-07に決定)。

`get_function_detail`はシーケンスのステップに加えて`weekly_plan`(各曜日に実際に何が、実時刻でいつ動くか)を返します。変更を確認するときは、リクエストを繰り返すのではなく、これを読み返してください。

使う前に知っておくとよいことが2つあります。

- **同じスロットに並んだデバイスは同時に動きます**。スロットは1つの所要時間を共有します。「この2つのバルブを40分間一緒に開ける」はこうやって表現します。
- **曜日ごとに、どのステップを動かすか・そのグループ・所要時間を上書きできます。** そのため、たとえば木曜の夕方の運転と金曜の明け方の運転を1つのシーケンスでまかなえます。曜日が違うというだけの理由で2本目のシーケンスを作る必要はありません。

`modify_function_options`はシーケンス(や他のトリガー)には効きません — それらの設定は`custom_options`ではなくデータベースの列だからです。呼び出すと、上記のツールを使うよう案内して拒否されます。

### 呼び出し状態(`call_state`) { #call-state }

`tools/call`のすべてのレスポンスには`call_state`が含まれます。各ツール固有の
`status`の語彙(`modified`、`created`、`deleted`、`configured`、`success`など)を
知らなくても、**その呼び出しが実際に実行されたかどうか**をこれで判断できます。

| 値 | 意味 | クライアント側の対応 |
|------|------|------|
| `executed` | この呼び出しで実行済み(読み取りツールも含む) | 結果を報告する |
| `already_executed` | ユーザーが承認した時点でサーバーが既に実行済み | 同梱の`result`を報告する。再度呼び出さない |
| `pending_approval` | 未実行、人の承認待ち | ユーザーを承認ページに案内して待つ |
| `approval_rejected` | ユーザーが却下した | 実行しない。アドバイスに切り替える |
| `approval_expired` | 承認の有効期限が切れた | あらためて承認を求める |
| `refused` | 別の理由で拒否された(レート制限、引数の不一致など) | `reason_code`を読んで説明する |
| `failed` | ツールがエラーで終了した | エラーを報告する |

既存の`status`の値は変わりません — コードや稼働中の設定は既にそれで分岐しているため、これは軸を再定義するのではなく新たに1本追加するものです。

### 拡張アプリ内アシスタントツール

上記のMCPカタログに加え、アプリ内AIアシスタントはエンティティの組み立て・自動化・知識のための追加ツールを使います。状態を変更するツールはすべて承認が必要です。

- **入力/出力の管理**: `list_device_types`、`get_device_type_options`、`create_input`・`modify_input`・`delete_input`、`create_output`・`modify_output`・`delete_output`、`get_device_measurements`
- **Function(自動化)**: `get_function_list`、`get_function_detail`、`create_function`、`create_sequence_function`、`modify_function_options`(トリガーには使えません — 上記のシーケンスの節を参照)、`activate_function`・`deactivate_function`・`delete_function`、加えてシーケンス用ツール`configure_sequence_day`・`modify_sequence_step`・`modify_sequence_schedule`
- **スケジュール台帳**: `search_schedule`、`edit_schedule`、`delete_schedule`
- **地図(GIS)**: `list_geo_maps`、`get_device_location`、`set_device_location`、`delete_geo_shape`、`list_unbound_slots`(デバイスのない場所を確認)、`rebind_device`(1台のデバイスが占める地図上の全スロットを別のデバイスへ移す)
- **GIS入力(地図レイヤー)**: `list_gis_inputs`、`create_gis_input`・`modify_gis_input`・`delete_gis_input`、`activate_gis_input`(VWorld/Google/OpenWeatherなどの地図レイヤー提供元を管理)
- **施設/設備の照会**: `get_facility_capacity`(施設の冷暖房能力・容積・換気・かんがい設計の要約)、`get_map_equipment`(地図に描かれた設備のサイト/ゾーン別かんがい設計要約。スプリンクラーと点滴かんがいは分けて集計)、`get_map_equipment_detail`(個々のスプリンクラーの位置・間隔・散水半径、配管ごとの詳細 — 要約で足りないときだけ)
- **掲示板**: `create_notice`・`modify_notice`・`delete_notice`
- **AIエージェント管理**: `list_ai_agents`、`list_ai_entries`、`create_ai_agent`・`modify_ai_agent`・`delete_ai_agent`
- **知識ライブラリ**: `knowledge_search`、`knowledge_shelve`、`list_library_source_types`、`smartfarmkorea_lookup`、`configure_library_source`
- **診断/その他**: `analyze_system_failure`、`get_local_time`、`get_tool_detail`、`read_manual`、`get_detailed_manifest`、`ask_user`

> ツールの単一の正本は`aot/ai/services/tool_registry.py`です。ツールが追加・変更されたときは、このページではなくそのファイルが正となります。

---

## デバイスごとのAI対象トグル { #device-ai-toggle }

`設定 -> 入力` / `設定 -> 出力`の各デバイス設定モーダルには、**AI判断に含める**トグルがあります。

- オン(既定): その入力/出力はAI判断・制御ツール(空間ツリー、デバイス照会、センサー/制御ツールなど)から見えます。
- オフ: そのデバイスはこれらのツールの照会や制御対象から除外されます。機密性の高いデバイスや、AIに絶対に触らせたくないデバイスをデバイス単位で隠すのに使います。

新規に作成した入力・出力は、この設定がデフォルトで有効になっています(`is_ai_enabled=True`)。

---

## 安全性と承認のモデル { #safety-approval-model }

状態を変えない**読み取りツール**は即座に実行されます。**状態を変更するツール**は、どちらの経路から呼ばれても承認ゲートを通ります。

- **承認が必要(変更・物理制御)**: デバイス制御(`operate_device`、`set_output_state`、`schedule_device_control`)、入力/出力/Function/掲示板/AIエージェント/GIS入力の作成・編集・削除、地図の配置変更(`set_device_location`、`delete_geo_shape`)、デバイスの置き換え(`rebind_device`)、`add_schedule`・`add_schedule_batch`、`configure_library_source`など。
- **承認不要(低リスクな書き込み)**: `create_note`、`knowledge_shelve` — 取り消し可能な個人メモ・未確認知識で、即座に保存され、確認されるまでは正としては扱われません。

承認が必要な操作は即座には適用されません。**アプリ内アシスタント**では、チャット上に**承認カード**として提示され、ユーザーが承認してはじめて実行されます。**外部MCPサーバー**経由では、`pending_approval`レスポンス(キューに入ったconfirmation_id)として返り、ユーザーがそのidを明示的に承認または却下してはじめて先に進みます — どちらの経路でも、ユーザーが却下すれば何も変わりません。

Webレビュー画面(`AI → MCPサーバー → AIリクエストとアドバイス`)で承認すると、**その場で即座に実行されます。** 以前は、承認しても許可証が出るだけでした — 人がAIのところへ戻って伝え、AIがもう一度呼び出す必要があり、チャットモデルは話しかけられたときにしか動かないため、この往復をAI自身では完結できませんでした。現在はサーバーが、確認と一緒に保存された引数をそのまま使って実行するため、承認画面に表示された内容と実際に実行される内容がずれることはありません。AIが後で同じconfirmation_idで再度呼び出しても、二度目の実行にはならず、その保存済みの結果が返るだけです。取り消せない物理制御(バルブ、ポンプ)だけは、承認画面でもう一段階の確認を求めます。

---

## 知識ライブラリ

`AI -> ライブラリ`ページ(`/ai/library`)は、AIの回答の根拠となる**コンテキストソース**を登録する場所です。ソースには、文書(PDF/テキスト)、WebのURL、REST API、内部クエリを指定できます。

### 知識はどこから来るか

ライブラリには4種類のものが存在し、AIはそれぞれを異なる形で引用します。

| 出どころ | 何であるか | AIの引用の仕方 |
|---|---|---|
| 権威(Authoritative) | 同期される公共データフィード(例: RDA、Nongsaro) | ソース名を添えて事実として述べる |
| 人が入力したもの | あなたが入力した、またはアップロードした文書 | 信頼できる — あなた自身がソース |
| データから導いたもの | このシステム自身の測定値から算出したもの | 一般則としてではなく、ここでの観察として提示する |
| AIが整理したもの | AIが調べた、または導き出して保存したもの | 人が確認するまで**未確認のノートとして明示** |

AIは自らライブラリに書き込むこともできます。何かを調べたときは要約を保存し、
次の質問がゼロから始まらないようにします。こうしたノートは常に未確認の状態で
入り、常にそうと明示されます — モデルが書き忘れても、サーバー側がその明示を
付け足します。

### AIが書いたものを確認する

**AIが整理した知識の確認**セクションには、AI自身のノートが並びます。ソースの
リンクを開いて原文を確認し、確認・編集・取り下げのいずれかを行います。確認する
ことがそのノートを「未確認」から引き上げる唯一の方法です。ソースリンクのない
ノートは実質的に確認できないため、リンクを出さず、未確認のままになります。

**確認済みの知識のみ**(既定はオフ)は、AI自身の未確認ノートをAIが引用しない
ようにします。権威ある知識と手入力の知識は影響を受けません。

### 閲覧と追加

**知識項目**セクションには、AIが引用できるものすべてが並びます — 検索し、
タグや出どころで絞り込み、古くなったものは取り置きます(取り置いても行は
残ります。AIの手が届かなくなるだけです)。

**知識を追加**は、AIのやり取りやソース登録を経ずに、あなたが既に知っていることを
書き込みます。ここに書いた内容は確認済みとして扱われます — あなたが出典です。

### 知識ダイジェスト・パイプライン

文書やWebのURLのような長い文章のソースは、登録時に**一度だけ**前処理されます。

1. ソースを**チャンク**に分割します。
2. 各チャンクを**ダイジェスト化(LLMによる要約 + キーワード抽出)**し、`ai_knowledge_chunk`テーブルにキャッシュします。
3. クエリ時には**LLM呼び出しは発生しません** — 検索は純粋なDB照会と決定的な検索だけなので、回答は速く、コストもかかりません。

### 範囲はサイトではなくタグで決まる

!!! warning "ここが変わりました — ライブラリは農場全体で共有です"
    かつて知識は`facility_id`で絞り込まれており、このページの旧版には、あるサイト
    向けに登録した文書は別のサイトには決して出てこないと書かれていました。**それは
    もう正しくありません。** ライブラリはフラットな、農場全体で共有するカタログです
    — どの項目もどの質問に対しても検索対象になり得て、関連性はタグとキーワード
    スコアリングで決まります。

    ライブラリを機密性の境界として扱わないでください。このAIを使う全員に見せたく
    ないものは、ライブラリに入れないでください。

範囲は代わりに**タグ**で決まります — 自由記述のテキスト(「大根」「北棟」
「橋A」など)で、実際に自分が管理している単位を使えます。AoTは農業専用では
ないため、決まった語彙はありません。タグこそが、クエリを正しい主題へ絞り込む
手段です。

### 地域を選ばない組み込みソース { #global-sources }

組み込みソースのほとんどは韓国の公共データ(RDA、Nongsaro、NCPMS、
SmartFarmKorea)で、その提供元のAPIキーが必要です。それ以外の地域でも、
2つの組み込みソースは**どこでもキーなしで**そのまま使えます。

| ソース | 何に答えるか |
|---|---|
| FAO ECOCROP(EXT-GL-01) | 2,500種以上の生育温度、降水量、土壌pH、標高の限界 |
| Open-Meteo(EXT-GL-02) | 世界的な予報、深さ別の地温/土壌水分、基準蒸発散量(ET₀)、過去の気候 |

Open-MeteoはAoT自身の天気ツールが届かない隙間を埋めます。`get_weather`は
この設置に配線された天気センサーしか読めず、`get_weather_forecast`は韓国限定
(気象庁)です。センサーがない場合や韓国の外では、これが唯一の天気の根拠に
なります — そして土壌の値とET₀は、どんなセンサーを持っていてもここから
供給されます。

それ以外は、ライブラリは逆方向に埋まっていきます — あなた自身の文書、
Webページ、REST API、そしてAIが作業中に調べて棚に上げたもの。

### データの出典表示 { #data-credits }

2つのグローバル組み込みソースはどちらも**CC BY 4.0**のデータです。このライセンス
は、データを表示する場所に出典表示を添えることを求めているため、AoTは2か所で
それを行います。

- **AIライブラリページ** — ソース一覧の下に「データ出典」の行があり、
  有効化しているソースを網羅します。
- **AIの回答** — クエリの応答には出典表示のテキストが含まれるため、AIが
  その値を引用する際に含めます。

| ソース | ライセンス | 出典表示 |
|---|---|---|
| Open-Meteo | CC BY 4.0(無料枠は非商用限定) | Weather data by [Open-Meteo.com](https://open-meteo.com/) |
| FAO ECOCROP | CC BY 4.0 | FAO ECOCROP |

!!! warning "商用利用について"
    Open-Meteoの無料エンドポイントは、その利用規約により**非商用利用に限定**
    されています(サブスクリプションや広告のあるサービス、商用製品への組み込みは
    商用とみなされます)。商用の生産者・サービスは
    [Open-Meteo APIキー](https://open-meteo.com/en/pricing)を取得し、ソース設定に
    入力してください — キーがあれば、AoTは商用エンドポイントを問い合わせます。

出典表示のテキストは、ソース設定(歯車アイコン)の**出典表示**欄で上書きできます。
空欄のままなら、組み込みの既定文が使われます。

---

## MCPサーバーの実行

外部MCPクライアント向けの標準MCPサーバーです。アプリの起動時に自動でウォームスタートされ、手動で実行することもできます。

```bash
# stdioモード(既定) — 同じマシン上のローカルクライアント
python3 /opt/AoT/aot/aot_mcp_server.py

# HTTPモード — リモートクライアント(既定ポート5700)
python3 /opt/AoT/aot/aot_mcp_server.py --http --port 5700
```

HTTPモードは、2つの経路を同時に提供します。

| パス | 内容 | 利用者 |
|------|------|------|
| `POST /mcp` | **MCP Streamable HTTP**(標準トランスポート) | Claude Desktop/Code、Cursor、あらゆるMCPクライアント |
| `GET /mcp/info`、`GET /mcp/tools/list`、`POST /mcp/tools/call` | 独自REST | ChatGPT Custom GPT(OpenAPI Actions)、curlでの確認 |

標準クライアントに必要なのはURLとAPIキーだけです — 中継スクリプトは不要です。

```bash
claude mcp add --transport http aot https://<host>/aotmcp/mcp \
  --header "X-API-KEY: <base64 api key>"
```

`GET /mcp`は405を返します。このサーバーはサーバーからクライアントへのSSEストリームを提供していません。waitressを4スレッドで動かしているため、1本の保持接続がツール呼び出しを飢餓状態にしてしまうからです。仕様上はこれも許されており、将来サーバー起動の通知を送る先になる予定です。

REST APIを残しているのは、通常プランのChatGPT Custom GPTがMCPサーバーを登録できないためです — OpenAPI Actions経由でしか接続できません。

### ChatGPT Custom GPTを接続する { #chatgpt-setup }

上記の3つのRESTパス(`/mcp/info`、`/mcp/tools/list`、`/mcp/tools/call`)を
**OpenAPI Action**として登録します。ActionsつきのCustom GPTを作成するには
有料のChatGPTプラン(Plus/Team/Enterprise/Pro)が必要です — 無料アカウントは
この経路をまったく使えません。

1. **APIキーを発行する** — `設定 > ユーザー`で、自分のアカウント用に新しいAPI
   キーを生成します(「ChatGPT」のような名前にしておくと、あとでこの接続だけを
   取り消せます)。このGPTが読み取り専用でよいなら、発行時にスコープ
   `readonly`を選んでください — 書き込み系ツール呼び出しはサーバー側で拒否
   されるため、Custom GPTの設定ミスでデバイスに誤って触れることがなくなります。
   複数人が使うなら、1人に1つずつキーを発行してください — 監査ログで誰が何を
   呼び出したかがわかり、漏えいしたキーも他の全員を止めずに失効できます。
2. **HTTPモードが有効で到達可能なことを確認する** — サーバーは
   `--http --port 5700`で稼働している必要があり、ChatGPTがそのポート(または
   リバースプロキシが公開しているパス)に到達できる必要があります。まず認証なしで
   確認してください(バージョンとツール数だけを返し、キーは不要です)。
   ```bash
   curl https://<host>:5700/mcp/info
   ```
3. **GPTを作成する**: ChatGPTで**Explore GPTs → Create → Configure**に進みます。
   名前と説明を入力し、**Instructions**には少なくとも以下を貼り付けてください —
   そのまま使うか、自分のサイトに合わせて調整します。

   ```
   You are an assistant for this AoT system: you observe status, advise, and
   can register device-control requests when asked.

   - Don't call listTools out of habit. The full tool catalog is a large
     response that eats into the conversation budget. Call it once early to
     learn tool names and arguments, then call only the tools you need.
   - Prefer narrow tools. For a single device or zone, use a tool that
     targets just that instead of a broad summary tool.
   - When calling callTool, always JSON-encode `arguments` into a string.
     E.g. not {"zone_name": "North Field"} but
     "{\"zone_name\": \"North Field\"}". Empty is "{}".
   - Every tool response carries call_state. Judge success/failure from that
     field alone — each tool's own `status` field uses different words:
       executed / already_executed → done, relay the result
       pending_approval            → not yet run, tell the user to approve it
       approval_rejected           → rejected, don't retry — offer advice instead
       approval_expired            → approval window expired, ask again
       refused / failed            → refused or errored, relay the reason
   - If a state-changing request comes back pending_approval, don't retry it
     yourself — tell the user to approve it on the web approval screen.
   - Answer in plain language, without jargon.
   ```

4. **Actionを追加する**: 同じ画面の下のほう、**Actions → Create new action**
   で、以下のスキーマを貼り付けます(`<host>`を実際のアドレスに置き換えて
   ください)。

   ```yaml
   openapi: 3.1.0
   info:
     title: AoT MCP
     version: "1.0.0"
   servers:
     - url: https://<host>:5700
   paths:
     /mcp/tools/list:
       get:
         operationId: listTools
         summary: List available tools and each tool's argument schema.
         responses:
           "200": { description: OK }
     /mcp/tools/call:
       post:
         operationId: callTool
         summary: Call one tool by name with arguments.
         requestBody:
           required: true
           content:
             application/json:
               schema:
                 type: object
                 required: [name]
                 properties:
                   name:
                     type: string
                     description: A tool name returned by listTools
                   arguments:
                     type: string
                     description: >-
                       Tool arguments serialized as a JSON object string.
                       E.g. "{\"zone_name\": \"North Field\"}". Empty is "{}".
         responses:
           "200": { description: OK }
   ```

5. **認証を設定する**: Authentication → API Key → Auth Type `Custom` →
   Header name `X-API-KEY` → 値は手順1のAPIキー(base64)です。
6. **⚠️ `arguments`は文字列として宣言してください — オブジェクトにしては
   いけません。** ツールは100種類を超えるため、その引数の形をすべて1つの
   OpenAPIスキーマに宣言することはできません。`arguments`を自由形式の
   オブジェクトのままにしておくと、ChatGPT Actionsは埋められないフィールドを
   黙って落としてしまいます(実際に起きた事例、2026-08-09: `list_devices_in_area`
   呼び出しには`area_name`が必須でしたが、リクエスト本文には`arguments`キー自体が
   まったく入っていませんでした)。上記のように文字列として宣言しておけば、
   これはすでに回避できます — 手順3のInstructionsも同じ理由から同じルールを
   念押ししています。
7. **保存して確認する**: 共有するつもりがない限り、可視性は**Only me**の
   ままにしておきます。チャットで「状況を教えて」のように尋ねてみて、
   ツール呼び出しと応答が返ってくれば接続成功です。
8. **この経路でも、状態を変更するツールは即座には実行されません。** 最初の
   呼び出しは`confirmation_id`付きの`pending_approval`として返り、ChatGPTは
   それをユーザーに提示し、ユーザーがWeb承認画面で承認したのち、同じ呼び出しに
   `_confirmation_id`を加えて再試行してはじめて実際に実行されます。Custom GPT
   の中で自動的に再承認される仕組みはありません。承認一覧を表示する画面は2つ
   あります — ふだんはスケジューラーページ(`/scheduler`、上部の「保留中の制御
   リクエスト」ブロック)で十分です。監査ログとアドバイス履歴も併せて見たい
   ときのために専用ページ(`/api/v1/mcp/review_page`、メニュー: **AI → MCP
   サーバー → AIリクエストとアドバイス**)もありますが、承認一覧自体はどちらも
   同じものです。

**接続できないとき**

| 症状 | 確認すること |
|---|---|
| 「unauthorized」/ APIキーエラー | 手順5で貼り付けたキーの前後に余分な空白がないか、キーが失効していないか |
| Actionが保存できない | 手順4のスキーマを丸ごと貼り付けたか — 波かっこが途中で切れていると保存に失敗します |
| 「そのツールが見つかりません」と言い続ける | GPTが先にlistToolsを呼んでいません — 「まずツール一覧を確認して」と促してください |
| 読み取りはできるが何も制御できない | 想定どおりです — 書き込みは常に人による承認を経ます(手順8) |
| 名前をもとにした質問に妙な答えが返る | `get_system_update_status`でバージョンを確認してください — 下記の注記を参照 |

> このページで扱っている地図関連のバグ修正(`get_weather`の名前検索が常に
> 同じ間違ったシェイプに当たる、`get_spatial_tree`のフィルターが効かない、
> ゾーンが階層クエリから消える)は、**AoTアプリv26.08.8以降**に含まれています。
> 接続した直後に一度`get_system_update_status`ツールを呼び、インストール済み
> バージョンを確認してください — 古いインストールでは、圃場/ゾーン名で尋ねた
> 質問が古い誤った答えを返すことがあります。

### Claude Desktopを接続する

`claude_desktop_config.json`に追加します。

```json
{
  "mcpServers": {
    "aot": {
      "command": "python3",
      "args": ["/opt/AoT/aot/aot_mcp_server.py"]
    }
  }
}
```

> ここでも、状態を変更するツール呼び出しは即座には実行されません(`aot/ai/services/mcp_safety_gate.py`)。最初の呼び出しは`confirmation_id`付きの`pending_approval`として返り、ユーザーは同じ会話の中、またはスケジューラーページ(`/scheduler`。監査ログも見るなら`/api/v1/mcp/review_page`)上で明示的に承認または却下する必要があり、これは`respond_to_confirmation`を通じて処理されます。承認しただけでは何も実行されません — そのあと`_confirmation_id`を加えて同じ呼び出しを再試行してください。呼び出し元のAIには、この承認を自分で決めたり偽装したりする手段がありません。`AOT_MCP_WRITE_ENABLED=0`を設定すると、書き込み系ツールを一律拒否します(アドバイス専用モード)。締め切りは2段階あります — 既定で人が承認するまで15分(`AOT_MCP_CONFIRM_TTL_SEC`)、承認された瞬間からあらためて5分で実行(`AOT_MCP_APPROVED_TTL_SEC`)です。制御ツールを引き続き公開しているため、このサーバーは信頼できるクライアントにのみ接続してください。

---

## 関連ページ

- [環境制御自動化](env-control.md)
- [スケジューラー](scheduler.md)
- 完全なAIガイド
