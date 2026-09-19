"""Convert `:shortcode:` text (as found in some Jellyfin titles/overviews)
into the emoji character itself. Pure Python, no dependencies."""

import re

_SHORTCODE_RE = re.compile(r":([a-z0-9_+\-]+):")

EMOJI: dict[str, str] = {
    "smile": "😄", "smiley": "😃", "grinning": "😀", "grin": "😁", "laughing": "😆",
    "joy": "😂", "rofl": "🤣", "sweat_smile": "😅", "wink": "😉", "blush": "😊",
    "innocent": "😇", "slightly_smiling_face": "🙂", "upside_down_face": "🙃",
    "heart_eyes": "😍", "kissing_heart": "😘", "yum": "😋", "stuck_out_tongue": "😛",
    "stuck_out_tongue_winking_eye": "😜", "sunglasses": "😎", "nerd_face": "🤓",
    "thinking": "🤔", "neutral_face": "😐", "expressionless": "😑", "unamused": "😒",
    "roll_eyes": "🙄", "smirk": "😏", "relieved": "😌", "pensive": "😔", "sleepy": "😪",
    "sleeping": "😴", "worried": "😟", "confused": "😕", "frowning": "😦",
    "disappointed": "😞", "cry": "😢", "sob": "😭", "scream": "😱", "fearful": "😨",
    "cold_sweat": "😰", "angry": "😠", "rage": "😡", "triumph": "😤", "mask": "😷",
    "skull": "💀", "ghost": "👻", "alien": "👽", "robot": "🤖", "poop": "💩",
    "clown_face": "🤡", "see_no_evil": "🙈", "hear_no_evil": "🙉", "speak_no_evil": "🙊",
    "+1": "👍", "thumbsup": "👍", "-1": "👎", "thumbsdown": "👎", "clap": "👏",
    "wave": "👋", "ok_hand": "👌", "v": "✌️", "muscle": "💪", "pray": "🙏",
    "point_up": "☝️", "point_down": "👇", "point_left": "👈", "point_right": "👉",
    "raised_hands": "🙌", "handshake": "🤝", "fist": "✊", "eyes": "👀", "brain": "🧠",
    "heart": "❤️", "broken_heart": "💔", "blue_heart": "💙", "green_heart": "💚",
    "yellow_heart": "💛", "purple_heart": "💜", "black_heart": "🖤", "sparkling_heart": "💖",
    "star": "⭐", "star2": "🌟", "sparkles": "✨", "zap": "⚡", "fire": "🔥",
    "boom": "💥", "collision": "💥", "sun": "☀️", "sunny": "☀️", "cloud": "☁️",
    "rain_cloud": "🌧️", "snowflake": "❄️", "rainbow": "🌈", "umbrella": "☔",
    "moon": "🌙", "earth_africa": "🌍", "earth_americas": "🌎", "earth_asia": "🌏",
    "ocean": "🌊", "tada": "🎉", "confetti_ball": "🎊", "balloon": "🎈", "gift": "🎁",
    "trophy": "🏆", "medal": "🏅", "crown": "👑", "gem": "💎", "moneybag": "💰",
    "dollar": "💵", "100": "💯", "warning": "⚠️", "no_entry": "⛔", "x": "❌",
    "white_check_mark": "✅", "heavy_check_mark": "✔️", "question": "❓",
    "exclamation": "❗", "bangbang": "‼️", "recycle": "♻️", "lock": "🔒", "key": "🔑",
    "bell": "🔔", "bulb": "💡", "book": "📖", "books": "📚", "memo": "📝",
    "pencil": "✏️", "email": "📧", "phone": "📱", "computer": "💻", "tv": "📺",
    "camera": "📷", "movie_camera": "🎥", "clapper": "🎬", "film_projector": "📽️",
    "film_strip": "🎞️", "popcorn": "🍿", "microphone": "🎤", "headphones": "🎧",
    "musical_note": "🎵", "notes": "🎶", "guitar": "🎸", "violin": "🎻",
    "trumpet": "🎺", "drum": "🥁", "video_game": "🎮", "game_die": "🎲",
    "dart": "🎯", "art": "🎨", "cinema": "🎦", "hourglass": "⌛", "watch": "⌚",
    "alarm_clock": "⏰", "rocket": "🚀", "airplane": "✈️", "car": "🚗",
    "taxi": "🚕", "bus": "🚌", "train": "🚆", "bike": "🚲", "ship": "🚢",
    "anchor": "⚓", "house": "🏠", "school": "🏫", "hospital": "🏥", "castle": "🏰",
    "dog": "🐶", "cat": "🐱", "mouse": "🐭", "rabbit": "🐰", "fox_face": "🦊",
    "bear": "🐻", "panda_face": "🐼", "koala": "🐨", "tiger": "🐯", "lion": "🦁",
    "cow": "🐮", "pig": "🐷", "frog": "🐸", "monkey_face": "🐵", "chicken": "🐔",
    "penguin": "🐧", "bird": "🐦", "eagle": "🦅", "owl": "🦉", "bat": "🦇",
    "wolf": "🐺", "unicorn": "🦄", "bee": "🐝", "bug": "🐛", "butterfly": "🦋",
    "snake": "🐍", "turtle": "🐢", "octopus": "🐙", "fish": "🐟", "whale": "🐳",
    "dolphin": "🐬", "shark": "🦈", "dragon": "🐉", "t_rex": "🦖", "spider": "🕷️",
    "tree": "🌳", "evergreen_tree": "🌲", "palm_tree": "🌴", "cactus": "🌵",
    "rose": "🌹", "sunflower": "🌻", "tulip": "🌷", "four_leaf_clover": "🍀",
    "apple": "🍎", "banana": "🍌", "cherries": "🍒", "strawberry": "🍓",
    "pizza": "🍕", "hamburger": "🍔", "fries": "🍟", "hotdog": "🌭", "taco": "🌮",
    "cake": "🍰", "cookie": "🍪", "doughnut": "🍩", "coffee": "☕", "tea": "🍵",
    "beer": "🍺", "beers": "🍻", "wine_glass": "🍷", "cocktail": "🍸",
    "champagne": "🍾", "soccer": "⚽", "basketball": "🏀", "football": "🏈",
    "baseball": "⚾", "tennis": "🎾", "bow_and_arrow": "🏹", "crossed_swords": "⚔️",
    "dagger": "🗡️", "gun": "🔫", "bomb": "💣", "shield": "🛡️", "syringe": "💉",
    "pill": "💊", "microscope": "🔬", "telescope": "🔭", "satellite": "📡",
    "detective": "🕵️", "ninja": "🥷", "santa": "🎅", "angel": "👼", "princess": "👸",
    "zombie": "🧟", "vampire": "🧛", "mage": "🧙", "fairy": "🧚", "genie": "🧞",
    "mermaid": "🧜", "superhero": "🦸", "supervillain": "🦹", "jack_o_lantern": "🎃",
    "christmas_tree": "🎄", "flag_white": "🏳️", "checkered_flag": "🏁",
    "arrow_right": "➡️", "arrow_left": "⬅️", "arrow_up": "⬆️", "arrow_down": "⬇️",
    "play": "▶️", "pause": "⏸️", "stop": "⏹️", "fast_forward": "⏩", "rewind": "⏪",
    "repeat": "🔁", "shuffle": "🔀", "copyright": "©️", "registered": "®️",
    "tm": "™️", "infinity": "♾️", "peace": "☮️", "yin_yang": "☯️",
}


def replace_shortcodes(text: str) -> str:
    """Replace known `:name:` shortcodes in `text` with emoji; unknown
    shortcodes (and any other text, e.g. `12:30:45`) are left untouched."""
    if not text or ":" not in text:
        return text
    return _SHORTCODE_RE.sub(lambda m: EMOJI.get(m.group(1), m.group(0)), text)
