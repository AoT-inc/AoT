# AoT 時刻処理リファレンス

この文書は、AoTシステムが**時刻とタイムゾーン(timezone)をどのように扱っているか**を
説明します。設計の背景・意思決定はリポジトリの`docs/design/timezone-management.md`
(開発用、マニュアル未公開)にあり、この文書は「実際にどう動作し、開発者は何を使えば
よいか」を扱います。

---

## 1. 一目で分かる — 核心となる3原則

1. **保存は常にUTC。** DB・InfluxDB・ログのすべての時刻はUTC基準です。
2. **表示は場面に合った時計で。** デバイスの予約は*デバイスのローカル時刻*、個人向け通知は
   *閲覧者本人の時刻*で表示します。
3. **解釈の入口は1つだけ。** タイムゾーンに関する計算は`aot/utils/timekit.py`の1か所に
   集約されています。

---

## 2. 時刻には2種類ある

性質の異なる2つの時刻を区別することが、すべての出発点です。

| | A. 絶対時刻 (Instant) | B. 壁時計の意図 (Wall-clock intent) |
|---|---|---|
| 例 | センサー値、ログ、`created_at`、「バルブが開いた瞬間」 | 「6時に灌水」「毎日早朝に予約」 |
| 性質 | タイムライン上の一点 | 人が特定の時計で語った時刻 |
| 保存 | UTC1つで十分・明確 | UTCへそのまま畳めない — **どの時計の6時か**(アンカー)が必要 |
| 表示 | 目的のtzへ変換するだけ | アンカーtzに戻さないと意図が失われる |

> **なぜ重要か:** 「+6地域のデバイスの6時に灌水」とは、その畑が朝6時であるときに水を
> やることであって、+9のオフィスの6時ではありません。壁時計の意図は、必ず**どこの時計
> なのか**を一緒に把握しなければなりません。

---

## 3. タイムゾーンの4階層 + ホスト時計

システムに関わるタイムゾーンの出所は4つあります。この4つは互いに異なる場合があります。

| 階層 | 何か | どこに保存されるか |
|---|---|---|
| **デバイスtz** | 各デバイス(入力/出力/機能/PID…)の所在地のタイムゾーン | `input.timezone` など(座標・継承から算出してキャッシュ) |
| **図形tz** | 地図上の図形(サイト/ゾーン/施設)のタイムゾーン — tzの**権威** | `geo_shape.timezone`、`geo_facility.timezone` |
| **ユーザーtz** | 個人の表示上の好み | `users.timezone`(未設定時はシステムへフォールバック) |
| **システムtz** | 農場全体の既定値(最後のフォールバック) | `misc.timezone` |

そしてこれとは別に、**ホストOSの時計**があります。

- **ホストOSの時計 = 「今」の唯一の供給源。tzではありません。**
  Dockerコンテナは常にUTCとして扱われ、OS側のローカルtzには依存しません。
  その役割は、`timekit.utc_now()`によって**現在のUTC時刻**を提供することだけです。
  スケジューラの発火は`fire_utc <= utc_now()`の比較だけで行われ、ここにtzは関与しません。
- **`misc.timezone`(システムtz)は「農場の既定値」という最後のフォールバックにすぎず、
  意図を解釈するものではありません。** デバイス・図形が位置情報を持っていれば、決して
  システムtzには落ちません。実際にシステムtzが使われた場合は、その事実が記録・ラベル
  付けされます。

---

## 4. 保存の規約 — naiveなdatetimeが混在していても安全な理由

- **新規コードはtz-awareなUTC**(`timekit.utc_now()` = `datetime.now(timezone.utc)`)を
  使います。
- **レガシーコードにはnaiveな`datetime.utcnow()`が数多く残っています。** これはバグ
  ではありません — プロジェクトの規約として**naiveなdatetimeはUTCとみなす**ことに
  なっており、`timekit.ensure_utc()`が読み取る時点で`+00:00`を付与して正規化するから
  です。
