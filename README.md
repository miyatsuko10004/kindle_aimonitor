# kindle_aimonitor

Codex・Claude Code・Antigravity の利用枠と、Mac で動いている AI エージェントの状況を、使っていない Kindle に電子ペーパーのダッシュボードとして表示します。

- Mac 上で利用状況を収集し、白黒・JavaScript なしの HTML として LAN に配信します（ポート `8766`）。
- Kindle の「体験版ブラウザ」でも表示できるよう、table レイアウトと meta refresh（60秒）だけで構成しています。
- 他のアプリは不要です。単体で動きます。

## 動作環境

macOS、Python 3.10 以上。追加パッケージは不要です。監視するサービス（Codex / Claude Code）にログイン済みである必要があります。Antigravity のライブ取得にはアプリが起動している必要があります。

## 使い方

```sh
git clone git@github.com:miyatsuko10004/kindle_aimonitor.git
cd kindle_aimonitor
./kindlemon start        # バックグラウンドで起動し、Kindle 用の URL を表示
./kindlemon url          # URL を再表示
./kindlemon status
./kindlemon stop
```

表示された `http://<MacのIP>:8766/?k=<トークン>` を Kindle のブラウザ（メニュー →「体験版ブラウザ」）で開き、ブックマークします。

- 起動直後は「初回データを収集しています」と表示されます。次の自動更新で中身が出ます。
- 初回起動時に、macOS のファイアウォールが Python の受信接続を許可するか尋ねる場合があります。
- Claude Code の利用枠は macOS のキーチェーンにある既存の認証情報を読みます。初回はキーチェーンへのアクセス許可を求められる場合があります。
- Mac を再起動したら、もう一度 `./kindlemon start` を実行してください。

## 表示内容と取得元

| サービス | 利用枠 | エージェント情報 |
|---|---|---|
| Codex | 5時間・週間の使用率とリセットまでの時間 | セッション、モデル |
| Claude Code | 5時間・週間（取得できる場合） | 起動中セッション、最後の応答モデル |
| Antigravity | モデル別の使用率 | language server の起動、最近の会話 |

収集処理（`collectors.py`）は [aimonitor](https://github.com/miyatsuko10004/aimonitor) と同じものです。各サービスの非公開 API や内部データを読むため、サービス側の変更で取得できなくなる場合があります。認証情報の書き換えや自動ログインは行いません。

## Kindle 側のコツ

- **スリープさせない**: ホーム画面の検索バーに `~ds` と入力して Enter（スクリーンセーバーを無効化。古いファームウェアのみ有効で、再起動すると元に戻ります）。
- 常時表示する場合は USB 給電したままにします。
- 端末を横向きにすると 2 列、縦向きでは 1 列のレイアウトになります。
- 時刻ボタンをタップすると、その場で再読み込みします。

## セキュリティ

- アクセスにはトークン（`.kindle_token`、パーミッション 600）が必要です。トークンを変えたいときはファイルを削除して `./kindlemon stop && ./kindlemon start` を実行します。
- 通信は HTTP（平文）です。自宅など信頼できる LAN でのみ使ってください。
- 認証情報はサーバー内でだけ使い、Kindle には送りません。会話本文も扱いません。
- 作業ディレクトリはフルパスではなく末尾のフォルダ名だけを表示します。

## 開発

```sh
python3 -m unittest -v
```

| ファイル | 役割 |
|---|---|
| `collectors.py` | 利用枠・セッションの読み取り専用収集 |
| `kindle_server.py` | 収集ループと Kindle 向け HTML 配信 |
| `kindlemon` | バックグラウンド起動・停止・URL 表示 |
