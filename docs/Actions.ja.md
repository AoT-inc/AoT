これらは、コントローラー(つまり入力・条件付き・トリガーの各コントローラー)に追加できるアクションで、追加機能を持たせたり、AoTの他の部分とやり取りしたりする手段を提供します。アクションがどのコントローラー種別で動作するかは、そのアクションの設計によって異なります。

サポートされているアクションの全一覧は、[サポートされているアクション](Supported-Actions.md)を参照してください。

## カスタムアクション { #custom-actions }

AoTには、ユーザーが作成したアクションをAoTシステム内で使用できるようにする、カスタムアクションのインポート機能があります。カスタムアクションは `[歯車アイコン] -> 構成 -> カスタムアクション` ページからアップロードできます。インポートすると、`設定 -> 機能` ページで使用できるようになります。

動作するアクションモジュールを開発した場合は、[新しいGitHub Issueの作成](https://github.com/AoT-inc/AoT/issues/new?assignees=&labels=&template=feature-request.md&title=New%20Module)やプルリクエストの送信を検討してください。そのモジュールが標準搭載セットに取り込まれる可能性があります。

きちんとフォーマットされた例を確認するには、ディレクトリ [AoT/aot/actions](https://github.com/AoT-inc/AoT/tree/main/aot/actions/) にある標準搭載モジュールを開いてみてください。

また、ディレクトリ [AoT/aot/actions/examples](https://github.com/AoT-inc/AoT/tree/main/aot/actions/examples) には、カスタムアクションのサンプルが含まれています。

標準搭載セットには含まれていないカスタムモジュールを専門に扱う別のGitHubリポジトリが、[aot-inc/AoT-custom](https://github.com/AoT-inc/AoT-custom) にあります。