- **SQLiteのカラムを往復させても安全**です。aware なUTC(`00:00+00:00`)をnaiveな
  `DateTime`カラムに保存すると、SQLite/SQLAlchemyはtzinfoだけを取り除き、値(UTCの
  00:00)は保持されます。読み出すとnaiveな`00:00`になり、`ensure_utc`が再び
  `00:00+00:00`に復元します。**SQLのフィルタ**(`schedule_time >= utc_now()`)も、
  バインド時にtzが取り除かれてnaive-UTC同士の比較になるため正確です。

> **落とし穴:** naiveとして保存されるカラムには**必ずUTC-aware(またはUTC相当のnaive)
> の値だけ**を入れなければなりません。もし`Asia/Seoul`-awareな値をそのまま入れると、
> tzinfoが取り除かれ、ソウルの壁時計がUTCと誤認されて9時間ずれてしまいます。そのため
> 保存前には必ずUTCへ変換します(`wall_to_utc`、`utc_now`はすでにUTCです)。

---

## 5. 単一の解決役 — `aot/utils/timekit.py`

タイムゾーンに関するものはすべてこのモジュールに集約されています。以前は各所に散らばって
いたゲート(`get_device_tz`・`get_user_tz`・`get_timezone_name`・`resolve_location_tz`など)
は、今ではこのモジュールに委譲しています。

| 関数 | 用途 |
|---|---|
| `utc_now()` / `now_utc()` | tz-awareな現在のUTC「今」 |
| `ensure_utc(dt)` | naive→UTCとみなし、aware→UTCへ変換(正規化) |
| `to_tz(dt, tz)` | UTC(またはnaive=UTC)→対象のtzへ |
| `iso_utc(dt)` | API直列化の標準 — 常に`+00:00`のISO文字列 |
| `resolve_tz(entity=None, *, user=None) → (tzinfo, source)` | **単一の解決チェーン**(下記) |
| `system_tz()` / `system_tz_name()` | 農場全体の既定tz(Misc) |
| `current_user_tz()` | リクエストしたユーザー個人のtz(なければシステム)。個人向け表示専用 |
| `wall_to_utc(wall, tz)` | 壁時計 + アンカーtz → UTC-aware(予約の保存、DSTも正確) |
| `utc_to_wall(dt, tz)` | UTC → アンカーtzの壁時計(予約の表示) |

### `resolve_tz`の優先順位チェーン

```
entity が図形(GeoShape/GeoFacility):
    自身の継承対応の解決ロジックを使用(保存値 → 親 → facility → centroid)
entity がデバイスの行:
    1. entity.timezone(物質化されたキャッシュ)      → キャッシュのtz_source
    2. 所属図形からの継承(device_id→図形→親チェーン)  → inherited
    3. entityの座標 → timezonefinder                  → coords
    4. システム(Misc.timezone)                        → system
user:
    User.timezone → システム
entity=None:
    システム → UTC
```

> **読み取りはO(1):** デバイスの`timezone`カラムは**物質化されたキャッシュ**です。
> 座標→タイムゾーン変換(`timezonefinder`)は重い処理ですが、これは図形・デバイスが
> **作成・編集されたときにだけ**1回実行され、結果がカラムに保存されます。スケジューラの
> 発火や表示などの実行経路では、そのカラムを読むだけです。

---

## 6. 予約が流れる過程(+9のユーザー / +6のデバイスの例)

ユーザー(ソウル、+9)が、バングラデシュ(ダッカ、+6)にあるバルブに対して「灌水 06:00」を
予約するとします。

```
1. アンカー決定 : 対象がデバイスなので、アンカーtz = デバイスのローカル(Asia/Dhaka, +6)
                 (_resolve_schedule_anchor)
2. 保存        : wall_to_utc("06:00", Asia/Dhaka) = 2026-07-22 00:00Z
                 SchedulerJobMeta.schedule_time=00:00Z, anchor_tz='Asia/Dhaka'
3. 発火        : utc_now()が00:00Zに達すると実行(tzは無関係)
4. 表示(運用)  : デバイスのローカル06:00(Asia/Dhaka) — _schedule_summary.when
5. 表示(ユーザー): 同じ瞬間をソウルへ → 09:00(Asia/Seoul)
```

