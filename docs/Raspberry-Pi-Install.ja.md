# Raspberry Piにインストールする { #top }

Raspberry Pi 1台にAoTをDockerでインストールし、必要なら同じPiで[Matter](Matter.md)コントローラーまで有効にする手順です。
WindowsやMacへのDocker Desktopのインストールは[インストールガイド](guide/g03-install.md)にあります。このページはそのガイドと同じ2つのファイル(設計図`docker-compose.prod.yml`と設定表`.env`)を使い、異なる点だけを別に書きます。

**なぜRaspberry Piなのか。** AoTは24時間動かし続けるサーバープログラムです。Raspberry Piは消費電力が少なく、電源が入ると自動で起動し、LinuxなのでMatterに必要なホストネットワークをそのまま使えます。macOSやWindowsのDocker DesktopではMatterは動作しません([Matterの要件](Matter.md#host))。

## 準備 { #prepare }

| 項目 | 推奨 | 理由 |
|---|---|---|
| 機種 | Raspberry Pi 4または5、メモリ**4 GB以上**(8 GB推奨) | Webアプリ、デーモン、MCP、InfluxDB、Matterサーバーまで1台で動きます |
| OS | **Raspberry Pi OS (64-bit)**、Bookworm以降。画面なしで使うならLite | AoTとMatterサーバーのイメージは64ビット(arm64)のみです。32ビットOSでは起動しません |
| ストレージ | USB 3 SSD(Pi 5ではNVMeも可)。最低32 GB | 測定値のストアが書き込みを続けます。SDカードは寿命が短く遅いです |
| 電源 | 機種に合った公式電源アダプター | 電圧が足りないとSSDやUSBデバイスが切断されます |
| ネットワーク | **有線イーサネット** | Matterデバイスを探すマルチキャストはWi-Fiより安定します |
| Bluetooth | Pi 4・5内蔵のBluetooth | Matterの**新規**デバイスをBluetoothで初めて登録するときだけ使います。ほかのアプリから共有されるデバイスには不要です |

Matterを使う場合は、Piを**Matterデバイスと同じネットワーク**(同じルーター・同じVLAN)に置きます。Threadデバイスを使うには、そのネットワークにThreadボーダールーター(HomePod、Apple TV、Nest Hub、SmartThings Stationなど)がすでにある必要があります。Piはその役割を果たしません。

## 1. OSを書き込む { #os }

別のコンピューターから[Raspberry Pi Imager](https://www.raspberrypi.com/software/)でSSD(またはSDカード)にOSを書き込みます。

1. 機種を選び、OSは**Raspberry Pi OS (64-bit)**(画面が不要なら**Raspberry Pi OS Lite (64-bit)**)を選びます。
2. 書き込む前の**OSのカスタマイズ**設定で次を入力します。
    - ホスト名(例: `aot`) — あとで`aot.local`で見つけられます
    - ユーザー名とパスワード — 自分で決め、ほかの人やAIには教えません
    - ロケールとタイムゾーン(例: `Asia/Seoul`)
    - **SSHを有効にする**をオン(パスワードまたは公開鍵)
3. 書き込んだストレージをPiに挿し、LANケーブルと電源をつなぎます。初回の起動には数分かかります。

別のコンピューターのコマンドラインから接続します(ユーザー名とホスト名は手順2で決めたもの)。

```bash
ssh <ユーザー>@aot.local
```

`aot.local`が見つからない場合は、ルーターの管理画面でPiのIPを調べ、`ssh <ユーザー>@<IP>`で接続します。以降のコマンドはすべてこのSSHウィンドウ(Piの中)で実行します。

OSを最新にして再起動します。

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

!!! tip "IPを固定しておきましょう"
    ブラウザーで開くアドレスが変わらないよう、ルーターの管理画面でPiに**固定IP(DHCP予約)**を設定しておくことをおすすめします。

## 2. Dockerをインストールする { #docker }

Docker公式のインストールスクリプトで、Docker EngineとComposeプラグインをインストールします。LinuxではDocker Desktopではなく、Docker Engineを使います。

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

最後の行は、`sudo`なしで`docker`コマンドを使えるようにします。**SSHを切断して再接続**すると反映されます。再接続したら確認します。

```bash
docker version
docker compose version
```

どちらのコマンドもバージョンが表示されれば成功です。Dockerは起動時に自動で開始されます。

## 3. ファイルを取得する { #files }

[インストールガイドの手順2](guide/g03-install.md)と同じです。`<バージョン>`は[リリースページ](https://github.com/AoT-inc/AoT/releases)の**Latest**の番号です(先頭の`v`を除いた数字、例: `26.09.08`)。

```bash
mkdir -p ~/AoT/docker && cd ~/AoT/docker
curl -fsSLO https://raw.githubusercontent.com/AoT-inc/AoT/v<バージョン>/docker/docker-compose.prod.yml
curl -fsSL -o .env https://raw.githubusercontent.com/AoT-inc/AoT/v<バージョン>/docker/.env.prod.example
```

Matterを使う場合は、さらに2つのファイルを取得します。ホスト点検スクリプトと、Bluetoothで新規デバイスを登録するときに重ねて使う設定です。

```bash
curl -fsSLO https://raw.githubusercontent.com/AoT-inc/AoT/v<バージョン>/aot/scripts/check_matter_host.sh
curl -fsSLO https://raw.githubusercontent.com/AoT-inc/AoT/v<バージョン>/docker/docker-compose.matter-ble.yml
```

!!! note "Matterが含まれるリリースから"
    Matterは実験的機能で、上の2つのファイルはMatterが含まれるリリースからあります。`curl: (22) … 404`と出る場合、そのバージョンにはまだMatterがありません。リリースノートでMatterに触れているバージョンを使ってください。

`ls -a`で、取得したファイルがすべてあるか確認します。

## 4. 設定して起動する { #start }

設定表を開きます。

```bash
nano .env
```

[インストールガイドの手順3](guide/g03-install.md)の4行を確認します。Raspberry Piでは`HARDWARE_PROFILE`を**`LOW`**にします(一部のAI付加機能だけがオフになり、センサーの読み取りとデバイス制御は同じです)。

| 行 | Raspberry Piでの値 |
|---|---|
| `AOT_IMAGE_TAG` | 取得したファイルと同じバージョン番号(先頭の`v`なし) |
| `AOT_PORT` | `8084` |
| `TZ` | 現場のタイムゾーン(例: `Asia/Seoul`) |
| `HARDWARE_PROFILE` | `LOW` |

`Ctrl+O`、`Enter`で保存し、`Ctrl+X`で終了します。そして起動します。

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

初回はイメージのダウンロードに数分かかります。`aot-app`、`aot_daemon`、`aot_mcp`、`influxdb`の4つがすべて`Up`であれば成功です。

別のコンピューターのブラウザーで`http://aot.local:8084`(または`http://<PiのIP>:8084`)を開きます。**`https`ではなく`http`**です。最初の管理者アカウントの作成と動作確認は、[インストールガイドの手順5〜6](guide/g03-install.md)と同じです。

!!! danger "ボリュームを削除しないでください"
    停止するときは`docker compose -f docker-compose.prod.yml down`だけを使います。`down -v`やボリュームの削除は、設定と測定値をすべて消します。

## 5. 停電から復帰する { #power }

Raspberry Piは電源が入ると自動で起動し、Dockerは起動時に開始され、AoTのコンテナはDockerが起動すると再び立ち上がります。そのため、WindowsやMacのように別途行う設定([インストールガイドの手順7](guide/g03-install.md))はありません。

インストールが終わったら、**電源を抜いてから差し直して**確認します。数分後にブラウザーでAoTが再び開けば成功です。

!!! warning "電源をそのまま抜いて切らないでください"
    停電は避けられませんが、意図的に切るときは`sudo shutdown -h now`でシャットダウンしてから電源を外します。書き込み中に電源が切れると、ストレージが損傷することがあります。停電が多い場所では、UPSをおすすめします。

## 6. Matterを有効にする(任意) { #matter }

MatterデバイスをAoTに取り込むときだけ行います。詳しい動作は[Matter](Matter.md)のページにあります。このページのDockerインストールではなくネイティブ(`/opt/AoT`)でインストールしたPiの場合は、[ネイティブインストールで起動する](Matter.md#native)に従ってください。

### 6-1. ホストを点検する { #matter-check }

点検スクリプトは設定を**読むだけ**で、変更しません。問題があれば、修正するコマンドも一緒に表示します。

```bash
cd ~/AoT/docker
bash check_matter_host.sh
```

各行は`OK`、`WARN`、`FAIL`で始まります。`FAIL`から直し、該当する`WARN`を直します。LANケーブルとWi-Fiの両方が接続されている場合は、Matterデバイスと同じネットワーク側を`--iface eth0`のように指定します。

Raspberry Piでよくある項目:

- **IPv6がオフ、ルーター広告を受信していない**: Raspberry Pi OSは標準でIPv6がオンです。オフになっている場合は、スクリプトが表示するコマンドでオンにし、再起動後も維持されるよう保存します。
- **`ra_routes`の警告**: Threadボーダールーターのないネットワークでは正常です。Threadデバイスを使うときだけ直します。
- **`mdns_5353`**: ほかのプログラム(例: `avahi-daemon`)が5353ポートを使っていても問題ありません。情報として表示されるだけです。

### 6-2. Matterサーバーを起動する { #matter-enable }

`.env`で、Matterの行の先頭の`#`を消して有効にします。

```
COMPOSE_PROFILES=matter
```

`MATTER_LOG_LEVEL`は`info`のままにします。`debug`に上げると、サーバーがWi-Fiのパスワードをそのままログに残します。保存して、もう一度起動します。

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

`matter_server`と`matter_socket`も`Up`であれば成功です。ブラウザーで**管理 → システム管理 → 一般設定**の**Matterを使用(実験的)**をオンにして保存します。設定メニューに表示された**Matter**を開き、サーバーが接続済みと表示されるか確認します。

### 6-3. Bluetoothで新規デバイスを登録する(任意) { #matter-ble }

ほかのアプリ(Apple Home、Google Home、SmartThingsなど)から**共有される**デバイスだけを使うなら、この手順は不要です。箱から出したばかりのデバイスをAoTに直接登録するときだけ行います。

Bluetoothサービスを有効にして点検します。

```bash
sudo systemctl enable --now bluetooth
bash check_matter_host.sh --ble
```

`ble_`で始まる行が`OK`になったら、今後は**2つのファイルを一緒に**使って起動します。

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.matter-ble.yml up -d
```

!!! warning "Bluetoothを使うなら、コマンドに2つのファイルを必ず一緒に"
    あとで`docker compose -f docker-compose.prod.yml up -d`だけをもう一度実行すると、Bluetoothの設定が抜けたままMatterサーバーが作り直されます。アップグレードのときも2つのファイルを一緒に使います。

### 6-4. デバイスを追加する { #matter-add }

[Matterのページ](Matter.md#add-shared)のとおり、既存のアプリでデバイスを共有して受け取ったペアリングコードを、**管理 → システム管理 → Matter**の**Add a shared device**に入力します。

## アップグレード { #upgrade }

[Dockerデプロイのアップグレード](Upgrade-Backup-Restore.md#docker)と同じです。新しいバージョンの`docker-compose.prod.yml`を取得し、`.env`の`AOT_IMAGE_TAG`を同じ番号に変えてから、`pull`と`up -d`を行います。Matterサーバーのバージョンは自動では上がらず、`.env`の`MATTER_SERVER_TAG`で決めます。

## うまくいかないとき { #trouble }

| 症状 | 原因 | 対処 |
|---|---|---|
| `no matching manifest for linux/arm/v7`などでイメージを取得できない | 32ビットOS | **64-bit**のRaspberry Pi OSで書き込み直します。`uname -m`が`aarch64`である必要があります |
| `permission denied ... docker.sock` | `docker`グループが反映される前 | SSHを切断して再接続します |
| ブラウザーが開かない | アドレスやポートが違う、またはまだ起動中 | `ps`で4つが`Up`か、`http://<PiのIP>:8084`かを確認 |
| 遅い、またはコンテナが何度も再起動する | メモリ不足 | `free -h`で確認。4 GB未満なら大きい機種を使うか、Matterをオフにします |
| 電源を入れ直したあとUSB SSDが見つからない | 電力不足 | 公式電源アダプターを使い、SSDの消費電力が大きいなら、専用電源付きのUSBハブを使います |
| 設定 > Matterでサーバーが接続されない | `COMPOSE_PROFILES=matter`がない、または`matter_server`が停止 | `.env`を確認して`up -d`、`docker compose -f docker-compose.prod.yml logs matter_server` |
| デバイスが見つからない(タイムアウト) | Piとデバイスが別のネットワーク、またはIPv6・マルチキャストの問題 | `check_matter_host.sh`をもう一度実行。メッシュWi-Fiのマルチキャスト最適化をオフにします |
| Bluetoothでの登録が検索タイムアウトで終わる | Bluetoothがオフ、または`-f docker-compose.matter-ble.yml`なしで起動した | `check_matter_host.sh --ble`を確認し、2つのファイルで`up -d` |

## ヘルパーAI向け { #for-ai }

- ユーザーはRaspberry Pi(64ビットのRaspberry Pi OS)にSSHで接続し、Docker Engineでインストールします。Docker Desktopのコマンドを案内しないでください。
- インストールフォルダーは`~/AoT/docker`、composeファイルは`docker-compose.prod.yml`で、MatterのBluetoothを使う場合は`docker-compose.matter-ble.yml`を必ず一緒に使います。
- `down -v`、ボリュームの削除、`docker system prune --volumes`を勧めないでください。
- `MATTER_LOG_LEVEL`を`debug`に上げるよう勧めないでください(Wi-Fiのパスワードがログに残ります)。
- ペアリングコード、Wi-Fiのパスワード、管理者パスワードを尋ねないでください。
