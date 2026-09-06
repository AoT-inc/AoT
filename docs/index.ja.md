description: Documentation for AoT, an open source GIS- and AI-based environmental monitoring and control system.

## AoT 環境モニタリング・制御システム

AoTは、センサーで環境を観測し、デバイスを遠隔操作するためのオープンソースソフトウェアです。特定の用途や場所の種類に縛られません。**GIS デジタルツイン**——すべてのデバイス・センサー・構造物が地図上に実際の位置を持つ——と、その地図を読み取り、診断し、承認を得たうえで操作できる**MCP(Model Context Protocol)ベースのAIレイヤー**を中心に構築されています。

[Raspberry Pi](https://en.wikipedia.org/wiki/Raspberry_Pi) をはじめとするシングルボードコンピュータ(SBC)にネイティブで動作するほか、一般的なサーバーやPC上ではDockerで動作します。

### 情報

AoTが何を行い、各要素がどう組み合わさっているかは[About](About.md)を、機能・スクリーンショットなどその他の情報は[README](https://github.com/AoT-inc/AoT)をご覧ください。

### 前提条件

*   シングルボードコンピュータ(推奨: [Raspberry Pi](https://www.raspberrypi.org/)、Zero・1・2・3・4のいずれのバージョンでも可)
*   Debianベースのオペレーティングシステム
*   有効なインターネット接続

このほか、AoTはLinux・macOS・Windowsの各マシン上でDockerを使って動作させることもできます——下記の[Dockerでインストール](#install-with-docker)を参照してください。

### インストール

起動してログインしたら、次のコマンドを実行してAoTのインストールを開始します。

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

インストール後、SBCのIPアドレスへWebブラウザでアクセスすると、管理者ユーザーの作成とログインを求められます。

```
https://127.0.0.1
```

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
*   `TZ` — コンテナのタイムゾーン(デフォルト`Asia/Seoul`)。データはUTCで保存されるため、この値はログ表示とローカル時刻ベースのスケジュールに影響します。
*   `HARDWARE_PROFILE` — `LOW`(Raspberry Pi、小規模VM)または`HIGH`。

スタックを起動します。

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

そのポートでホストのIPアドレスへWebブラウザでアクセスすると、管理者ユーザーの作成とログインを求められます。

```
http://127.0.0.1:8084
```

Docker環境のアップグレードとは、ディスク上のファイルを置き換えることではなく、新しいイメージを取得してコンテナを再作成することを意味します。詳しくは[アップグレード/バックアップ/復元](Upgrade-Backup-Restore.md#docker)を参照してください。

!!! note
    Dockerスタックは、ホストのGPIO・I2C・1-Wireデバイスをコンテナに渡しません。Raspberry Piのピンに配線したセンサーやリレーには直接インストールを使用してください。LoRaWAN(ChirpStack)・Modbus TCP・MQTTなどネットワーク接続のデバイスは、どちらのインストール方式でも同じように動作します。

### サポート

*   [AoT on GitHub](https://github.com/AoT-inc/AoT)
*   [AoT Wiki](https://github.com/AoT-inc/AoT/wiki)
*   [AoT API](https://aot-inc.github.io/AoT/aot-api.html)
*   [ディスカッションフォーラム](https://forum.radicaldiy.com)
*   [よくある質問](https://forum.radicaldiy.com/docs?category=23&tags=aot)
