import argparse
import hashlib
import os
import sys
import time
import json
import subprocess   # ← 追加
import re

import requests

class TokenError(Exception):  # ← 追加
    """401 認証エラーなど、トークン再取得が必要な状態"""
    pass


HOST = "https://fngw-mcp-gc-livefn.ol.epicgames.com"
ENDPOINT_TMPL = "/fortnite/api/cloudstorage/system/{unique}"

# ここに取得したい uniqueFilename を並べる
UNIQUE_FILENAMES = [
    "d16053edfaa74782b72283b51e7d393f",
    "a22d837b6a2b46349421259c0a5411bf",
    "56335419f8794c71ba727c8f6e935af2",
    "f60cbea9f6d24c5a855056088b15f447",
]

# Hotfix形式のトークンファイル（例）
HOTFIX_TOKEN_FILE = r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/tokens_hotfix.txt"
TOKENS_JSON_FILE  = r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/tokens.json"

def load_token_from_hotfix(path: str, prefer=("eg1account_token", "account_token")) -> str | None:
    """
    +CurveTable=/Auth/Tokens;RowUpdate;{key};{value}
    の形式から、優先順位 prefer に従って最初に見つかったトークンを返す。
    """
    if not os.path.exists(path):
        return None
    token_map = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith(";"):
                    continue
                # 期待形式: +CurveTable=/Auth/Tokens;RowUpdate;{name};{value}
                parts = s.split(";")
                if len(parts) >= 4 and parts[0].startswith("+CurveTable=/Auth/Tokens") and parts[1] == "RowUpdate":
                    key = parts[2]
                    val = ";".join(parts[3:])  # 値に ';' が含まれても拾えるように
                    token_map[key] = val
        for k in prefer:
            if k in token_map and token_map[k]:
                print(f"Hotfixトークンファイルから {k} を読み込みました")
                return token_map[k]
    except Exception as e:
        print(f"Hotfixトークン読込失敗: {e}", file=sys.stderr)
    return None


def list_system_files(token: str, timeout: int = 25):
    """CloudStorage の system バケットにあるファイル一覧を取得"""
    url = "https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/cloudstorage/system"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "CloudStorageFetcher/1.0 (+python-requests)",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    if r.status_code == 401:              # ← 追加
        raise TokenError("401 Unauthorized in list_system_files")  # ← 追加
    r.raise_for_status()
    return r.json()  # [{"uniqueFilename": "...", "filename": "...", ...}, ...]

def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def guess_ext(content_type: str) -> str:
    if not content_type:
        return ".bin"
    ct = content_type.lower()
    if "json" in ct: return ".json"
    if "xml" in ct: return ".xml"
    if "yaml" in ct or "yml" in ct: return ".yml"
    if "text" in ct: return ".txt"
    return ".bin"

