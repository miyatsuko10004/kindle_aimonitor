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

各サービスの非公開 API や内部データを読むため、サービス側の変更で取得できなくなる場合があります。認証情報の書き換えや自動ログインは行いません。

## Kindle 側のコツ

- **スリープについて**: 最近のファームウェア（5.18 系など）では、脱獄しないとスクリーンセーバーを止められません。止めない場合は、数分間操作がないとダッシュボードが隠れます。常時表示したい場合は下の「脱獄（参考）」を参照してください。
- 古いファームウェアでは、ホーム画面の検索バーに `~ds` と入力して Enter するとスクリーンセーバーを無効にできる場合があります（再起動で元に戻ります）。
- 常時表示する場合は USB 給電したままにします。
- 端末を横向きにすると 2 列、縦向きでは 1 列のレイアウトになります。
- 時刻ボタンをタップすると、その場で再読み込みします。

## 脱獄（参考）

スクリーンセーバーを止めて常時表示するには、Kindle の脱獄が必要です。以下は Kindle Paperwhite 第10世代（PW4）・ファームウェア 5.18.1・広告なしモデルで実施した手順のメモです。

> [!WARNING]
> 脱獄は非公式の改造で、保証の対象外になる可能性があります。端末が起動しなくなるリスクもあります。自己責任で行ってください。手順やツールは更新されるため、必ず [Kindle Modding Wiki](https://kindlemodding.org/jailbreaking/index.html) の最新情報を確認してください。

### 1. 使える脱獄方法を調べる

Kindle の「設定 → 端末オプション → 端末情報」で、シリアル番号・ファームウェアのバージョン・ロック画面広告の有無を確認します。それを [Find my Jailbreak](https://kindlemodding.org/jailbreak-wizard.html) に入力すると、使える方法が表示されます。

PW4・5.18.1・広告なしの場合、使えるのは **SpiderCat** と **Sanctuary** です（AdBreak は広告付きモデル専用）。以下は SpiderCat の手順です。

### 2. 自動アップデートを防ぐ（容量を埋める）

脱獄の途中は Wi‑Fi をオンにする必要があります。その間に自動アップデートが入ると、脱獄できないファームウェアに更新されることがあります。それを防ぐため、Kindle のストレージを埋めて空きを 50〜90MB にしておきます（[公式ガイド](https://kindlemodding.org/jailbreaking/prevent-auto-update/)）。

1. Kindle を機内モードにし、USB で Mac に接続します。
2. Kindle 直下に `update*.bin` などのアップデートファイルがあれば削除します。
3. 空きが約 70MB になるまでダミーファイルを作ります。macOS 標準の `mkfile` だけで作れます。

```sh
K=/Volumes/Kindle
mkdir -p "$K/fill_disk"
i=0
while :; do
  free=$(df -m "$K" | awk 'NR==2{print $4}')
  left=$((free - 70)); [ $left -le 0 ] && break
  mkfile $(( left > 100 ? 100 : left ))m "$K/fill_disk/fill_$i.bin" || break
  sync; i=$((i + 1))
done
df -h "$K"
```

Kindle への書き込みは遅く、数 GB を埋めるには 30 分以上かかることがあります。途中で USB が外れたら、つなぎ直して再実行してください。

### 3. SpiderCat を実行する（[公式ガイド](https://kindlemodding.org/jailbreaking/SpiderCat/)）

1. 公式ガイドから `spidercat.azw3` を入手し、Kindle の `documents` フォルダにコピーします。Kindle のブラウザから直接ダウンロードすることもできます。
2. Kindle を取り出して USB を抜き、機内モードを解除して Wi‑Fi に接続します。終わるまで Wi‑Fi はオンのままにします。
3. ライブラリから「SpiderCat」を開きます。しばらく画面が白いままになり、そのあと文字が流れ始めます。
4. 「アプリケーションエラー」が出ても無視します。
5. 「Restarting Kindle」と表示されて再起動したら成功です。最後の行が `abort:no-firm` なら非対応です。
6. Kindle ストアを開くなど、他の操作は終わるまでしないでください。

### 4. 脱獄後の後片付け

1. Kindle 直下に `.bin` のアップデートファイルがあれば削除します。
2. 容量埋めのダミーファイルを削除します（脱獄後はアップデートがブロックされます）。

```sh
rm -rf /Volumes/Kindle/fill_disk
```

3. 公式 Wiki の「[What's Next?](https://kindlemodding.org/jailbreaking/whats-next/index.html)」に従って、必要な拡張（KUAL など）を入れます。

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
