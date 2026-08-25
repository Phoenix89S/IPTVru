#!/usr/bin/env python3
# coding: utf-8
"""
git_bot_for_stable.py
- читает локальные целевые файлы (gh-pages checkout)
- загружает donor-источники (SOURCE_URL и OPTIONAL SECOND_SOURCE_URL)
- применяет фильтрацию только ко второму донору (если указан)
- добавляет в конец целевых файлов группу "Стабильные ТВ" только новых записей
- делает backup файлов
- если SKIP_PUSH=false -> создаёт фиксационную ветку от gh-pages, коммитит и пушит её
- если SKIP_PUSH=true  -> не пушит и не создаёт ветку, оставляет изменения в рабочем дереве для workflow
"""

import os
import re
import subprocess
import urllib.request
import time
import shutil
import sys

# ---------- Конфигурация ----------
# Донорские raw-URL (первый обычно не фильтруем, второй — донор, к нему применяется фильтр)
SOURCE_URL = "https://raw.githubusercontent.com/Phoenix89S/IpTV_playlist_2026Ru/main/ngenix_found_1.m3u"
SECOND_SOURCE_URL = ""  # <-- сюда вставьте URL второго источника-донора (raw.githubusercontent.com/...)

# allow overriding via env (useful for workflow inputs)
SECOND_SOURCE_URL = os.environ.get("SECOND_SOURCE_URL", SECOND_SOURCE_URL)
# если SKIP_PUSH = true — скрипт НЕ будет создавать ветку/коммитить/push — workflow сделает push
SKIP_PUSH = os.environ.get("SKIP_PUSH", "true").lower() in ("1", "true", "yes")
# целевая ветка для пуша из workflow (по умолчанию gh-pages-2)
TARGET_PUSH_BRANCH = os.environ.get("TARGET_PUSH_BRANCH", "gh-pages-2")

# Применять фильтрацию blacklist/has_digit_index только ко второму источнику
FILTER_SECOND_SOURCE = True

# Локальные целевые файлы (в вашем локальном gh-pages-клоне)
TARGET_MIR = "IPTVmir.m3u8"
TARGET_STABLE = "legacy/IPTVstable.m3u8"

# Резервные raw-фоллбеки (необязательно; если локального файла нет — можно подгрузить с gh-pages raw)
TARGET_MIR_RAW = "https://raw.githubusercontent.com/Phoenix89S/IPTVru/gh-pages/IPTVmir.m3u8"
TARGET_STABLE_RAW = "https://raw.githubusercontent.com/Phoenix89S/IPTVru/gh-pages/legacy/IPTVstable.m3u8"

# Чёрный список каналов (Safe Edition)
BLACKLIST = {
    "365 дней", "europa plus tv", "fashion tv", "gulli girl", "hdl", "khl", "khl prime",
    "mma-tv.com", "women’s magazine", "авто плюс", "бокс тв", "big planet", "barely legal",
    "blue hustler", "в гостях у сказки", "дорама", "живи!", "звезда плюс", "индия",
    "индийское кино", "кино living", "киномикс", "кинопремьера", "киносемья", "киносвидание",
    "киноужас", "кинохит", "квн тв", "кухня тв", "кто есть кто", "ля-минор", "матч! арена",
    "матч! боец", "матч! игра", "матч! планета", "матч! премьер", "матч! страна", "матч! футбол",
    "мужское кино", "наше новое кино", "ностальгия", "родное кино", "saga", "супергерои",
    "playboy", "erox"
}

# ---------- Утилиты ----------
def run(cmd, cwd=None, check=True):
    try:
        res = subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)
        return res
    except subprocess.CalledProcessError as e:
        print(f"Команда {' '.join(cmd)} завершилась с ошибкой: {e}\nstderr:\n{e.stderr}")
        raise

def git_is_clean():
    res = run(["git", "status", "--porcelain"], check=True)
    return res.stdout.strip() == ""

def ensure_on_branch(branch="gh-pages"):
    run(["git", "fetch", "origin"], check=True)
    run(["git", "checkout", branch], check=True)
    run(["git", "pull", "origin", branch], check=True)

def create_branch_from(branch_from="gh-pages", new_branch=None):
    if not new_branch:
        new_branch = f"fix/restore-playlists-{time.strftime('%Y%m%d_%H%M%S')}"
    ensure_on_branch(branch_from)
    run(["git", "checkout", "-b", new_branch], check=True)
    return new_branch

def push_branch(branch):
    run(["git", "push", "-u", "origin", branch], check=True)

