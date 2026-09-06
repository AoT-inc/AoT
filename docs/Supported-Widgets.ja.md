## Built-In Widgets

### AI Periodic Advice

- Libraries: ai

Displays pre-generated periodic AI analysis. Content depth adapts to widget size automatically.

### AoT Actuator Position


Displays and controls a positional (open/close) actuator: close/stop/open buttons plus a fine-adjust slider.

### AoT PID

- Libraries: controller

PIDコントローラーを表示し、制御できます。

### AoT PWM Output


Displays and controls a PWM output with a single slider.

### AoT グラフ

- Libraries: Highstock
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, data-9.1.2.js, exporting-9.1.2.js, export-data-9.1.2.js, offline-exporting-9.1.2.js

同期グラフを表示します。選択されたデータは設定された期間X軸に表示されます。

### AoT サーキュラーゲージ

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js

円形ゲージでデータを表示します。最大値オプションが最後のセクション（高）と一致していることを確認してください。温度、湿度、VPDなどのプリセットを選択すると、最小/最大値と色セクションが自動的に設定されます。

### AoT マップ

- Libraries: MapLibre GL JS (Leaflet-free)

選択した機器の位置を地図上に表示します。稼働状態を選択した色で強調表示し、3D地形・ピッチ・ベアリングに対応しています。

### AoT 区画


区画ひとつを一目で — ステージ期間バー、目標と実測、推移、積算温度。日程・指針・目標をここで編集できます。

### AoT 施設

- Libraries: Three.js 3D + IEC control

施設の3Dビュー、環境サマリー、設定値エディター、アクチュエーター制御グリッド、AIアドバイスを提供します。

### AoTコントローラスイッチ


コントローラーをオン オフするためのスイッチです

### AoTタイマー

- Libraries: timer

Use the toggle switch to turn the device on and off. Turn on "Timer" to operate on a timer: in Simple mode the device runs once for the set time (0 = run until stopped), and in Cycle mode it repeats a Run / Rest sequence for the set number of cycles. "Scheduled Start" begins operation at a set wall-clock time in the device timezone. When "Timer" is off, the toggle simply switches the device on or off regardless of the time settings.

### AoT天気予報


ユーザーが選択した期間のKMA（韓国気象庁）短期予報を表示します。

### AoT風向/風速ゲージ

- Libraries: Native SVG

円形リング上に風向（0-360°）と中央に風速を表示します。8つの基本方位線を含みます。

### Pythonコード


Pythonコードを実行し、結果をウィジェット内に表示します。

### インジケータ


測定値に応じて赤または緑の円形画像を表示します。出力のオン/オフ状態を示すのに便利です。

### カメラ


カメラ画像またはストリームを表示します。

### カレンダー


Shows scheduled events (from the Scheduler) on a calendar, split by category (AI / User / Device), and any Google calendars you connect. Click an event for details or to edit; open the full Scheduler for more.

### ゲージ (ソリッド) [Highcharts]

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, solid-gauge-9.1.2.js

ソリッドゲージを表示します。ゲージを正しく表示するには、最大値オプションを最後のStop値に設定してください。

### シーケンスコントローラー


シーケンス関数を制御・監視します。

### スペーサー


内容にテキストを設定できる、スペーサー用のシンプルなウィジェットです。

### モダンカメラ

- Libraries: aot.camera
- Dependencies: [opencv-python>=4.8.0](https://pypi.org/project/opencv-python>=4.8.0), [python-onvif-zeep>=0.2.12](https://pypi.org/project/python-onvif-zeep>=0.2.12)

依存関係の自動インストールとプロファイルに対応した高度なカメラウィジェットです。

### 掲示板


最新の掲示板投稿タイトルを表示します。タイトルをクリックすると、投稿全体(本文、投票、返信、既読確認)がポップアップで表示され、そこで行った操作はすべて実際の投稿に反映されます。書き込み権限のあるユーザーは、ウィジェットから直接投稿の作成・編集・削除も行えます。

### 測定値 (1個)


測定値とタイムスタンプを表示します。

### 測定値 (2個)


2つの測定値とタイムスタンプを表示します。

### 関数ステータス


関数のステータスを表示します(対応している場合)。

