import os
import re
import subprocess
import urllib.request

# Источник и целевые файлы в репозитории
SOURCE_URL = "https://raw.githubusercontent.com/Phoenix89S/IpTV_playlist_2026Ru/main/ngenix_found_1.m3u"
TARGET_MIR = "IPTVmir.m3u8"
TARGET_STABLE = "legacy/IPTVstable.m3u8"

# Чёрный список каналов (технический / Safe Edition)
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

def is_blacklisted(title):
    title_clean = title.strip().lower()
    for bad in BLACKLIST:
        if bad in title_clean:
            return True
    return False

def has_digit_index_in_path(url):
    # Проверяем наличие паттернов вроде /1/, /2/, /123/ в путях URL
    return bool(re.search(r'/\d+/', url))

def git_commit_and_push():
    commit_message = (
        "feat: добавлены стабильные потоки из открытых и новооткрытых источников\n\n"
        "- добавлен файл IPTVstable.m3u8 в каталог /legacy\n"
        "- зафиксирован стабильный результат поиска\n"
        "- Никаких 18+ каналов не дадим(!) забота о детях"
    )
    
    try:
        print("Выполняем git add...")
        subprocess.run(["git", "add", TARGET_MIR, TARGET_STABLE], check=True)
        
        # Проверяем, есть ли изменения для коммита
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        if not status.stdout.strip():
            print("Нет изменений для коммита.")
            return

        print("Выполняем git commit...")
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        
        print("Выполняем git push...")
        subprocess.run(["git", "push"], check=True)
        print("Автокоммит и пуш успешно выполнены!")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при работе с Git: {e}")

def process_playlist():
    print("Загрузка и обработка плейлиста...")
    
    try:
        req = urllib.request.urlopen(SOURCE_URL)
        content = req.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Ошибка загрузки источника: {e}")
        return

    lines = content.splitlines()
    valid_items = []
    
    current_meta = None
    
    for line in lines:
        line_str = line.strip()
        if line_str.startswith("#EXTINF:"):
            current_meta = line_str
        elif line_str and not line_str.startswith("#"):
            url = line_str
            if current_meta:
                # Извлекаем название канала после запятой
                parts = current_meta.split(',', 1)
                channel_name = parts[1].strip() if len(parts) > 1 else "Unknown"
                
                # Проверки безопасности и фильтрации:
                # 1. Чёрный список (удаляем на лету)
                # 2. Цифровые индексы в пути (например, /1/, /2/)
                if not is_blacklisted(channel_name) and not has_digit_index_in_path(url):
                    valid_items.append((channel_name, url))
                
                current_meta = None

    # Формируем итоговый текст M3U8 со сквозной нумерацией и группой «Стабильные ТВ»
    output_lines = ["#EXTM3U"]
    
    for index, (name, url) in enumerate(valid_items, start=1):
        numbered_name = f"{index}. {name}"
        extinf = f"#EXTINF:-1 tvg-chno=\"{index}\" group-title=\"Стабильные ТВ\",{numbered_name}"
        output_lines.append(extinf)
        output_lines.append(url)

    final_content = "\n".join(output_lines) + "\n"

    # Убедимся, что каталог legacy существует
    os.makedirs(os.path.dirname(TARGET_STABLE), exist_ok=True)

    # Записываем в оба целевых файла
    with open(TARGET_MIR, "w", encoding="utf-8") as f:
        f.write(final_content)
        
    with open(TARGET_STABLE, "w", encoding="utf-8") as f:
        f.write(final_content)

    print(f"Успешно обработано! Добавлено каналов (с учетом фильтров): {len(valid_items)}")
    
    # Автоматически отправляем изменения в репозиторий
    git_commit_and_push()

if __name__ == "__main__":
    process_playlist()