def fetch_url(url, timeout=15):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Ошибка загрузки {url}: {e}")
        return ""

# ---------- Парсинг M3U ----------
def parse_m3u_content(content):
    lines = content.splitlines()
    entries = []
    current_meta = None
    tvg_re = re.compile(r'tvg-id="([^"]+)"', re.IGNORECASE)
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#EXTINF:"):
            current_meta = s
        elif not s.startswith("#"):
            url = s
            if current_meta:
                parts = current_meta.split(",", 1)
                name = parts[1].strip() if len(parts) > 1 else ""
                m = tvg_re.search(current_meta)
                key = m.group(1) if m else url
                entries.append({'extinf': current_meta, 'url': url, 'key': key, 'name': name})
                current_meta = None
            else:
                # URL without meta
                entries.append({'extinf': '', 'url': url, 'key': url, 'name': ''})
    return entries

def read_local_or_raw(path, raw_fallback=None):
    # Читаем локально, если есть
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    # иначе пробуем raw fallback (если передан). Если raw пустой — возвращаем пустую строку (и не создаём файл)
    if raw_fallback:
        print(f"Локальный файл {path} не найден — пробуем raw {raw_fallback}")
        return fetch_url(raw_fallback)
    return ""

def is_blacklisted(title):
    t = (title or "").strip().lower()
    for bad in BLACKLIST:
        if bad in t:
            return True
    return False

def has_digit_index_in_path(url):
    return bool(re.search(r'/\d+/', url))

def collect_existing_keys(path, raw_fallback=None):
    content = read_local_or_raw(path, raw_fallback=raw_fallback)
    if not content:
        return set()
    entries = parse_m3u_content(content)
    keys = set()
    for e in entries:
        if e.get('key'):
            keys.add(e['key'])
        if e.get('url'):
            keys.add(e['url'])
    return keys

def ensure_group_title_in_extinf(extinf, group_title):
    if not extinf:
        return f'#EXTINF:-1 group-title="{group_title}",'
    if 'group-title=' in extinf:
        return re.sub(r'group-title="[^"]*"', f'group-title="{group_title}"', extinf)
    if ',' in extinf:
        meta, name = extinf.split(',', 1)
        return f'{meta} group-title="{group_title}",{name}'
    return f'{extinf} group-title="{group_title}",'

def backup_file(path):
    if os.path.exists(path):
        ts = time.strftime('%Y%m%d_%H%M%S')
        bak = f"{path}.bak_{ts}"
        shutil.copy2(path, bak)
        print(f"Создан backup: {bak}")

def append_group_if_new(target_path, donor_entries, group_title="Стабильные ТВ", raw_fallback=None):
    # Возвращает количество добавленных записей (0 — если ничего не добавлено)
    # Не создаём файл, если donor_entries пустой
    if not donor_entries:
        return 0

    existing_keys = collect_existing_keys(target_path, raw_fallback=raw_fallback)
    to_append = []
    for e in donor_entries:
        key = e.get('key') or e.get('url') or e.get('extinf')
        url = e.get('url') or ""
        if key in existing_keys or url in existing_keys:
            continue
        extinf_with_group = ensure_group_title_in_extinf(e.get('extinf'), group_title)
        to_append.append((extinf_with_group, url))
        existing_keys.add(key)
        existing_keys.add(url)

    if not to_append:
        return 0

    # backup
    backup_file(target_path)

    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    with open(target_path, "a", encoding="utf-8") as f:
        f.write("\n")
        f.write(f"# ===== {group_title} (added {time.strftime('%Y-%m-%d %H:%M:%S')}) =====\n")
        for extinf, url in to_append:
            f.write(extinf.rstrip() + "\n")
            f.write(url.rstrip() + "\n")

    return len(to_append)

