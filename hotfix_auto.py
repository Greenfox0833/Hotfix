import json, os, subprocess, sys, time, requests

PY = sys.executable

# ====== 設定 ======
HOTFIX_FETCH = [
    PY, r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/Hotfix取得.py",
    "--outdir", r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/cloudstorage_system",
    "--hotfix-out", r"e:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/Hotfix.ini",
    "--changed-tables-out", r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/changed_tables.json",
    "--message", r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/message.py",
]

WATCH_AND_UPDATE = [
    PY, r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/watch_and_update.py",
    "--config", r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/hotfix_rules.yaml",
    "--once",
]

# Discord Webhook（←自分のURLに差し替え）
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1408009764490973194/QD_Mi9Umhnsj3lrKbenSm1FKNZBoY5Rf6btZs6BzrUB6tP-zdGui373jlb0qDTskSYfI"

# Optional通知を送るかどうか（True: 送る / False: 送らない）
# ※更新(=差分あり)通知とエラー通知はこの設定に関係なく「必ず」送信します
ENABLE_OPTIONAL_NOTICES = False

# 差分あり(更新)通知に @everyone を付けるか
MENTION_EVERYONE_ON_UPDATE = True

# GitHub リポジトリ設定（New Loot をリポジトリとする）
GIT_REPO_DIR = r"E:/フォートナイト/Picture/Loot Pool/TEST4/New Loot"
GIT_INCLUDE_PATHS = ["."]
GIT_BRANCH = "main"

# ループ間隔(秒)
INTERVAL_SECONDS = 40


# ====== Discord通知ユーティリティ ======
def _post_discord(content: str, mandatory: bool = False):
    """
    mandatory=True の場合は ENABLE_OPTIONAL_NOTICES に関係なく送信（=必ず通知）。
    mandatory=False の場合は ENABLE_OPTIONAL_NOTICES が True のときだけ送信。
    """
    if not mandatory and not ENABLE_OPTIONAL_NOTICES:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    except Exception as e:
        print(f"[AUTO] Discord通知失敗: {e}", file=sys.stderr)

def notify_info(msg: str):
    _post_discord(f"ℹ️ {msg}", mandatory=False)

def notify_error(msg: str):
    _post_discord(f"❌ {msg}", mandatory=True)  # エラーは必ず

def notify_update(tables):
    head = "@everyone\n" if MENTION_EVERYONE_ON_UPDATE else ""
    body = "✅ Hotfix更新あり\n変更されたテーブル:\n" + "\n".join(f"- {t}" for t in tables)
    _post_discord(head + body, mandatory=True)  # 更新は必ず


# ====== Gitユーティリティ ======
def _run_git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, text=True, capture_output=True)

def git_has_changes(repo_dir, include_paths):
    p = _run_git(["status", "--porcelain"] + include_paths, repo_dir)
    if p.returncode != 0:
        msg = f"git status 失敗: {p.stderr.strip()}"
        print("[AUTO]", msg)
        notify_error(msg)  # gitエラーは必ず
        return False
    changed = bool(p.stdout.strip())
    if not changed:
        print("[AUTO] Git変更なし。プッシュしません。")
        notify_info("Git変更なし。プッシュしません。")  # optional
    return changed

def git_commit_and_push(repo_dir, include_paths, message):
    p = _run_git(["add"] + include_paths, repo_dir)
    if p.returncode != 0:
        msg = f"git add 失敗: {p.stderr.strip()}"
        print("[AUTO]", msg)
        notify_error(msg)  # 必ず
        return

    p = _run_git(["diff", "--cached", "--quiet"], repo_dir)
    if p.returncode == 0:
        msg = "コミット対象なし（ステージに変更なし）。"
        print("[AUTO]", msg)
        notify_info(msg)  # optional
        return

    p = _run_git(["commit", "-m", message], repo_dir)
    if p.returncode != 0:
        msg = f"git commit 失敗: {p.stderr.strip()}"
        print("[AUTO]", msg)
        notify_error(msg)  # 必ず
        return
    notify_info(f"Gitコミット完了: {message}")  # optional

    p = _run_git(["push", "origin", GIT_BRANCH], repo_dir)
    if p.returncode != 0:
        msg = f"git push 失敗: {p.stderr.strip()}"
        print("[AUTO]", msg)
        notify_error(msg)  # 必ず
        return

    print("[AUTO] GitHubへプッシュ完了。")
    notify_info("GitHubへプッシュ完了。")  # optional


# ====== メイン処理 ======
def run_once():
    notify_info("Hotfixチェック開始")  # optional

    # 1) Hotfix取得
    try:
        p = subprocess.run(HOTFIX_FETCH, text=True)
    except Exception as e:
        msg = f"Hotfix取得の起動に失敗: {e}"
        print("[AUTO]", msg)
        notify_error(msg)  # 必ず
        return

    if p.returncode == 100:
        msg = f"Hotfix差分なし。更新処理は行いません。{INTERVAL_SECONDS}秒待機中..."
        print("[AUTO]", msg)
        notify_info(msg)  # optional
        return
    if p.returncode != 0:
        msg = f"Hotfix取得失敗 rc={p.returncode}"
        print("[AUTO]", msg)
        notify_error(msg)  # 必ず
        return

    # 2) 差分テーブル読み込み
    changed_path = r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/changed_tables.json"
    if not os.path.exists(changed_path):
        msg = "changed_tables.json が見つからないためスキップ。"
        print("[AUTO]", msg)
        notify_error(msg)  # 必ず（重要ファイル欠如）
        return

    try:
        with open(changed_path, "r", encoding="utf-8") as f:
            tables = json.load(f)
    except Exception as e:
        msg = f"changed_tables.json の読み込みに失敗: {e}"
        print("[AUTO]", msg)
        notify_error(msg)  # 必ず
        return

    if not tables:
        msg = "差分テーブルなし。"
        print("[AUTO]", msg)
        notify_info(msg)  # optional
        return

    # 3) 更新通知（必ず）
    notify_update(tables)

    # 4) 更新処理（watch_and_update 実行）
    only_arg = "--only-tables=" + ",".join(tables)
    cmd = WATCH_AND_UPDATE + [only_arg]
    notify_info(f"更新処理実行: {' '.join(cmd)}")  # optional
    try:
        subprocess.run(cmd, text=True)
    except Exception as e:
        msg = f"watch_and_update 実行失敗: {e}"
        print("[AUTO]", msg)
        notify_error(msg)  # 必ず
        return

    # 5) GitHubへプッシュ（New Lootの変更を反映）
    if git_has_changes(GIT_REPO_DIR, GIT_INCLUDE_PATHS):
        git_commit_and_push(GIT_REPO_DIR, GIT_INCLUDE_PATHS, f"Hotfix更新: {', '.join(tables)}")

def main():
    while True:
        run_once()
        notify_info(f"{INTERVAL_SECONDS}秒待機中...")  # optional
        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
