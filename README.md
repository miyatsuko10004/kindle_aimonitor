# kindle_aimonitor

`aimonitor` のダッシュボードを、使っていない Kindle に電子ペーパーのモニターとして表示するための中継サーバーです。

- Mac 上の aimonitor（`127.0.0.1:8765`）から情報を読み取り、白黒・JavaScript なしの HTML に変換して LAN に配信します（ポート `8766`）。
- Kindle の「体験版ブラウザ」でも表示できるよう、table レイアウトと meta refresh（60秒）だけで構成しています。
- aimonitor 本体は変更しません。aimonitor は引き続き localhost 限定です。

## 使い方

```sh
aimonitor start          # 先に本体を起動
./kindlemon start        # Kindle 用ビューを起動し、URL を表示
./kindlemon url          # URL を再表示
./kindlemon status
./kindlemon stop
```

表示された `http://<MacのIP>:8766/?k=<トークン>` を Kindle のブラウザ（メニュー →「体験版ブラウザ」）で開き、ブックマークします。初回起動時に macOS のファイアウォールが Python の受信接続を許可するか尋ねる場合があります。

## Kindle 側のコツ

- **スリープさせない**: ホーム画面の検索バーに `~ds` と入力して Enter（スクリーンセーバーを無効化。古いファームウェアのみ有効で、再起動すると元に戻ります）。
- 常時表示する場合は USB 給電したままにします。
- 端末を横向きにすると 2 列、縦向きでは 1 列のレイアウトになります。
- 時刻ボタンをタップすると、その場で再読み込みします。

## セキュリティ

- アクセスにはトークン（`.kindle_token`、パーミッション 600）が必要です。トークンを変えたいときはファイルを削除して `./kindlemon stop && ./kindlemon start` を実行します。
- 通信は HTTP（平文）です。自宅など信頼できる LAN でのみ使ってください。
- 作業ディレクトリはフルパスではなく末尾のフォルダ名だけを表示します。認証情報は扱いません。

## テスト

```sh
python3 -m unittest -v
```