# ---------- Основной поток ----------
def main():
    # Проверки git-окружения
    if not shutil.which("git"):
        print("Git не найден в PATH. Установите git и повторите.")
        sys.exit(1)

    if not git_is_clean():
        print("Рабочее дерево git не чистое. Очистите/закоммитьте изменения или запустите скрипт в отдельной копии.")
        sys.exit(1)

    # branch_name подготовим заранее — используем только если SKIP_PUSH == False
    branch_name = f"fix/restore-playlists-{time.strftime('%Y%m%d_%H%M%S')}"

    if not SKIP_PUSH:
        print("Создаём ветку:", branch_name)
        try:
            new_branch = create_branch_from("gh-pages", branch_name)
        except Exception as e:
            print("Не удалось создать ветку: ", e)
            sys.exit(1)
    else:
        print("SKIP_PUSH=true — не создаём ветку в скрипте, только модифицируем файлы в рабочем каталоге.")

    # Собираем записи из доноров
    donor_entries = []

    # Первый источник — без фильтрации
    if SOURCE_URL:
        raw1 = fetch_url(SOURCE_URL)
        if raw1:
            ents1 = parse_m3u_content(raw1)
            # пометим источник (опционально)
            for e in ents1:
                e['source'] = 'SOURCE_URL'
            print(f"Из SOURCE_URL: найдено {len(ents1)} записей (без фильтра).")
            donor_entries.extend(ents1)
        else:
            print("SOURCE_URL пустой или недоступен — пропускаем.")

    # Второй источник — фильтруем, если указан
    if SECOND_SOURCE_URL:
        raw2 = fetch_url(SECOND_SOURCE_URL)
        if raw2:
            ents2 = parse_m3u_content(raw2)
            filtered = []
            for e in ents2:
                name = e.get('name') or ""
                url = e.get('url') or ""
                if FILTER_SECOND_SOURCE:
                    if is_blacklisted(name):
                        continue
                    if has_digit_index_in_path(url):
                        continue
                e['source'] = 'SECOND_SOURCE_URL'
                filtered.append(e)
            print(f"Из SECOND_SOURCE_URL (после фильтрации): {len(filtered)} записей.")
            donor_entries.extend(filtered)
        else:
            print("SECOND_SOURCE_URL пустой или недоступен — пропускаем.")

    if not donor_entries:
        print("Нет донорских записей — изменений не будет.")
        if not SKIP_PUSH:
            print(f"Ветка создана: {branch_name} (без изменений).")
        sys.exit(0)

    # Добавляем в целевые файлы
    modified = []
    added_total = 0

    # Для TARGET_MIR читаем локально, fallback на raw если локального нет
    added = append_group_if_new(TARGET_MIR, donor_entries, group_title="Стабильные ТВ", raw_fallback=TARGET_MIR_RAW)
    if added:
        print(f"В {TARGET_MIR} добавлено: {added}")
        modified.append(TARGET_MIR)
        added_total += added
    else:
        print(f"В {TARGET_MIR} нет новых записей для добавления.")

    # Для TARGET_STABLE
    added = append_group_if_new(TARGET_STABLE, donor_entries, group_title="Стабильные ТВ", raw_fallback=TARGET_STABLE_RAW)
    if added:
        print(f"В {TARGET_STABLE} добавлено: {added}")
        modified.append(TARGET_STABLE)
        added_total += added
    else:
        print(f"В {TARGET_STABLE} нет новых записей для добавления.")

    if not modified:
        print("Новых записей не было добавлено ни в один файл.")
        if not SKIP_PUSH:
            # если мы создавали ветку в скрипте, откатим её — ничего не коммитим
            try:
                run(["git", "checkout", "gh-pages"], check=True)
                run(["git", "branch", "-D", branch_name], check=True)
                print(f"Пустая ветка {branch_name} удалена.")
            except Exception as e:
                print("Ошибка при удалении пустой ветки:", e)
        else:
            print("SKIP_PUSH=true — оставляем рабочее дерево без коммита для workflow.")
        sys.exit(0)

    # Если SKIP_PUSH == True — не делаем коммит/пуш в скрипте, workflow это выполнит
    if SKIP_PUSH:
        print("SKIP_PUSH=true — изменения внесены в рабочем дереве, но не закоммичены/запушены.")
        print(f"Добавлено всего: {added_total} записей. Файлы готовы для commit/push в ветку {TARGET_PUSH_BRANCH} через workflow.")
        # Печатаем modified для логов
        print("Modified files:", modified)
        sys.exit(0)

    # Иначе — закоммитить и запушить фиксационную ветку (скрипт сам создавал ветку ранее)
    try:
        run(["git", "add"] + modified, check=True)
        commit_msg = f"chore: append 'Стабильные ТВ' from donors ({time.strftime('%Y-%m-%d %H:%M:%S')})"
        run(["git", "commit", "-m", commit_msg], check=True)
        push_branch(branch_name)
    except Exception as e:
        print("Ошибка при коммите/пуше:", e)
        sys.exit(1)

    print(f"Готово. Добавлено всего: {added_total} записей.")
    print(f"Изменения закоммичены и запушены в ветку: {branch_name}")
    print(f"URL ветки: https://github.com/<OWNER>/<REPO>/tree/{branch_name}  (замените OWNER/REPO на ваш репо)")

if __name__ == "__main__":
    main()