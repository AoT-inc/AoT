## 著作権とライセンスについて

この文書は、オープンソースのMycodoプロジェクトをベースにしたAoTシステムのドキュメントです。

- Copyright (C) 2025 AoT
- Copyright (C) 2015–2022 Kyle T. Gabriel

GNU GPLv3ライセンスの下で配布されています。

## REST API

AoTはREST APIを提供しています(詳細は[APIエンドポイントのドキュメント](https://aot-inc.github.io/AoT/aot-api.html)を参照してください)。

APIとはApplication Programming Interfaceの略で、簡単に言えばプログラム同士が通信できるようにする一連のルールです。インターネットを通じて、データや機能を一貫した形式で公開します。

RESTはRepresentational State Transfer(表現状態転送)の略です。分散システムが一貫したインターフェースを公開する方法を説明するアーキテクチャパターンです。「REST API」という用語が使われるとき、一般にはHTTPプロトコル上のあらかじめ定められたURL群を通じてアクセスするAPIを指します。これらのURLはさまざまなリソースを表しており、そこでアクセスできる情報やコンテンツはJSON、HTML、音声ファイル、画像などとして返される場合があります。多くの場合、1つのリソースにはHTTPで実行できる1つ以上のメソッド(GET、POST、PUT、DELETE)があります。

### 認証 { #authentication }

APIキーは**管理 → システム管理 → ユーザー**でユーザーを編集し、**APIキーを生成**を選ぶと発行できます。キーは128バイトのランダムな値で、**生成された瞬間に一度だけ**base64エンコードされた文字列として表示されます — AoTはキー自体ではなく一方向ハッシュのみを保存するため、後から再表示することはできません。紛失した場合は新しく生成してください。詳しくは[セキュリティ](Security.md#api-keys)を参照してください。

AoTは複数の認証方式に対応しています。すべてのAPIリクエストはHTTPS経由で行う必要があります。平文HTTP経由の呼び出しは失敗します。認証なしのAPIリクエストも失敗します。

### Bashの例

``curl``を使うことができますが、署名なしのSSL証明書を使えるように``-k``を付けるか、独自の証明書とドメインを使う必要があります。

```bash
curl -k -v -X GET "https://127.0.0.1/api/settings/users" -H "authorization: Basic YOUR_API_KEY" -H "accept: application/vnd.aot.v1+json"
```

```bash
curl -k -v -X GET "https://127.0.0.1/api/settings/users" -H "X-API-KEY: YOUR_API_KEY" -H "accept: application/vnd.aot.v1+json"
```

APIキーは`?api_key=`クエリパラメータとして渡すこともできますが、この方式は
**非推奨であり、将来のリリースで削除される予定です**:

```bash
# 非推奨 — 上記のいずれかのヘッダー方式を使ってください
curl -k -v -X GET "https://127.0.0.1/api/settings/users?api_key=YOUR_API_KEY" -H "accept: application/vnd.aot.v1+json"
```

クエリ文字列に入れたキーはWebサーバーのアクセスログ、リバースプロキシのログ、
`Referer`ヘッダーに記録されるため、それらを閲覧できる人には事実上公開された
状態になります。この方式でのリクエストは非推奨の警告とともにログに記録され、
監査ログ(`apikey.url_auth`)にも残るため、廃止前に残っている利用箇所を洗い出せます。

### Pythonの例(GET)

```python
import json
import requests

ip_address = '127.0.0.1'
api_key = 'YOUR_API_KEY'
endpoint = 'settings/inputs'
url = 'https://{ip}/api/{ep}'.format(ip=ip_address, ep=endpoint)
headers = {
    'Accept': 'application/vnd.aot.v1+json',
    'X-API-KEY': api_key
}
response = requests.get(url, headers=headers, verify=False)
print("レスポンスステータス: {}".format(response.status_code))
print("レスポンスヘッダー: {}".format(response.headers))
response_dict = json.loads(response.text)
print("レスポンス辞書: {}".format(response_dict))
```

### Pythonの例(POST)

```python
import json
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ip_address = '127.0.0.1'
api_key = 'YOUR_API_KEY'
endpoint = 'outputs/3f5a4806-c830-432d-b329-7821da8336e4'
url = 'https://{ip}/api/{ep}'.format(ip=ip_address, ep=endpoint)
data = {"state": True}  # 出力をオンにします
headers = {
    'Accept': 'application/vnd.aot.v1+json',
    'X-API-KEY': api_key
}
response = requests.post(url, json=data, headers=headers, verify=False)
print("レスポンスステータス: {}".format(response.status_code))
print("レスポンスヘッダー: {}".format(response.headers))
response_dict = json.loads(response.text)
print("レスポンス辞書: {}".format(response_dict))
```

### エラー

AoTはAPIリクエストの成功・失敗を表すために、一般的なHTTPレスポンスコードを使用します。おおむね、2xx台のコードは成功を示します。4xx台のコードは、渡された情報が原因で失敗したエラーを示します(たとえば必須パラメータが欠けている、決済が失敗した、など)。5xx台のコードはAoTサーバー側のエラーを示します(こちらはまれです)。

プログラム側で処理できる4xxエラー(たとえばカードが拒否された場合など)には、報告された問題を簡潔に説明するエラーコードが含まれます。

### エンドポイント

APIのバージョンを判別するため、ベンダー固有のコンテンツタイプヘッダーを含める必要があります。バージョン1の場合、上記の例にもある通り "application/vnd.aot.v1+json" です。

`https://{RASPBERRY_PI_IP_ADDRESS}/api` にアクセスすると、お使いのAoTインストールにおける現在のAPIエンドポイントのドキュメントを確認できます。

最新のAPIバージョンのドキュメントはHTML形式でも公開されています: `AoT API Documentation <https://aot-inc.github.io/AoT/aot-api.html>`__

## デーモン制御オブジェクト { #daemon-control-object }

### DaemonControl()

**class aot_client.DaemonControl**\ (*pyro_uri='PYRO:aot.pyro_server@127.0.0.1:9080'*, *pyro_timeout=None*)

aotクライアントオブジェクトは、aotデーモンと通信したりinfluxdbデータベースから情報を照会したりするためのメソッドを実装しています。

使用例:

```python
from aot.aot_client import DaemonControl
control = DaemonControl()
control.terminate_daemon()
```

パラメータ:

-  **pyro_uri** - デーモンへの接続に使うPyro5のuriです。
-  **pyro_timeout** - Pyro5のタイムアウト時間です。

### controller_activate()

**controller_activate**\ (*controller_id*)

コントローラーを有効化します。

パラメータ:

-  **controller_type** - 有効化するコントローラーの種類です。指定できる値は "Function"、"Input"、"Output"、"PID"、"Trigger"、"Function" です。
-  **controller_id** - 有効化するコントローラーの一意のIDです。

### controller_deactivate()

**controller_deactivate**\ (*controller_id*)

コントローラーを無効化します。

パラメータ:

-  **controller_type** - 無効化するコントローラーの種類です。指定できる値は "Conditional"、"Input"、"Output"、"PID"、"Trigger"、"Function" です。
-  **controller_id** - 無効化するコントローラーの一意のIDです。

### get_condition_measurement()

**get_condition_measurement**\ (*condition_id*)

条件付き機能の条件から測定値を取得します。

パラメータ:

-  **condition_id** - コントローラーの一意のIDです。

### get_condition_measurement_dict()

**get_condition_measurement_dict**\ (*condition_id*)

条件付き機能の条件から測定値の辞書を取得します。

パラメータ:

-  **condition_id** - コントローラーの一意のIDです。

### input_force_measurements()

**input_force_measurements**\ (*input_id*)

入力に測定を強制的に実行させます。

パラメータ:

-  **input_id** - コントローラーの一意のIDです。

### lcd_backlight()

**lcd_backlight**\ (*lcd_id*, *state*)

LCDがこの機能に対応している場合に、そのバックライトのオン・オフを切り替えます。

パラメータ:

-  **lcd_id** - コントローラーの一意のIDです。
-  **state** - LCDバックライトの状態です。False(オフ)、True(オン)のいずれかです。

### lcd_flash()

**lcd_flash**\ (*lcd_id*, *state*)

LCDがこの機能に対応している場合に、バックライトの点滅を開始または停止します。

パラメータ:

-  **lcd_id** - コントローラーの一意のIDです。
-  **state** - LCD点滅の状態です。False(停止)、True(開始)のいずれかです。

### lcd_reset()

**lcd_reset**\ (*lcd_id*)

LCDを初期の起動状態にリセットします。画面を消去したり、表示の不具合を直したり、点滅を止めたりするのに使えます。

パラメータ:

-  **lcd_id** - コントローラーの一意のIDです。

### output_off()

**output_off**\ (*output_id*, *trigger_conditionals=True*)

出力をオフにします。

パラメータ:

-  **output_id** - 出力の一意のIDです。
-  **trigger_conditionals** - 状態変化を監視しているコントローラーをトリガーするかどうかです。

### output_on()

**output_on**\ (*output_id*, *output_type='sec'*, *amount=0.0*, *min_off=0.0*, *trigger_conditionals=True*)

出力をオンにします。

パラメータ:

-  **output_id** - 出力の一意のIDです。
-  **output_type** - 出力モジュールに送る出力タイプです(例: "sec"、"pwm"、"vol")。
-  **amount** - 出力モジュールに送る量です。
-  **min_off** - オンにした後、出力がオフのままでいなければならない最小時間です。
-  **trigger_conditionals** - 状態変化を監視しているコントローラーをトリガーするかどうかです。

### output_on_off()

**output_on_off**\ (*output_id*, *state*, *output_type='sec'*, *amount=0.0*,)

出力をオン・オフします。

パラメータ:

-  **output_id** - 出力の一意のIDです。
-  **state** - 出力をオンにするかオフにするかを示します。指定できる値は "on"、"off" です。
-  **output_type** - 出力モジュールに送る出力タイプです(例: "sec"、"pwm"、"vol")。
-  **amount** - 出力モジュールに送る量です。

### output_sec_currently_on()

**output_sec_currently_on**\ (*output_id*)

その出力がオンになっている継続時間を秒単位で取得します。

パラメータ:

-  **output_id** - 出力の一意のIDです。

### output_setup()

**output_setup**\ (*action*, *output_id*)

出力をセットアップします(例: データベースから設定を読み込み/再読み込みする、ピンやクラスを初期化する、など)。

パラメータ:

-  **action** - 出力に実行させるアクションです。指定できる値は "Add"、"Delete"、"Modify" です。
-  **output_id** - 出力の一意のIDです。

### output_state()

**output_state**\ (*output_id*)

出力の状態を取得します。"on"、"off"、またはデューティサイクルの値を返します。

パラメータ:

-  **output_id** - 出力の一意のIDです。

### pid_get()

**pid_get**\ (*pid_id*, *setting*)

PIDコントローラーのパラメータを取得します。

パラメータ:

-  **pid_id** - コントローラーの一意のIDです。
-  **setting** - 取得するオプションです。指定できる値は "setpoint"、"error"、"integrator"、"derivator"、"kp"、"ki"、"kd" です。

### pid_hold()

**pid_hold**\ (*pid_id*)

PIDコントローラーを保留状態にします。

パラメータ:

-  **pid_id** - コントローラーの一意のIDです。

### pid_mod()

**pid_mod**\ (*pid_id*)

実行中のPIDコントローラーの変数を再読み込みまたは再初期化します。

パラメータ:

-  **pid_id** - コントローラーの一意のIDです。

### pid_pause()

**pid_pause**\ (*pid_id*)

PIDコントローラーを一時停止状態にします。

パラメータ:

-  **pid_id** - コントローラーの一意のIDです。

### pid_resume()

**pid_resume**\ (*pid_id*)

PIDコントローラーを再開状態にします。

パラメータ:

-  **pid_id** - コントローラーの一意のIDです。

### pid_set()

**pid_set**\ (*pid_id*, *setting*, *value*)

実行中のPIDコントローラーのパラメータを設定します。

パラメータ:

-  **pid_id** - コントローラーの一意のIDです。
-  **setting** - 設定するオプションです。指定できる値は "setpoint"、"method"、"integrator"、"derivator"、"kp"、"ki"、"kd" です。
-  **value** - 設定する値です。

### module_function()

**module_function**\ (*controller_type*, *unique_id*, *button_id*, *args_dict*, *thread=True*, *return_from_function=False*)

特定のモジュール(Input、Outputなど)のカスタム関数を直接実行します。これは主に**センサーのキャリブレーション**作業に使われます。

パラメータ:

-  **controller_type**: モジュールの種類です(例: "Input"、"Output")
-  **unique_id**: モジュールの一意のIDです
-  **button_id**: 実行する関数のIDです(例: "mid_calibrate"、"clear_calibrate")
-  **args_dict**: 関数に渡すパラメータの辞書です

### refresh_daemon_conditional_settings()

**refresh_daemon_conditional_settings**\ (*unique_id*)

実行中の条件付き機能の設定を再読み込みします。

### refresh_daemon_misc_settings()

**refresh_daemon_misc_settings**\ ()

実行中のデーモンのその他の設定を、データベースの値から再読み込みします。

### refresh_daemon_trigger_settings()

**refresh_daemon_trigger_settings**\ (*unique_id*)

実行中のトリガーコントローラーの設定を再読み込みします。

### check_daemon()

**check_daemon**\ ()

デーモンの稼働状況を確認します。"GOOD" またはエラーメッセージを返します。

---

> [!NOTE]
> AIエージェント向けの構造化されたAPI仕様は `ai_docs/api.json` ファイルにあります。