**要点:** 保存されるのはUTC1つ(`00:00Z`)だけであり、`06:00`(デバイス)と`09:00`
(ユーザー)はその同じ瞬間の異なる表現です。新規タスクのフォームは、この3つを**リアル
タイムの二重時計**として一緒に表示します。

```
灌水 · [バルブ6(+6)] · 06:00
  Device-local: 2026-07-22 06:00 (Asia/Dhaka)   ← 実際に適用される値
  Your time:    2026-07-22 09:00 (Asia/Seoul)   ← あなたの画面
  UTC:          2026-07-22 00:00
```

> **確定した方針:** デバイス予約の壁時計は**既定でデバイスのローカル時刻**として解釈
> します(作物の太陽日を基準)。編集画面の`datetime-local`のシード値もデバイスのローカル
> 時刻で表示されるため、保存時の解釈と一致し、往復させてもずれません。

---

## 7. 表示のルール

文脈がtzを決定します。**サーバー側で特定のtzを焼き込むことはしません。**

| 文脈 | 時計 | 方法 |
|---|---|---|
| 運用(スケジューラ・デバイスログ・「いつ発火したか」) | **デバイスtz** + ラベル | フロント側の`AoTTz.formatDevice(iso, deviceTz)` |
| 個人(ユーザー通知・「あなたが今行ったこと」) | **閲覧者/ユーザーtz** | `AoTTz.formatViewer(iso)` |
| 複数のtzが重なるカレンダーの軸 | **閲覧者tz** | FullCalendarの`timeZone:'local'` |

- サーバーAPIは**UTCのISO**(`iso_utc`)だけを返し、表示用のtzはクライアント側の
  `AoTTz`が選びます。
- フロント側の単一ユーティリティ: `aot/aot_flask/static/js/common/aot-tz.js`
  (`window.AoTTz`)。
  - `formatDevice(iso, tz)` — デバイスのローカル
  - `formatViewer(iso)` — 閲覧者(個人tzを優先 → ブラウザ → システム)
  - `wallToInstant(wall, tz)` — 壁時計をtzの時計として解釈し、絶対的な瞬間を返す(二重
    時計用)
  - 閲覧者tzは`<meta name="aot-user-tz">`(User.timezone) > ブラウザtz >
    `aot-fallback-tz`(システム)の順で決まります。

---

## 8. タイムゾーンの継承(図形ツリー)

デバイスが数千台に増えても、デバイスごとにタイムゾーンを計算することはありません。
**tzは位置グループの属性**です。

```
Site (GeoShape)      → tzの権威。明示的なoverride | centroidを1回だけ解決 → 物質化
 └ Zone (GeoShape)   → Siteから継承。必要ならoverride → 物質化
     └ Device        → 所属するZone/Siteから継承(キャッシュ)
```

- 図形ツリーは`geo_shape.parent_id`(自己参照)で構成され、物理デバイスとの結び付きは
  `geo_shape.device_id`です。
- `tz_source`(`explicit` | `inherited` | `coords`)が値の出所を示します。`explicit`
  (手動でのoverride、または境界グループの選択)は**ピン留め**として扱われ、自動更新で
  上書きされません。
- **物質化と伝播:** 地図の保存(`save_overlays`/`save_delta`)がコミットされた後、
  `GeoOverlayManager.materialize_timezones(map_uuid)`がsite→zone→deviceの順にtzを
  計算してキャッシュし、連結されたデバイスへ伝播します。親図形のtz overrideは
  子・デバイスへと流れ落ちます。

---

## 9. タイムゾーンの境界 / 日付変更線

運用グループが境界をまたいでいても、**分裂しません。**

- 畑がtzの境界をまたいでいても、**サイトが単一のtzを決め、サブツリー全体がそれを継承**
  します → 「1つの畑 = 1つの時計」。
