"""Görsel dil ve temalar.

İki tema var: "Kâğıt" (sıcak, kâğıt zemin) ve "Beyaz" (saf beyaz, serin griler).
Renkler yalnızca anlam taşır: yeşil = güvenli, amber = incele, kırmızı = dokunma.
Vurgu rengi sadece etkileşim için kullanılır.

Modül düzeyindeki adlar (PAPER, INK, …) etkin temayı gösterir; `use()` bunları
günceller. Widget'lar renkleri oluşturulurken veya çizilirken buradan okur, bu
yüzden tema değişince ana pencere yeniden kurulur.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..core.models import RiskLevel

FONT_UI = "Segoe UI Variable Text"
FONT_DISPLAY = "Segoe UI Variable Display"
FONT_MONO = "Cascadia Mono"


@dataclass(frozen=True)
class Palette:
    key: str
    name: str
    paper: str          # Pencere zemini
    surface: str        # Kartlar, liste
    surface_sunk: str   # Gömülü alanlar, çubuk zemini
    ink: str
    ink_soft: str
    ink_faint: str
    rule: str           # Kenarlıklar
    accent: str
    accent_hover: str
    row_alt: str
    row_hover: str
    selection: str
    map_neutral: str    # Disk haritasında sınıflandırılmamış kutular
    risk: dict          # RiskLevel → (ön plan, zemin)


PALETTES: dict[str, Palette] = {
    "paper": Palette(
        key="paper", name="Kâğıt",
        paper="#F4F1EA", surface="#FFFDF8", surface_sunk="#EAE5DA",
        ink="#1D1B17", ink_soft="#5E584D", ink_faint="#968E80", rule="#D9D2C3",
        accent="#1F3A5F", accent_hover="#2C5283",
        row_alt="#FAF7F0", row_hover="#F1ECE1", selection="#DCE5F0", map_neutral="#D8D1C2",
        risk={RiskLevel.SAFE: ("#2F7D4F", "#E1F0E5"),
              RiskLevel.REVIEW: ("#B7791F", "#F8EBD3"),
              RiskLevel.DANGER: ("#B0362B", "#F6DEDB")},
    ),
    "white": Palette(
        key="white", name="Beyaz",
        paper="#FFFFFF", surface="#FFFFFF", surface_sunk="#EEF1F4",
        ink="#14171C", ink_soft="#535B66", ink_faint="#8A929D", rule="#E2E6EB",
        accent="#1D5BD6", accent_hover="#2F6EEA",
        row_alt="#FAFBFC", row_hover="#F2F5F9", selection="#E4EDFD", map_neutral="#DDE2E8",
        risk={RiskLevel.SAFE: ("#1B7A4A", "#E5F4EC"),
              RiskLevel.REVIEW: ("#A4660F", "#FCF1DE"),
              RiskLevel.DANGER: ("#C03A2B", "#FCE8E6")},
    ),
}
DEFAULT_THEME = "paper"

# Etkin temanın değerleri (use() tarafından doldurulur)
PALETTE: Palette = PALETTES[DEFAULT_THEME]
PAPER = SURFACE = SURFACE_SUNK = INK = INK_SOFT = INK_FAINT = RULE = ""
ACCENT = ACCENT_HOVER = MAP_NEUTRAL = ""
STYLESHEET = ""


def risk_fg(level: RiskLevel) -> str:
    return PALETTE.risk[level][0]


def risk_bg(level: RiskLevel) -> str:
    return PALETTE.risk[level][1]


def _icon_dir() -> str:
    """Onay kutusu simgeleri için SVG'leri (QSS yalnızca dosya yolu kabul eder) yazar."""
    from ..core.settings import data_dir

    try:
        path = os.path.join(data_dir(), "theme")
        os.makedirs(path, exist_ok=True)
    except OSError:
        return ""  # Profil yazılamıyorsa kutular simgesiz çalışır
    icons = {
        "check.svg": '<path d="M3.5 8.5l3 3 6-7" fill="none" stroke="#fff" stroke-width="2" '
                     'stroke-linecap="round" stroke-linejoin="round"/>',
        "partial.svg": '<path d="M4 8h8" stroke="#fff" stroke-width="2" stroke-linecap="round"/>',
    }
    for name, body in icons.items():
        target = os.path.join(path, name)
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">{body}</svg>'
        try:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(svg)
        except OSError:
            pass  # Simge yazılamazsa kutular yine çalışır, sadece tik görünmez
    return path.replace("\\", "/")