def fetch_unique(token: str, unique: str, outdir: str, timeout: int = 25):
    url = HOST + ENDPOINT_TMPL.format(unique=unique)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": "CloudStorageFetcher/1.0 (+python-requests)",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code == 200:
        data = resp.content
        ct = resp.headers.get("Content-Type", "")

        def looks_like_hotfix_ini(t: str) -> bool:
            s = t.lstrip()
            if s.startswith("[/Script/"): return True
            if s.startswith("[ConsoleVariables]") or s.startswith("[AssetHotfix]"): return True
            if ("+DataTable=" in t) or ("+CurveTable=" in t) or ("+TextReplacements=" in t):
                return True
            head = s.splitlines()[:5]
            if any(line.strip().startswith(("[", "+")) for line in head): return True
            return False

        # 拡張子の推定
        try:
            text_probe = data.decode("utf-8-sig")
            if looks_like_hotfix_ini(text_probe):
                ext = ".ini"
            else:
                ext = guess_ext(ct)
        except Exception:
            text_probe = None
            ext = guess_ext(ct)

        os.makedirs(outdir, exist_ok=True)
        # 文字列化（UTF-8優先）
        text = None
        try:
            text = data.decode("utf-8-sig")
        except Exception:
            pass

        save_ext = None
        save_text = None
        json_obj = None

        if text is not None:
            # JSON判定
            try:
                json_obj = json.loads(text)
                save_ext = ".json"
            except Exception:
                json_obj = None

            # INI判定（JSONでなかった場合）
            if json_obj is None and looks_like_hotfix_ini(text):
                save_ext = ".ini"
                save_text = text

        # 保存：決定した拡張子があればそれで、なければ Content-Type から推定
        if save_ext is None:
            save_ext = guess_ext(ct)

        os.makedirs(outdir, exist_ok=True)
        outpath = os.path.join(outdir, f"{unique}{save_ext}")
        with open(outpath, "wb") as f:
            f.write(data)
        print(f"[200] {unique} -> {outpath} ({len(data)} bytes, sha256={sha256_bytes(data)[:16]}… , CT='{ct}')")

        # 追加保存が必要ならこのタイミングで（JSONは整形保存）
        if json_obj is not None:
            # 上書きでテキスト保存し直す（人間可読の整形）
            with open(outpath, "w", encoding="utf-8") as jf:
                json.dump(json_obj, jf, ensure_ascii=False, indent=2)
            return {"type": "json", "data": json_obj}

        if save_ext == ".ini" and save_text is not None:
            # さきほどバイナリで書いているのでテキスト上書き
            with open(outpath, "w", encoding="utf-8") as tf:
                tf.write(save_text)
            return {"type": "ini", "raw": save_text}

        # 生テキストだが型不明なら raw、テキスト化不可なら binary
        if text is not None:
            return {"type": "raw", "raw": text}
        return {"type": "binary", "raw": ""}

    elif resp.status_code == 404:
        print(f"[404] {unique}: 見つかりませんでした")
        return None
    elif resp.status_code == 401:
        # 401 は main 側で message 実行 → トークン再取得 → リトライさせたいので例外化
        raise TokenError(f"401 Unauthorized for {unique}")
    else:
        print(f"[{resp.status_code}] {unique}: 取得失敗 reason={resp.reason}")
        try:
            print(resp.json())
        except Exception:
            pass
        return None


def try_load_token_from_sources():
    """
    既存の取得経路（Hotfix形式 → tokens.json → 環境変数）から再読込する。
    """
    token = load_token_from_hotfix(HOTFIX_TOKEN_FILE)
    if not token and os.path.exists(TOKENS_JSON_FILE):
        try:
            with open(TOKENS_JSON_FILE, "r", encoding="utf-8") as f:
                tokens = json.load(f)
                token = (tokens.get("eg1account_token")
                        or tokens.get("account_token")
                        or tokens.get("client_token"))
                if token:
                    print("tokens.json からトークンを読み込みました")
        except Exception as e:
            print(f"tokens.json の読込に失敗: {e}", file=sys.stderr)
    if not token:
        token = os.getenv("EPIC_ACCOUNT_TOKEN")
    return token

def refresh_token_via_message(message_path: str | None) -> str | None:
    """
    message が無くても、まず保存先(HOTFIX/JSON/環境変数)からの再読込だけ試す。
    指定があれば message を実行してから再読込。
    """
    if not message_path:
        print("トークン再取得: messageファイルが指定されていません。保存先からの再読込のみ試します。")
        return try_load_token_from_sources()

    print(f"トークン再取得のため message を実行: {message_path}")
    try:
        if message_path.lower().endswith(".py"):
            subprocess.run([sys.executable, message_path], check=True)
        else:
            subprocess.run([message_path], check=True)
    except Exception as e:
        print(f"message 実行に失敗: {e}", file=sys.stderr)
        # 実行失敗でも保存先からの再読込だけは試す
        return try_load_token_from_sources()

    time.sleep(1.0)
    new_token = try_load_token_from_sources()
    if new_token:
        print("message 実行後、トークンを再読込しました")
    else:
        print("message 実行後もトークンを再読込できませんでした", file=sys.stderr)
    return new_token



