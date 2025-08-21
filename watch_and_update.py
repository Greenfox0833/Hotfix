import argparse
import hashlib
import os
import re
import subprocess
import sys
import time
import yaml
from typing import Dict, List, Optional, Tuple

LINE_RE = re.compile(
    r"""^[+\-]?DataTable=(?P<table_path>[^;]+);(?P<op>[^;]+);(?P<row>[^;]+)(?:;(?P<rest>.*))?$""",
    re.UNICODE,
)

def load_cfg(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def run_cmd(cmd: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return 1, "", f"Failed to run {cmd}: {e}"

def file_hash(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def table_basename(table_path: str) -> str:
    base = os.path.basename(table_path)
    base = os.path.splitext(base)[0]
    return base

def parse_hotfix(text: str) -> List[dict]:
    events = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        m = LINE_RE.match(raw)
        if not m:
            continue
        d = m.groupdict()
        events.append({
            "table": table_basename(d["table_path"]),
            "op": d["op"],
            "row": d["row"],
            "rest": d.get("rest") or "",
            "raw": raw,
        })
    return events

def match_table(name: str, matcher: dict) -> bool:
    method = matcher.get("method", "exact")
    targets = matcher.get("tables", [])
    if method == "exact":
        return name in targets
    elif method == "regex":
        return any(re.search(pat, name) for pat in targets)
    elif method == "prefix":
        return any(name.startswith(p) for p in targets)
    elif method == "suffix":
        return any(name.endswith(s) for s in targets)
    else:
        return False

def filter_events(events: List[dict], matcher: dict, ops: List[str]) -> List[dict]:
    out = []
    for e in events:
        if e["op"] not in ops:
            continue
        if match_table(e["table"], matcher):
            out.append(e)
    return out

def one_cycle(cfg: dict, last_hash: Optional[str], only_tables: Optional[set] = None) -> Optional[str]:
    # 1) 取得
    fetch_cmd = cfg.get("hotfix", {}).get("fetch_cmd")
    if fetch_cmd:
        rc, out, err = run_cmd(fetch_cmd)
        if rc != 0:
            print(f"[WARN] fetch_cmd failed (rc={rc}): {err}", flush=True)

    hotfix_file = cfg["hotfix"]["file"]
    h = file_hash(hotfix_file)
    if h is None:
        print(f"[WARN] Hotfix file not found: {hotfix_file}", flush=True)
        return last_hash

    if cfg["hotfix"].get("skip_same_hash", True) and h == last_hash:
        print("[INFO] No change (hash same).", flush=True)
        return last_hash


    # 2) 解析
    with open(hotfix_file, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    events = parse_hotfix(text)

    if only_tables:
        events = [e for e in events if e["table"] in only_tables]

    # 3) グループごとに判定
    groups = cfg.get("groups", [])
    to_run = []  # [(group_name, cmd)]
    fired_groups = set()

    for g in groups:
        name = g["name"]
        matched = filter_events(events, g["match"], g["ops"])
        if matched:
            if name not in fired_groups:
                to_run.append((name, g["cmd"]))
                fired_groups.add(name)

    # 4) 交差トリガー
    for ct in cfg.get("cross_triggers", []):
        src_matched = filter_events(events, ct["source"], ct["source"]["ops"] if "ops" in ct["source"] else ct.get("ops", []))
        # ↑ source の ops は source 内に書いてあるケース/外だと ct["ops"] の両対応
        if src_matched:
            tgt = ct["target_group"]
            if tgt not in fired_groups:
                # 対象グループの cmd を引く
                gdef = next((g for g in groups if g["name"] == tgt), None)
                if gdef:
                    to_run.append((tgt, gdef["cmd"]))
                    fired_groups.add(tgt)

    # 5) 実行
    if not to_run:
        print("[INFO] No trigger.", flush=True)
        return h

    for (name, cmd) in to_run:
        print(f"[TRIGGER] {name} -> {' '.join(cmd)}", flush=True)
        rc, out, err = run_cmd(cmd)
        print(f"[RUN] rc={rc}", flush=True)
        if out:
            print(out, flush=True)
        if err:
            print(err, flush=True)

    # 6) ハッシュ更新
    return h

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="hotfix_rules.yaml")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", type=int, default=0)
    ap.add_argument("--only-tables", default="", help="カンマ区切りのテーブル名だけ処理（例: A,B,C）")
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    last_hash = None

    # ← 追加: --only-tables をセット化（空なら None）
    only = set([s for s in (args.only_tables or "").split(",") if s.strip()]) or None

    if args.once:
        last_hash = one_cycle(cfg, last_hash, only_tables=only)  # ← 引数追加
        return

    if args.watch > 0:
        print(f"[INFO] Watching every {args.watch}s ...", flush=True)
        while True:
            last_hash = one_cycle(cfg, last_hash, only_tables=only)  # ← 引数追加
            time.sleep(args.watch)
    else:
        last_hash = one_cycle(cfg, last_hash, only_tables=only)      # ← 引数追加

if __name__ == "__main__":
    main()
