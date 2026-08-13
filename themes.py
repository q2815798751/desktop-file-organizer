"""
主题模块 — 精心策展的 10 套配色主题。

设计原则（web-design-engineer 派）：
每套 = "暖/冷中性深色底 + 单一高对比强调色"，强调色 ≤ 1，
删除红为固定语义色（全主题一致），全部深色底以规避浅色俗套。
每个主题含仪表盘 / 悬浮面板 / 托盘菜单所需的全部颜色令牌。
panel_bg / panel_border 为 QColor 用 RGB 元组；accent 等为十六进制字符串。
"""
DEFAULT = "emerald"

# 全主题一致的语义危险色
_DANGER = "#f87171"
_DANGER_HOVER = "#ef4444"
_DANGER_TEXT = "#261012"

THEMES = {
    # ── 1 翡翠绿（默认）：暖锌 + 翡翠 ─────────────────────
    "emerald": {
        "label": "翡翠绿",
        "bg_main": "#17181c",
        "bg_sidebar": "#101114",
        "bg_surface": "#1e2025",
        "bg_surface_alt": "#24272d",
        "border": "#2a2d34",
        "text_primary": "#e8e6e1",
        "text_secondary": "#9ba0a9",
        "text_muted": "#6d7178",
        "accent": "#34d399",
        "accent_rgb": "52, 211, 153",
        "accent_hover": "#6ee7b7",
        "accent_text": "#0b1411",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (28, 30, 35),
        "panel_border": (42, 45, 52),
    },
    # ── 2 深海蓝：冷蓝炭 + 天青 ───────────────────────────
    "ocean": {
        "label": "深海蓝",
        "bg_main": "#10131c",
        "bg_sidebar": "#0a0d14",
        "bg_surface": "#161b27",
        "bg_surface_alt": "#1e2534",
        "border": "#283043",
        "text_primary": "#e3e8f0",
        "text_secondary": "#98a3b8",
        "text_muted": "#67718a",
        "accent": "#5b9df0",
        "accent_rgb": "91, 157, 240",
        "accent_hover": "#86b7f5",
        "accent_text": "#0a1420",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (22, 27, 39),
        "panel_border": (40, 48, 67),
    },
    # ── 3 暮夜紫：紫黑 + 薰衣草 ───────────────────────────
    "dusk": {
        "label": "暮夜紫",
        "bg_main": "#171420",
        "bg_sidebar": "#100e18",
        "bg_surface": "#1f1b2e",
        "bg_surface_alt": "#2a2440",
        "border": "#342d4d",
        "text_primary": "#eae6f5",
        "text_secondary": "#a59dc0",
        "text_muted": "#6f6890",
        "accent": "#b58cf2",
        "accent_rgb": "181, 140, 242",
        "accent_hover": "#c9aaf6",
        "accent_text": "#160f24",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (31, 27, 46),
        "panel_border": (52, 45, 77),
    },
    # ── 4 暖阳橙：暖褐 + 琥珀 ─────────────────────────────
    "sunset": {
        "label": "暖阳橙",
        "bg_main": "#191613",
        "bg_sidebar": "#100e0c",
        "bg_surface": "#201c18",
        "bg_surface_alt": "#2a241e",
        "border": "#372f27",
        "text_primary": "#f0e9e0",
        "text_secondary": "#b3a599",
        "text_muted": "#786b5e",
        "accent": "#f5a64a",
        "accent_rgb": "245, 166, 74",
        "accent_hover": "#f7bd7a",
        "accent_text": "#241405",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (32, 28, 24),
        "panel_border": (55, 47, 39),
    },
    # ── 5 鎏金铜：暖炭 + 古铜金 ───────────────────────────
    "bronze": {
        "label": "鎏金铜",
        "bg_main": "#1a1714",
        "bg_sidebar": "#12100d",
        "bg_surface": "#211d18",
        "bg_surface_alt": "#2a251f",
        "border": "#393329",
        "text_primary": "#f0e9de",
        "text_secondary": "#b3a795",
        "text_muted": "#7a6f5d",
        "accent": "#d9a05b",
        "accent_rgb": "217, 160, 91",
        "accent_hover": "#e2b57e",
        "accent_text": "#241a0c",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (33, 29, 24),
        "panel_border": (57, 51, 41),
    },
    # ── 6 曜石黑：纯炭 + 铂银（极简单色）──────────────────
    "obsidian": {
        "label": "曜石黑",
        "bg_main": "#121214",
        "bg_sidebar": "#0c0c0e",
        "bg_surface": "#1a1a1d",
        "bg_surface_alt": "#222226",
        "border": "#2e2e33",
        "text_primary": "#e8e8ea",
        "text_secondary": "#9c9ca3",
        "text_muted": "#6a6a72",
        "accent": "#c9c9d0",
        "accent_rgb": "201, 201, 208",
        "accent_hover": "#e0e0e5",
        "accent_text": "#101013",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (26, 26, 29),
        "panel_border": (46, 46, 51),
    },
    # ── 7 森林绿：松绿黑 + 暖象牙 ─────────────────────────
    "forest": {
        "label": "森林绿",
        "bg_main": "#0f1511",
        "bg_sidebar": "#0a0f0c",
        "bg_surface": "#161d18",
        "bg_surface_alt": "#1e2720",
        "border": "#2b362e",
        "text_primary": "#e7eadf",
        "text_secondary": "#9aa595",
        "text_muted": "#67715f",
        "accent": "#e2d9bd",
        "accent_rgb": "226, 217, 189",
        "accent_hover": "#efe8d4",
        "accent_text": "#1c180e",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (22, 29, 24),
        "panel_border": (43, 54, 46),
    },
    # ── 8 冰川蓝：青墨 + 冰青 ─────────────────────────────
    "ice": {
        "label": "冰川蓝",
        "bg_main": "#0d1418",
        "bg_sidebar": "#090e11",
        "bg_surface": "#141d23",
        "bg_surface_alt": "#1c2830",
        "border": "#2a3a44",
        "text_primary": "#e2ecef",
        "text_secondary": "#93a8b0",
        "text_muted": "#637a84",
        "accent": "#2fd4e0",
        "accent_rgb": "47, 212, 224",
        "accent_hover": "#63e0e9",
        "accent_text": "#061719",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (20, 29, 35),
        "panel_border": (42, 58, 68),
    },
    # ── 9 珊瑚红：可可 + 珊瑚 ─────────────────────────────
    "coral": {
        "label": "珊瑚红",
        "bg_main": "#191312",
        "bg_sidebar": "#110c0b",
        "bg_surface": "#211a18",
        "bg_surface_alt": "#2b211e",
        "border": "#3a2d29",
        "text_primary": "#f2e7e3",
        "text_secondary": "#b69d96",
        "text_muted": "#7b655e",
        "accent": "#f0756a",
        "accent_rgb": "240, 117, 106",
        "accent_hover": "#f79a91",
        "accent_text": "#26100d",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (33, 26, 24),
        "panel_border": (58, 45, 41),
    },
    # ── 10 靛青蓝：靛黑 + 长春花蓝 ────────────────────────
    "indigo": {
        "label": "靛青蓝",
        "bg_main": "#131221",
        "bg_sidebar": "#0d0c18",
        "bg_surface": "#1b1a2e",
        "bg_surface_alt": "#24223a",
        "border": "#322f4e",
        "text_primary": "#e9e8f6",
        "text_secondary": "#a3a1c4",
        "text_muted": "#6d6b90",
        "accent": "#7c8cf8",
        "accent_rgb": "124, 140, 248",
        "accent_hover": "#9aa7fa",
        "accent_text": "#0d1030",
        "danger": _DANGER, "danger_hover": _DANGER_HOVER, "danger_text": _DANGER_TEXT,
        "panel_bg": (27, 26, 46),
        "panel_border": (50, 47, 78),
    },
}


def get(name=None):
    """按名称取主题字典；名称无效或缺省时返回默认（翡翠绿）。"""
    return THEMES.get(name or DEFAULT, THEMES[DEFAULT])
