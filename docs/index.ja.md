description: Documentation for AoT, an open source GIS- and AI-based environmental monitoring and control system.

## AoT 環境監視・制御システム

AoTはセンサーで環境を観測し、機器を遠隔制御するオープンソースソフトウェアで、特定の用途や場所に縛られません。すべてのデバイス・センサー・構造物が地図上の実際の位置を持つ **GISデジタルツイン** と、その地図を読み、診断し、ユーザーの承認を得て操作する **MCP（Model Context Protocol）ベースのAI** を中心に構築されています。

[Raspberry Pi](https://en.wikipedia.org/wiki/Raspberry_Pi) などのシングルボードコンピュータに直接インストールするほか、一般的なサーバーやPCではDockerで実行できます。

### 情報

AoTが何をするのか、各要素がどう組み合わさるのかは [概要](About.md) を、機能やスクリーンショットなどその他の情報は [README](https://github.com/AoT-inc/AoT) を参照してください。

### 必須条件

*   シングルボードコンピュータ 推奨: [Raspberry Pi](https://www.raspberrypi.org/) Zero, 1, 2, 3, 4の全バージョン対応 
*   Debian系OS
*   アクティブなインターネット接続

Dockerが動作するLinux・macOS・Windows環境でも実行できます — 下記の[Dockerでインストール](#install-with-docker)を参照してください。

### インストール

起動してログインしたら、次のコマンドを実行してAoTのインストールを開始してください

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

インストール後、SBCのIPアドレスにブラウザでアクセスすると管理者ユーザーの作成とログインが求められます。

```
https://127.0.0.1
```

### Dockerでインストール { #install-with-docker }

必須条件: [Docker](https://docs.docker.com/get-docker/)（Compose v2を含む）。公式イメージは `linux/amd64` と `linux/arm64` で発行されています。

composeファイルはリポジトリ内のカスタム拡張ディレクトリ（`aot/inputs/custom_inputs` など）をマウントするため、先にリポジトリを取得してください。

```bash
git clone https://github.com/AoT-inc/AoT.git /opt/AoT
cd /opt/AoT
cp docker/.env.prod.example docker/.env
```

`docker/.env` で次の項目を確認してください。

*   `AOT_IMAGE_TAG` — インストールするバージョン。[リリース](https://github.com/AoT-inc/AoT/releases)の正確なバージョンに固定することを推奨します。
*   `AOT_PORT` — Webインターフェースを公開するホストのポート（既定 `8084`）。
*   `TZ` — コンテナのタイムゾーン（既定 `Asia/Seoul`）。データはUTCで保存され、この値はログ表示とローカル時刻ベースのスケジュールに影響します。
*   `HARDWARE_PROFILE` — `LOW`（Raspberry Pi・小規模VM）または `HIGH`。

起動:

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

そのポートにブラウザでアクセスすると、管理者ユーザーの作成とログインが求められます。

```
http://127.0.0.1:8084
```

Docker版のアップグレードは、ディスク上のファイルを置き換えるのではなく、新しいイメージを取得してコンテナを作り直す方式です。[アップグレード/バックアップ/復元](Upgrade-Backup-Restore.md#docker)を参照してください。

!!! note
    Docker構成では、ホストのGPIO・I2C・1-Wireデバイスはコンテナに渡されません。Raspberry Piのピンに直接接続したセンサーやリレーを使う場合は直接インストールを利用してください。LoRaWAN（ChirpStack）・Modbus TCP・MQTTなどネットワーク接続のデバイスは、どちらのインストール方式でも同じように動作します。

### サポート

*   [AoT on GitHub](https://github.com/AoT-inc/AoT)
*   [AoT Wiki](https://github.com/AoT-inc/AoT/wiki)
*   [AoT API](https://aot-inc.github.io/AoT/aot-api.html)
*   [ディスカッションフォーラム](https://forum.radicaldiy.com)
*   [よくある質問](https://forum.radicaldiy.com/docs?category=23&tags=aot)

