!!! note
    「Dockerでのトラブルシューティング」の節を除き、このページはネイティブ(直接)インストールを前提としています。Dockerではその節を先に見てください。ホストに`/opt/AoT`はなく、`aotflask`サービスや`upgrade_post.sh`もありません。

## アップグレード後にWeb UIへアクセスできない

アップグレード後にWeb UIへアクセスできなくなる原因はさまざまです。バグは発見され次第、継続的に修正されています。そのため、似たような症状の解決策が書かれた古いGitHub Issueやフォーラムの投稿をそのまま当てにしないでください——症状の原因がまったく別のものである可能性があるからです。まず最初に行うべきことは、アップグレードログ(/var/log/aot/aotupgrade.log)にエラーがないか確認することです。次に、以下のコマンドを実行してアップグレードを再実行してみてください。

```bash
sudo /opt/AoT/aot/scripts/upgrade_post.sh
```

## デーモンが実行されていない { #daemon-not-running }

- ナビゲーションバー左上のブランド(ロゴ)領域を見てください。異常があるときだけ色が付きます。色なしはデーモンとWebアプリの両方が正常、**赤**はデーモンが停止、**グレー**はブラウザがWebアプリにまったく届いていない状態です。画面は60秒ごとに`/daemonactive`を確認するため、状態が変わってから色が変わるまで最大1分ほどかかることがあります。
- デーモンが実行中か確認する: ターミナルで `ps aux | grep aot_daemon.py` を実行し、該当するエントリが返ってくるか確認してください。
- ログを確認する: `管理 → システムログ` ページまたは /var/log/aot/ から、デーモンログにエラーがないか確認してください。問題がアップグレード後に始まった場合は、アップグレードログにも問題の兆候がないか確認してください。
- 上記を調べても解決策が見つからない場合は、GitHub Issuesで未解決のIssueを検索するか、フォーラムで最近の投稿を検索してください。

## データベースのバージョンが正しくない { #incorrect-database-version }

- `管理 → システム情報` ページを確認してください。
- 「データベースバージョン」が通常の文字色で表示されていれば正しいバージョンです。バージョンが正しくない場合は赤色で表示され、その後ろにバージョンが正しくないことを示す文言と本来あるべきバージョンが表示されます。
- データベースのバージョンが正しくないとは、AoTの設定データベース(`/opt/AoT/databases/aot.db`)に保存されているバージョンが、AoTの設定ファイル(`/opt/AoT/aot/config.py`)で定められた最新のAoTバージョンと一致していない状態を指します。
- これは、古いデータベースバージョンから新しいバージョンへのアップグレード処理でエラーが発生した場合や、AoTのアップグレード処理中にデータベースがアップグレードされなかった場合に起こり得ます。
- 発生した可能性のある問題がないか、アップグレードログを確認してください。ログは `/var/log/aot/aotupgrade.log` にありますが、(アクセスできる場合は)Web UIからも確認できます: `管理 → システムログ` を開き、**ログ** の一覧で **AoTアップグレード** を選択してください。
- 問題がすぐには表面化しないこともあります。実際には最新のアップグレードより何バージョンも前に生じたデータベースの問題を、今になって経験しているというケースも珍しくありません。
- データベースが取り得る状態のバージョンが多岐にわたるという性質上、データベースの問題を修正するのは非常に難しい場合があります。

データベースを削除し、設定なしで最初からやり直す方がはるかに簡単な場合があります。以下のコマンドでデータベースの名前を変更し、Web UIを再起動してください。両方のコマンドが成功したら、ブラウザでWeb UIのページを更新して新しいデータベースを生成し、新しい管理者ユーザーを作成してください。

```bash
mv /opt/AoT/databases/aot.db /opt/AoT/databases/aot.db.backup
sudo service aotflask restart
```

## UIを使わずにバックアップを復元する

例えばエラーが原因でWeb UIにアクセスできない場合でも、コマンドラインからバックアップを復元できます。詳しくは[Backup and Restore](https://github.com/AoT-inc/AoT/wiki/Backup-and-Restore)を参照してください。

## 問題診断についての詳細

問題の診断について詳しくは、[Diagnosing Issues](https://github.com/AoT-inc/AoT/wiki/Diagnosing-Issues)をご覧ください。

## Dockerでのトラブルシューティング { #docker }

Dockerインストールでは、ホスト側で調べるものはDocker自体だけです。以下はチェックアウトしたディレクトリ(`docker/`がある場所)で実行してください。

**コンテナは起動しているか**

```bash
docker compose -f docker/docker-compose.prod.yml ps
```

重要なサービスは`aot-app`(Web UI)、`aot_daemon`(制御デーモン)、`aot_mcp`(外部MCPサーバー)、`influxdb`(測定値)の4つです。再起動を繰り返している、または終了しているサービスが調べる対象です。上で説明したブランドの色もこれに対応します。赤は`aot_daemon`の停止、グレーは`aot-app`に届かない状態です。

**ログを読む**

```bash
docker compose -f docker/docker-compose.prod.yml logs --tail 200 aot-app
docker compose -f docker/docker-compose.prod.yml logs --tail 200 aot_daemon
```

`-f`を付けると追いかけ続けます。Web UIに接続できる場合は`管理 → システムログ`でも同じログを見られます。

**Web UIが開かない: ポートの競合。** ホストのポートをすでに別のプログラムが使っていると、`aot-app`は「port is already allocated」というエラーで起動できません。`docker/.env`に空いているポートを指定してコンテナを再作成してください。

```bash
# docker/.env
AOT_PORT=8090
docker compose -f docker/docker-compose.prod.yml up -d
```

その後、`http://<ホストのIPアドレス>:8090`へアクセスします。

**アーキテクチャの不一致。** 公式イメージは`linux/amd64`と`linux/arm64`のみです。32ビットのRaspberry Pi OS(`armhf`)では動かせないため、その機器では直接インストールを使ってください。`uname -m`で確認できます(`x86_64`や`aarch64`なら問題ありません)。

**データの場所。** データベース・アップロードファイル・バックアップ・ログ・ユーザースクリプトは、チェックアウトではなくDockerの名前付きボリュームにあります(`docker volume ls`)。`docker compose down`やイメージの更新、コンテナの再作成をしても残ります。

!!! danger "`docker compose down -v`は絶対に実行しないでください"
    `-v`オプションは名前付きボリュームを削除し、データベース・アップロードファイル・バックアップ・InfluxDBの測定履歴も一緒に失われます。元に戻す方法はありません。スタックを停止するには`-v`なしで`docker compose -f docker/docker-compose.prod.yml down`を、サービス1つだけ再起動するには`docker compose -f docker/docker-compose.prod.yml restart aot_daemon`を使ってください。ボリュームに手を加える前には、必ずバックアップを取ってください([アップグレード/バックアップ/復元](Upgrade-Backup-Restore.md)を参照)。

**アップグレード後。** 以前のバージョンに戻すには、`docker/.env`の`AOT_IMAGE_TAG`を以前のバージョンに変えて`up -d`を再実行します。[アップグレード/バックアップ/復元](Upgrade-Backup-Restore.md#docker)を参照してください。
