"""Claude x SolidWorks Pro: activate a key on this PC, check the subscription, connect the Pro tools.

    python pro_license.py activate SWP-XXXX-XXXX-XXXX-XXXX
    python pro_license.py status            # online check, falls back to the cached offline token
    python pro_license.py deactivate        # frees this PC's slot (a key works on 2 PCs)

Stdlib only. Stores the key in %APPDATA%\\claude-solidworks\\pro.json (or ~/.config/claude-solidworks).
Activation registers the Pro MCP server with Claude Code (`claude mcp add ... swpro`), so the Pro tools
appear in Claude's tool list. They run on the Pro server and stop working when the subscription ends.
"""
from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SERVER = os.environ.get("SWPRO_URL", "https://swpro.REPLACE-AFTER-DEPLOY.workers.dev").rstrip("/")
PLANS_URL = "https://github.com/YanirBarHazan/claude-solidworks-pro/blob/main/PLANS.md"


def _config_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "claude-solidworks" / "pro.json"


def load() -> dict:
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(cfg: dict) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def device_id(cfg: dict) -> str:
    if not cfg.get("device_id"):
        cfg["device_id"] = str(uuid.uuid4())
    return cfg["device_id"]


def _post(path: str, body: dict, timeout: float = 10) -> tuple[int, dict]:
    req = urllib.request.Request(SERVER + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": f"http_{e.code}"}


def _token_payload(token: str | None) -> dict | None:
    """Reads the offline token's payload (expiry). The server signs it; this side only reads the date."""
    try:
        body = token.split(".")[0]
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None


def check(cfg: dict | None = None) -> dict:
    """Current Pro state for this PC: {'pro': bool, 'state': ..., 'source': 'online'|'offline'|'none'}."""
    cfg = cfg if cfg is not None else load()
    if not cfg.get("key"):
        return {"pro": False, "state": "no_key", "source": "none", "upgrade_url": PLANS_URL}
    try:
        status, r = _post("/v1/check", {"key": cfg["key"], "device_id": device_id(cfg), "device_name": platform.node()})
    except (urllib.error.URLError, OSError):
        payload = _token_payload(cfg.get("token"))
        ok = bool(payload and payload.get("exp", 0) / 1000 > time.time())
        return {"pro": ok, "state": "offline" if ok else "offline_expired", "source": "offline",
                "valid_until": time.strftime("%Y-%m-%d", time.localtime(payload["exp"] / 1000)) if payload else None}
    r.setdefault("pro", False)
    r["source"] = "online"
    if r.get("token"):
        cfg["token"] = r["token"]
    cfg["last_state"] = r.get("state") or r.get("error")
    save(cfg)
    return r


def _register_mcp(cfg: dict) -> str:
    args = ["mcp", "add", "--transport", "http", "--scope", "user", "swpro", SERVER + "/mcp",
            "--header", f"Authorization: Bearer {cfg['key']}", "--header", f"X-Device-Id: {device_id(cfg)}"]
    claude = shutil.which("claude")
    if not claude:
        return "Claude Code not found on PATH. Run this once it is installed:\n  claude " + " ".join(
            f'"{a}"' if " " in a else a for a in args)
    subprocess.run([claude, "mcp", "remove", "--scope", "user", "swpro"], capture_output=True)
    done = subprocess.run([claude, *args], capture_output=True, text=True)
    return "Pro tools connected to Claude Code (restart Claude to load them)." if done.returncode == 0 else done.stderr.strip()


def activate(key: str) -> int:
    cfg = load()
    cfg["key"] = key.strip().upper()
    r = check(cfg)
    if not r.get("ok"):
        msg = {"invalid_key": "Key not recognised. Check it, or contact support.",
               "device_limit": f"This key is already active on {r.get('max_devices', 2)} PCs. Run 'deactivate' on one of them first."}
        print(msg.get(r.get("error"), f"Activation failed: {r.get('error') or r.get('state')}"))
        if r.get("error") == "invalid_key":
            cfg.pop("key", None)
            save(cfg)
        return 1
    save(cfg)
    print(f"Activated: {r.get('plan', 'pro').title()}, state {r['state']}, paid until {str(r.get('paid_until', ''))[:10]}.")
    print(_register_mcp(cfg))
    return 0


def deactivate() -> int:
    cfg = load()
    if cfg.get("key"):
        try:
            _post("/v1/release", {"key": cfg["key"], "device_id": device_id(cfg)})
        except (urllib.error.URLError, OSError):
            print("Server not reachable; removed locally only.")
    claude = shutil.which("claude")
    if claude:
        subprocess.run([claude, "mcp", "remove", "--scope", "user", "swpro"], capture_output=True)
    for k in ("key", "token", "last_state"):
        cfg.pop(k, None)
    save(cfg)
    print("Pro removed from this PC.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "activate":
        return activate(argv[1])
    if argv[:1] == ["deactivate"]:
        return deactivate()
    if argv[:1] in (["status"], []):
        r = check()
        if r["pro"]:
            extra = f", grace until {r['grace_until'][:10]} - renew to keep Pro" if r.get("state") == "grace" else ""
            print(f"Pro: active ({r.get('state')}, {r['source']}{extra}).")
        else:
            print(f"Pro: not active ({r.get('state') or r.get('error')}). Plans: {PLANS_URL}")
        return 0 if r["pro"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