- 境界の検出は**編集時に1回だけ**行われます。図形の保存時に
  `GeoShape.detect_tz_boundary()`がbboxの4隅のtzを調べ、異なっていれば
  `tz_boundary=True`と表示します。
- `timezonefinder`は**法的(政治的)境界**を基準にしているため、中国全土が+8、
  スペインが+1、カザフスタンのアルマトイが+5など、「太陽時とは異なる法定時」も
  すでに正確に返します。

---

## 10. 開発者向けクイックリファレンス — 「いつ何を使うか」

| やりたいこと | 使うもの |
|---|---|
| 「今」(UTC) | `timekit.utc_now()` |
| 保存されたnaive/awareなdatetimeをUTCへ正規化 | `timekit.ensure_utc(dt)` |
| API応答に時刻を直列化 | `timekit.iso_utc(dt)` → フロント側の`AoTTz` |
| あるエンティティのタイムゾーンを知る | `timekit.resolve_tz(entity)`(または`device_tz.get_device_tz`) |
| 位置IDからローカルのタイムゾーンを得る | `device_tz.resolve_location_tz(target_id)` |
| 予約の壁時計 → 保存 | `timekit.wall_to_utc(wall, anchor_tz)` |
| 予約のUTC → 表示 | `timekit.utc_to_wall(dt, tz)` または `to_tz` |
| 個人向け表示tz(リクエスト時) | `timekit.current_user_tz()` |
| フロントでデバイスの時刻を表示 | `AoTTz.formatDevice(iso, deviceTz)` |
| フロントで自分の時刻を表示 | `AoTTz.formatViewer(iso)` |

---

## 11. 落とし穴集

- **naiveなカラムにはUTCの値だけ。** 非UTCのawareな値を入れるとtzinfoが取り除かれ、
  誤認されます(§4)。
- **壁時計の解釈はアンカーtzで行う。** ユーザーのブラウザtzやシステムtzで解釈すると、
  別のtzのデバイスではずれてしまいます。予約は`wall_to_utc(wall, device_anchor)`を
  使います。
- **`get_user_tz()`は実際にはシステムtzです。** 名前とは裏腹に個人のtzではありません
  (壁時計の解釈・daemonとの互換性のためのものです)。個人向け表示には
  `current_user_tz()`を使います。
- **`serialize_ts()`はシステムtzでサーバー側に変換します。** デバイスに関する表示には
  使わず、`iso_utc` + `AoTTz`を使ってください。(スケジューラの`_serialize_job`にある
  `decided_at`/`executed_at`/`created_at`は監査用のメタ情報であるため、まだ
  `serialize_ts`が残っています — 既知の軽微なギャップです。)
- **`datetime.now()`(システムのローカル)を「UTCのnow」として使わないこと。** Docker
  上ではたまたま一致しますが、非UTCのホストではずれます。`utc_now()`を使ってください。
  (ただし、経過時間の計測やoffsetの計算を目的とした`datetime.now()`は意図的なもので、
  そのままにしています。)
- **デバイスの`timezone`キャッシュは、位置を編集したイベントのときにしか更新されません。**
  座標を変えたのにtzが変わらない場合は、物質化(`materialize_timezones`)や座標リスナー
  の経路を確認してください。

---

## 12. 関連ファイル

- バックエンドの単一の入口: `aot/utils/timekit.py`
- 座標→tz・位置の解決: `aot/utils/device_tz.py`
- 図形のtz/継承/境界: `aot/databases/models/geo.py`、`aot/aot_flask/geo/geo_overlays.py`
- 座標→tzの自動物質化リスナー: `aot/databases/device_tz_listeners.py`
- 予約のアンカー・表示: `aot/ai/services/aot_data_tool_service.py`、
  `aot/aot_flask/routes_scheduler.py`
- フロント側の表示ユーティリティ: `aot/aot_flask/static/js/common/aot-tz.js`
- 設計・意思決定: `docs/design/timezone-management.md`(開発用、マニュアル未公開)
- 過去の点検レポート: `docs/design/timezone_audit.md`(開発用、マニュアル未公開)