def main():
    ap = argparse.ArgumentParser(description="Download Fortnite CloudStorage system files by uniqueFilename")
    ap.add_argument("--token", help="アカウントアクセストークン（Bearer にそのまま入れる）")
    ap.add_argument("--outdir", default="cloudstorage_system", help="保存先フォルダ（既定: cloudstorage_system）")
    ap.add_argument("--sleep", type=float, default=0.25, help="各リクエスト間のスリープ秒（既定: 0.25）")
    ap.add_argument("--all", action="store_true", help="system バケットの全ファイルを一覧から取得して総なめダウンロードする")
    ap.add_argument("--filter-text", default=None, help="本文にこの文字列を含むものだけを HotfixJson に集約（個別保存は従来通り）")
    ap.add_argument("--message", default=None, help="401時に実行するトークン再取得用ファイル（.exe/.bat/.py）")
    # argparse に追加
    ap.add_argument("--hotfix-out", default=r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix.ini",
                    help="Hotfixまとめiniの出力先")
    ap.add_argument("--changed-tables-out", default=None,
                    help="差分があった時、変更テーブルのリストをJSONで書き出すパス")
    args = ap.parse_args()

    DEFAULT_MESSAGE_PATH = r"E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/message.py"
    if not args.message and os.path.exists(DEFAULT_MESSAGE_PATH):
        args.message = DEFAULT_MESSAGE_PATH

    # 互換: フラグなしで「message.py / .bat / .exe」だけ渡されたら --message として解釈
    if (args.message is None and len(sys.argv) >= 2
            and sys.argv[1].lower().endswith((".py", ".bat", ".exe"))):
        args.message = sys.argv[1]

    # 1) message.py を実行して client_token を生成
    if args.message:
        try:
            if args.message.lower().endswith(".py"):
                subprocess.run([sys.executable, args.message], check=True)
            else:
                subprocess.run([args.message], check=True)
        except Exception as e:
            print(f"message 実行に失敗: {e}", file=sys.stderr)

    # 2) tokens.json から client_token を読む
    token = None
    if os.path.exists(TOKENS_JSON_FILE):
        try:
            with open(TOKENS_JSON_FILE, "r", encoding="utf-8") as f:
                tokens = json.load(f)
                token = tokens.get("client_token")
                if token:
                    print("tokens.json から client_token を読み込みました")
        except Exception as e:
            print(f"tokens.json の読込に失敗: {e}", file=sys.stderr)

    if not token:
        print("エラー: client_token が取得できませんでした", file=sys.stderr)
        sys.exit(10)

    # 3) それでも無ければ 引数/環境変数
    if not token:
        token = args.token or os.getenv("EPIC_ACCOUNT_TOKEN")

    if not token:
        print("エラー: アカウントトークンが取得できませんでした", file=sys.stderr)
        sys.exit(10)


    # 🔽 対象 unique を決定
    if args.all:
        try:
            try:
                index = list_system_files(token)
            except TokenError:
                token_new = refresh_token_via_message(args.message)
                if token_new:
                    token = token_new
                    try:
                        index = list_system_files(token)
                    except TokenError:
                        print("[401] 一覧取得: 再取得トークンでも認証失敗。処理を中止します。", file=sys.stderr)
                        sys.exit(12)
                else:
                    print("[401] 一覧取得: トークン再取得できず。処理を中止します。", file=sys.stderr)
                    sys.exit(12)
            targets = [item.get("uniqueFilename") for item in index if "uniqueFilename" in item]
            print(f"system 一覧から {len(targets)} 件を検出しました")
        except Exception as e:
            print(f"一覧取得に失敗: {e}", file=sys.stderr)
            sys.exit(11)
    else:
        targets = UNIQUE_FILENAMES  # 従来通り固定リスト

    total = 0
    ok = 0
    all_data = {}
    for unique in targets:
        total += 1
        try:
            data = fetch_unique(token, unique, args.outdir)
        except TokenError:
            token_new = refresh_token_via_message(args.message)
            if token_new:
                token = token_new
                try:
                    data = fetch_unique(token, unique, args.outdir)
                except TokenError:
                    print(f"[401] {unique}: 再取得トークンでも認証失敗。スキップします。", file=sys.stderr)
                    continue
            else:
                print(f"[401] {unique}: トークン再取得できずスキップします。", file=sys.stderr)
                continue

        # data は {"type":"json","data":...} or {"type":"ini","raw": "..."} など
        if data is not None:
            # 🔽 --filter-text が指定されている場合は本文に含むものだけ集約
            if args.filter_text:
                body_text = None
                if data.get("type") == "ini":
                    body_text = data.get("raw") or ""
                elif data.get("type") == "json":
                    try:
                        body_text = json.dumps(data.get("data", {}), ensure_ascii=False)
                    except Exception:
                        body_text = ""
                else:
                    body_text = data.get("raw") or ""
                if args.filter_text not in (body_text or ""):
                    time.sleep(args.sleep)
                    continue

            all_data[unique] = data
            ok += 1
        time.sleep(args.sleep)

    out_hotfix = args.hotfix_out
    os.makedirs(os.path.dirname(out_hotfix), exist_ok=True)

    # まとめ用ファイルは一度だけ開く（'w' で最初に作り直す）
    tmp_out = out_hotfix + ".tmp"
    with open(tmp_out, "w", encoding="utf-8") as f:
        for unique, entry in all_data.items():
            # 区切り
            f.write(f"; ===== {unique} =====\n")

            etype = entry.get("type")

            if etype == "json":
                data = entry.get("data", {})
                # ここは実ファイルの構造に応じて調整してください
                rowname = data.get("RowName", "Default.SafeZone.WaitTime")
                x = data.get("X", 0)
                y = data.get("Y", 0)
                f.write(f"+CurveTable=/{unique};RowUpdate;{rowname};{x};{y}\n")

            elif etype == "ini":
                raw = entry.get("raw", "")
                for line in raw.splitlines():
                    f.write(line + "\n")

            elif etype == "raw":
                # テキストだけど JSON/INI判定できなかったものは、そのまま追記
                raw = entry.get("raw", "")
                if raw:
                    for line in raw.splitlines():
                        f.write(line + "\n")
                else:
                    f.write("; (raw: 空テキスト)\n")

            elif etype == "binary":
                # バイナリは中身を書けないので注記のみ
                f.write("; (binary: 内容はバイナリのため省略)\n")

            else:
                # 念のためのフォールバック
                f.write("; (unknown type)\n")

            f.write("\n")  # 見やすさ用の空行


    # ここでは return しない。処理は最後まで進める。
    def sha256_file(p):
        h = hashlib.sha256()
        with open(p, "rb") as r:
            for chunk in iter(lambda: r.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # === 差分判定：旧Hotfix.iniとの比較 ===
    old_exists = os.path.exists(out_hotfix)
    if old_exists and sha256_file(tmp_out) == sha256_file(out_hotfix):
        os.remove(tmp_out)
        # 差分なしでも changed_tables_out を空配列で書いておくと後段が楽
        if args.changed_tables_out:
            with open(args.changed_tables_out, "w", encoding="utf-8") as jf:
                jf.write("[]")
        print("Hotfixに変更なし（まとめiniは前回と同一）")
        sys.exit(100)

    # 差分あり：行単位で DataTable の差分テーブル名だけ抽出
    import collections
    LINE_RE_DT = re.compile(r"^[+\-]?DataTable=([^;]+);")

    def load_lines(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return [ln.rstrip("\n") for ln in f]

    def split_dt_lines(lines):
        # table名 -> そのテーブルに属する +DataTable=... 行の集合（同一行は重複排除）
        m = collections.defaultdict(set)
        for s in lines:
            ms = LINE_RE_DT.match(s.strip())
            if ms:
                table_path = ms.group(1)  # 例: /LootCurrentSeason/DataTables/BlastBerryComposite_LP
                base = os.path.splitext(os.path.basename(table_path))[0]  # → BlastBerryComposite_LP
                m[base].add(s.strip())
        return m

    new_lines = load_lines(tmp_out)
    new_map = split_dt_lines(new_lines)

    old_map = {}
    if old_exists:
        old_lines = load_lines(out_hotfix)
        old_map = split_dt_lines(old_lines)

    # 新旧で「内容が変わった」テーブルだけを抽出
    changed_tables = sorted([
        t for t in new_map.keys()
        if new_map.get(t) != old_map.get(t, set())
    ])

    # ここで実ファイルを差し替え
    os.replace(tmp_out, out_hotfix)

    # --changed-tables-out が指定されているときだけ出力（差分テーブルのみ）
    if args.changed_tables_out:
        try:
            with open(args.changed_tables_out, "w", encoding="utf-8") as jf:
                json.dump(changed_tables, jf, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"変更テーブルの書き出しに失敗: {e}", file=sys.stderr)

    print(f"\n完了: {ok}/{total} 件 保存 (まとめ: {out_hotfix})")
    if changed_tables:
        print("差分テーブル:", ", ".join(changed_tables))
    else:
        print("差分テーブル: なし")

if __name__ == "__main__":
    main()
