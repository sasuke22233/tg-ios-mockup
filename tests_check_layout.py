"""Автопроверка вёрстки: текст не должен накладываться сам на себя и на реакции."""
from tg_mock.config import Config, Reaction
from tg_mock.render import Renderer
from tg_mock.fonts import FontBook

FONTS = FontBook()
OK = True

def check(name, cfg, base_dir="."):
    global OK
    r = Renderer(cfg, FONTS, base_dir)
    r.render()
    boxes = r.boxes
    texts = [(lbl, b) for lbl, b in boxes if lbl.startswith("text")]
    chips = [b for _, b in boxes if _ == "chip"]
    meta = [b for _, b in boxes if _ == "meta"]
    bubble = [b for _, b in boxes if _ == "bubble"][0]
    problems = []
    # соседние строки текста не пересекаются
    for i in range(len(texts) - 1):
        a, b = texts[i][1], texts[i + 1][1]
        if b[1] < a[3] - 0.5:
            problems.append(f"строки {i} и {i+1} перекрываются на {a[3]-b[1]:.1f}px")
    # текст не залезает на реакции
    for lbl, t in texts:
        for c in chips:
            if t[3] > c[1] + 0.5 and t[1] < c[3] - 0.5 and t[2] > c[0] and t[0] < c[2]:
                problems.append(f"{lbl} пересекается с реакцией")
    for c in chips:
        if c[3] > bubble[3] + 0.5:
            problems.append(f"реакция ниже пузыря на {c[3]-bubble[3]:.1f}px")
    for m in meta:
        if m[3] > bubble[3] + 0.5 or m[0] < bubble[0] - 0.5:
            problems.append("строка времени выходит за пределы пузыря")
        for c in chips:
            if m[1] < c[3] - 0.5 and m[3] > c[1] + 0.5 and m[0] < c[2] - 0.5 and m[2] > c[0] + 0.5:
                problems.append("время накладывается на реакцию")
    status = "OK " if not problems else "FAIL"
    if problems:
        OK = False
    print(f"[{status}] {name}: строк={len(texts)} реакций={len(chips)} " + ("; ".join(problems) if problems else ""))

base = Config()
check("по умолчанию", base)

c = Config(); c.post.text = "Абзац 1\n\nАбзац 2 — длинный текст, который точно должен переноситься по ширине пузыря и не наезжать на соседние строки\n\nФинальная строка 🔥"
check("три абзаца", c)

c = Config(); c.post.text = "Оченьдлинноесловобезпробеловкотороепридётсярезатьпосимвольно " * 2
check("длинное слово", c)

c = Config(); c.post.reactions = [Reaction(e, i * 111, i == 0) for i, e in enumerate(
    ["🔥", "❤️", "👍", "🎉", "😂", "🤩", "💯", "👏", "🙏", "⭐"])]
check("10 реакций", c)

c = Config(); c.post.text = "Короткий пост"
check("короткий пост", c)

c = Config(); c.post.text = "Пост без реакций, но с длинным текстом " * 6
c.post.reactions = []
check("без реакций", c)

c = Config(); c.post.media = "assets/example_media.jpg"
c.post.text = "Подпись к фото\n\nВторой абзац подписи с эмодзи 🚀 и ссылкой t.me/telegram"
check("фото + подпись", c)

c = Config(); c.post.text_size = 22; c.post.line_spacing = 6
check("крупный текст", c)

c = Config(); c.screen.theme = "light"; c.post.text_size = 15
c.post.text = "Светлая тема\n\nМногострочный текст для проверки интервалов " * 3
check("светлая тема", c)

c = Config(); c.post.buttons = ["Кнопка 1", "Кнопка 2"]
check("с кнопками", c)

c = Config(); c.post.text = ""; c.post.media = "assets/example_media.jpg"
check("только фото", c)


c = Config(); c.post.max_width = 200
check("узкий пузырь (200pt)", c)

c = Config(); c.post.views = 0; c.post.show_views = False; c.post.reactions = []
check("без просмотров и реакций", c)

c = Config(); c.bottom.type = "input"; c.screen.theme = "light"
check("светлая + поле ввода", c)

c = Config(); c.screen.device = "iphone_13"; c.screen.scale = 3
check("iPhone 13", c)

c = Config(); c.post.text = "Строка\n" * 25
check("25 строк (обрезается низом экрана)", c)

print("\nИТОГ:", "все проверки пройдены" if OK else "ЕСТЬ ПРОБЛЕМЫ")