def _build_stylesheet(p: Palette) -> str:
    icons = _icon_dir()
    return f"""
* {{ font-family: "{FONT_UI}"; font-size: 10pt; color: {p.ink}; }}
QMainWindow, QWidget#Root, QDialog {{ background: {p.paper}; }}
QToolTip {{ background: {p.ink}; color: {p.surface}; border: none; padding: 6px 8px; }}

QLabel#AppTitle {{ font-family: "{FONT_DISPLAY}"; font-size: 22pt; font-weight: 700; }}
QLabel#AppSubtitle {{ color: {p.ink_soft}; font-size: 10pt; }}
QLabel#SectionLabel {{ color: {p.ink_faint}; font-size: 8.5pt; font-weight: 600; letter-spacing: 1.2px; }}
QLabel#Muted {{ color: {p.ink_soft}; }}
QLabel#EmptyTitle {{ font-family: "{FONT_DISPLAY}"; font-size: 16pt; font-weight: 700; }}

QFrame#Card {{ background: {p.surface}; border: 1px solid {p.rule}; border-radius: 10px; }}
QFrame#Card:hover {{ border-color: {p.ink_faint}; }}
QFrame#Card[active="true"] {{ border: 2px solid {p.accent}; }}
QFrame#Panel {{ background: {p.surface}; border: 1px solid {p.rule}; border-radius: 10px; }}

QPushButton {{
    background: {p.surface}; border: 1px solid {p.rule}; border-radius: 7px;
    padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {p.ink_soft}; }}
QPushButton:pressed {{ background: {p.surface_sunk}; }}
QPushButton:disabled {{ color: {p.ink_faint}; border-color: {p.surface_sunk}; }}
QPushButton:focus {{ outline: none; border: 2px solid {p.accent}; }}
QPushButton#Primary {{ background: {p.accent}; color: #FFFFFF; border: none; padding: 9px 18px; }}
QPushButton#Primary:hover {{ background: {p.accent_hover}; }}
QPushButton#Primary:disabled {{ background: {p.ink_faint}; color: {p.surface}; }}
QPushButton#Hero {{
    background: {p.risk[RiskLevel.SAFE][0]}; color: #FFFFFF; border: none;
    padding: 10px 20px; font-size: 10.5pt; font-weight: 700;
}}
QPushButton#Hero:hover {{ background: {p.risk[RiskLevel.SAFE][0]}; border: 2px solid {p.ink}; }}
QPushButton#Hero:disabled {{ background: {p.ink_faint}; color: {p.surface}; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {p.accent}; padding: 4px 6px; }}
QPushButton#Ghost:hover {{ text-decoration: underline; }}
QPushButton#Segment {{
    background: transparent; border: 1px solid {p.rule}; border-radius: 0; padding: 5px 12px;
    color: {p.ink_soft}; font-weight: 600;
}}
QPushButton#Segment:checked {{ background: {p.ink}; color: {p.surface}; border-color: {p.ink}; }}
QPushButton#Segment[first="true"] {{ border-top-left-radius: 7px; border-bottom-left-radius: 7px; }}
QPushButton#Segment[last="true"] {{ border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}

QTreeWidget, QTableWidget {{
    background: {p.surface}; border: 1px solid {p.rule}; border-radius: 10px;
    alternate-background-color: {p.row_alt}; selection-background-color: {p.selection};
    selection-color: {p.ink}; outline: none;
}}
QTreeWidget::item, QTableWidget::item {{ padding: 4px 2px; border: none; }}
QTreeWidget::item:hover {{ background: {p.row_hover}; }}
QTreeWidget::item:selected, QTableWidget::item:selected {{ background: {p.selection}; color: {p.ink}; }}
QHeaderView::section {{
    background: {p.surface}; color: {p.ink_faint}; border: none; border-bottom: 1px solid {p.rule};
    padding: 6px 8px; font-size: 8.5pt; font-weight: 600;
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QTreeWidget::indicator {{
    width: 15px; height: 15px; border: 1.5px solid {p.ink_faint}; border-radius: 4px;
    background: {p.surface};
}}
QCheckBox::indicator:hover, QTreeWidget::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked, QTreeWidget::indicator:checked {{
    background: {p.accent}; border-color: {p.accent}; image: url("{icons}/check.svg");
}}
QTreeWidget::indicator:indeterminate {{
    background: {p.accent}; border-color: {p.accent}; image: url("{icons}/partial.svg");
}}
QCheckBox::indicator:disabled {{ background: {p.surface_sunk}; border-color: {p.rule}; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; padding: 8px 16px; margin-right: 4px; color: {p.ink_soft};
    border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {p.ink}; border-bottom: 2px solid {p.ink}; }}
QTabBar::tab:hover {{ color: {p.ink}; }}

QProgressBar {{
    background: {p.surface_sunk}; border: none; border-radius: 3px; height: 6px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}

QComboBox {{ background: {p.surface}; border: 1px solid {p.rule}; border-radius: 7px; padding: 6px 10px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {p.rule}; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {p.ink_faint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: transparent; }}
QMessageBox QLabel {{ color: {p.ink}; }}
"""


def use(key: str) -> Palette:
    """Etkin temayı değiştirir ve modül düzeyindeki renk adlarını günceller."""
    global PALETTE, PAPER, SURFACE, SURFACE_SUNK, INK, INK_SOFT, INK_FAINT, RULE
    global ACCENT, ACCENT_HOVER, MAP_NEUTRAL, STYLESHEET
    p = PALETTES.get(key, PALETTES[DEFAULT_THEME])
    PALETTE = p
    PAPER, SURFACE, SURFACE_SUNK = p.paper, p.surface, p.surface_sunk
    INK, INK_SOFT, INK_FAINT, RULE = p.ink, p.ink_soft, p.ink_faint, p.rule
    ACCENT, ACCENT_HOVER, MAP_NEUTRAL = p.accent, p.accent_hover, p.map_neutral
    STYLESHEET = _build_stylesheet(p)
    return p


use(DEFAULT_THEME)
