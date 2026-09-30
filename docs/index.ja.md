description: Documentation for AoT, an open source GIS- and AI-based environmental monitoring and control system.

## AoT 環境モニタリング・制御システム

AoT は、自分の空間を地図に収め、その場所の記録とデバイスを結びつけます。そして、その空間を AI が人と一緒に見て、判断し、作業できるようにします。

センサーで環境を観測し、デバイスを遠隔操作するためのオープンソースソフトウェアであり、特定の用途や場所の種類に縛られません。デバイス・センサー・構造物を**GIS 地図**上の実際の位置に置くことができ、**MCP(Model Context Protocol)ベースのAIレイヤー**がシステムを読み取り、診断し、承認を得たうえで操作できます。どの機能を使うかは利用者が決めます。

[Raspberry Pi](https://en.wikipedia.org/wiki/Raspberry_Pi) をはじめとするシングルボードコンピュータ(SBC)にネイティブで動作するほか、一般的なサーバーやPC上ではDockerで動作します。

### 情報

AoTが何を行い、各要素がどう組み合わさっているかは[About](About.md)を、機能・スクリーンショットなどその他の情報は[README](https://github.com/AoT-inc/AoT)をご覧ください。

### 前提条件

*   シングルボードコンピュータ(推奨: [Raspberry Pi](https://www.raspberrypi.org/) 2・3・4以降)、またはその他のDebianベースのLinuxマシン
*   Debianベースのオペレーティングシステム(32ビット`armhf`、64ビット`arm64`、`amd64`)、Python 3.8以上
*   有効なインターネット接続

インストーラーはCPUアーキテクチャを検出し、`armhf`・`arm64`・`amd64`に対応します。Raspberry Pi ZeroとPi 1(ARMv6)は検証していないため、対応対象として記載していません。

このほか、AoTはLinux・macOS・Windowsの各マシン上でDockerを使って動作させることもできます——下記の[Dockerでインストール](#install-with-docker)を参照してください。

### インストール

起動してログインしたら、次のコマンドを実行してAoTのインストールを開始します。

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

インストール後、SBCのIPアドレスへWebブラウザでアクセスします。

```
https://<PiのIPアドレス>
```

`https://127.0.0.1`(または`localhost`)は、Pi自身で開いたブラウザでのみ動作します。別のコンピュータからはPiのIPアドレスを使ってください。インストーラーが自己署名証明書を作成するため、初回アクセス時にブラウザが証明書の警告を表示します。警告を承諾して先へ進んでください。

このあとの画面は下記の[初回起動](#first-run)を参照してください。

### MQTTブローカー { #mqtt-broker-security }

直接インストールでは、ローカルの[Mosquitto](https://mosquitto.org/) MQTTブローカーも設定されます。既定では同じ機器(`127.0.0.1`)からの接続のみ受け付け、AoTのMQTT入力・出力の既定の接続先(`localhost:1883`)と一致します。

*   外部ゲートウェイなど他の機器から接続する場合は、インストールコマンドを実行する前に、同じ端末で `export AOT_MQTT_LISTEN_ALL=1` を実行します。この場合、すべてのネットワークインターフェースで**ログインなし**で接続できるため、信頼できるネットワークでのみ使うか、`/etc/mosquitto/conf.d/aot.conf` にパスワードファイル(`allow_anonymous false`、`password_file`)を追加してください。
*   既存のインストールでは、現在の `/etc/mosquitto/conf.d/aot.conf` がそのまま維持されます。以前のバージョンは `listener 1883` と `allow_anonymous true` を書き込み、ネットワーク全体からログインなしで接続できました。インストール・アップグレードでこのファイルは変更されず、このように開いている場合は警告のみ表示されます。制限するには、1行目を `listener 1883 127.0.0.1` に変更し、`sudo systemctl restart mosquitto` を実行してください。ネットワーク上のゲートウェイがこのブローカーへ発行していないことを確認してから変更してください。

### Dockerでインストール { #install-with-docker }

前提条件: Compose v2を含む[Docker](https://docs.docker.com/get-docker/)。公式イメージは`linux/amd64`と`linux/arm64`向けに公開されています。

composeファイルはリポジトリ内のカスタム拡張ディレクトリ(`aot/inputs/custom_inputs`など)をマウントするため、先にリポジトリをクローンします。

```bash
git clone https://github.com/AoT-inc/AoT.git /opt/AoT
cd /opt/AoT
cp docker/.env.prod.example docker/.env
```

`docker/.env`内の次の値を確認してください。

*   `AOT_IMAGE_TAG` — インストールするバージョン。特定の[リリース](https://github.com/AoT-inc/AoT/releases)に固定することを推奨します。
*   `AOT_PORT` — Webインターフェース用のホストポート(デフォルト`8084`)。
*   `TZ` — コンテナのタイムゾーン(デフォルト`Asia/Seoul`)。システムタイムゾーン設定の**初回起動時の既定値**だけを決めます(データベースの初回作成時に一度コピーされ、その後変更しても影響しません)。ログの時刻とスケジュールは、システムタイムゾーン設定と地図上のサイト・ゾーンの位置に従います。初回ログイン後にシステムタイムゾーンを確認し、サイトとゾーンを地図に配置してください。データは常にUTCで保存されます。
*   `HARDWARE_PROFILE` — `LOW`(デフォルト)、`MEDIUM`、`HIGH`。変わるのはAIアシスタント機能だけです。`LOW`はVEEとEKGの機能をオフにし(AIインテントルーターはオンのまま)、`MEDIUM`と`HIGH`はVEEとEKGをオンにします。`HIGH`はEKGのウィンドウをより大きく(500件ではなく5000件)保持します。センサー・出力・制御はどの値でも同じなので、Raspberry Piや小規模VMでは`LOW`のままにしてください。

スタックを起動します。

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

そのポートでホストのIPアドレスへWebブラウザでアクセスします。

```
http://<ホストのIPアドレス>:8084
```

`http://127.0.0.1:8084`(または`localhost`)は、Dockerホスト自身で開いたブラウザでのみ動作します。Dockerスタックは既定でHTTPSを使わないため、証明書の警告は出ません。HTTPSが必要な場合は前段にリバースプロキシを置いてください([セキュリティ](Security.md)を参照)。

Docker環境のアップグレードとは、ディスク上のファイルを置き換えることではなく、新しいイメージを取得してコンテナを再作成することを意味します。詳しくは[アップグレード/バックアップ/復元](Upgrade-Backup-Restore.md#docker)を参照してください。

!!! note
    Dockerスタックは、ホストのGPIO・I2C・1-Wireデバイスをコンテナに渡しません。Raspberry Piのピンに配線したセンサーやリレーには直接インストールを使用してください。LoRaWAN(ChirpStack)・Modbus TCP・MQTTなどネットワーク接続のデバイスは、どちらのインストール方式でも同じように動作します。

### 初回起動 { #first-run }

新規インストール(直接インストール・Dockerとも)では、ログインフォームではなく公開のランディングページが最初に開きます。管理者ユーザーがまだいない間の流れは次のとおりです。

1. ランディングページで**ログイン**を押します。`/login`へ移動しますが、管理者がいないためそのまま`/create_admin`へ転送されます。
2. 最初の画面は**品質保証に関する通知**(ライセンス・保証・匿名統計)です。読んで**承認します**を押します。
3. 管理者作成フォームが表示されます。ユーザー名・メール・パスワードを入力して送信します。
4. 作成したアカウントでログインします。統計収集は、あとから`管理 → システム管理 → 一般設定`で拒否できます。

### サポート

*   [AoT on GitHub](https://github.com/AoT-inc/AoT)
*   [AoT Wiki](https://github.com/AoT-inc/AoT/wiki)
*   [AoT API](https://aot-inc.github.io/AoT/aot-api.html)
*   [ディスカッションフォーラム](https://forum.radicaldiy.com)
*   [よくある質問](https://forum.radicaldiy.com/docs?category=23&tags=aot)
