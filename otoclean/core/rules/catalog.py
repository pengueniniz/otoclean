"""Bilinen konumlar için kural kataloğu.

Her kural bir `Category` (risk + Türkçe açıklama) ve ortam değişkenli/glob
desteğli yol şablonlarından oluşur. Yeni bir önbellek eklemek için listeye bir
`LocationRule` eklemek yeterlidir.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Category, RiskLevel

S, R, D = RiskLevel.SAFE, RiskLevel.REVIEW, RiskLevel.DANGER

CACHE_WHY = "Uygulamanın geçici önbelleği; gerektiğinde kendini yeniden oluşturur."
CACHE_IF = "Uygulama ilk açılışta biraz yavaş olabilir, veri kaybı olmaz."


@dataclass(frozen=True)
class LocationRule:
    category: Category
    paths: tuple[str, ...]


def _cat(key: str, name: str, risk: RiskLevel, why: str, if_deleted: str, **kw) -> Category:
    return Category(key=key, name=name, risk=risk, why=why, if_deleted=if_deleted, **kw)


def _cache(key: str, name: str, *paths: str, auto_ok: bool = True, **kw) -> LocationRule:
    kw.setdefault("why", CACHE_WHY)
    kw.setdefault("if_deleted", CACHE_IF)
    return LocationRule(_cat(key, name, S, auto_ok=auto_ok, contents_only=True, **kw), paths)


LOCAL = "%LOCALAPPDATA%"
ROAM = "%APPDATA%"
HOME = "%USERPROFILE%"
CHROMIUM = ("Cache", "Code Cache", "GPUCache", r"Service Worker\CacheStorage")


def _chromium(base: str) -> tuple[str, ...]:
    return tuple(rf"{base}\User Data\*\{sub}" for sub in CHROMIUM)


LOCATION_RULES: tuple[LocationRule, ...] = (
    # ---------------- 🟢 GÜVENLİ ----------------
    # %TEMP% yerine sabit konum: TEMP yanlışlıkla C:\ gibi geniş bir yeri gösterebilir
    _cache("user_temp", "Kullanıcı geçici dosyaları (TEMP)", rf"{LOCAL}\Temp",
           why="Programların kurulum/çalışma sırasında bıraktığı geçici dosyalar.",
           if_deleted="Bir şey kaybolmaz; son 24 saatteki dosyalara dokunulmaz.",
           min_age_days=1),
    _cache("windows_temp", "Windows geçici dosyaları", r"%WINDIR%\Temp",
           why="Windows ve servislerin geçici dosyaları.",
           if_deleted="Bir şey kaybolmaz; yönetici izni gerekir.",
           min_age_days=1, needs_admin=True),
    _cache("chrome_cache", "Google Chrome önbelleği", *_chromium(rf"{LOCAL}\Google\Chrome")),
    _cache("edge_cache", "Microsoft Edge önbelleği", *_chromium(rf"{LOCAL}\Microsoft\Edge")),
    _cache("brave_cache", "Brave önbelleği", *_chromium(rf"{LOCAL}\BraveSoftware\Brave-Browser")),
    _cache("opera_cache", "Opera önbelleği", rf"{LOCAL}\Opera Software\*\Cache"),
    _cache("firefox_cache", "Firefox önbelleği", rf"{LOCAL}\Mozilla\Firefox\Profiles\*\cache2"),
    _cache("npm_cache", "npm paket önbelleği", rf"{LOCAL}\npm-cache",
           why="npm'in indirdiği paketlerin kopyası; projeler kendi node_modules'unu kullanır.",
           if_deleted="Sonraki `npm install` paketleri tekrar indirir.",
           native_cmd=("npm", "cache", "clean", "--force")),
    _cache("pip_cache", "pip paket önbelleği", rf"{LOCAL}\pip\cache",
           why="pip'in indirdiği paket arşivleri; kurulu paketler bundan etkilenmez.",
           if_deleted="Sonraki `pip install` paketleri tekrar indirir.",
           native_cmd=("python", "-m", "pip", "cache", "purge")),
    _cache("uv_cache", "uv önbelleği", rf"{LOCAL}\uv\cache",
           native_cmd=("uv", "cache", "clean")),
    _cache("yarn_cache", "Yarn önbelleği", rf"{LOCAL}\Yarn\Cache",
           native_cmd=("yarn", "cache", "clean")),
    _cache("pnpm_store", "pnpm paket deposu", rf"{LOCAL}\pnpm\store", auto_ok=False,
           why="pnpm'in ortak paket deposu.",
           if_deleted="Projeler çalışmaya devam eder; yeni kurulumlar paketleri tekrar indirir.",
           native_cmd=("pnpm", "store", "prune")),
    _cache("bun_cache", "Bun önbelleği", rf"{HOME}\.bun\install\cache"),
    _cache("nuget_cache", "NuGet paket önbelleği", rf"{HOME}\.nuget\packages", auto_ok=False,
           if_deleted=".NET projeleri bir sonraki derlemede paketleri tekrar indirir.",
           native_cmd=("dotnet", "nuget", "locals", "all", "--clear")),
    _cache("cargo_cache", "Cargo (Rust) indirme önbelleği", rf"{HOME}\.cargo\registry\cache"),
    _cache("gradle_cache", "Gradle önbelleği", rf"{HOME}\.gradle\caches", auto_ok=False,
           if_deleted="Android/Java projeleri ilk derlemede bağımlılıkları tekrar indirir."),
    _cache("vscode_cache", "VS Code önbellekleri",
           rf"{ROAM}\Code\Cache", rf"{ROAM}\Code\CachedData", rf"{ROAM}\Code\CachedExtensionVSIXs",
           rf"{ROAM}\Code\Code Cache", rf"{ROAM}\Code\GPUCache", rf"{ROAM}\Code\logs"),
    _cache("discord_cache", "Discord önbelleği", rf"{ROAM}\discord\Cache", rf"{ROAM}\discord\Code Cache"),
    _cache("teams_cache", "Teams önbelleği", rf"{ROAM}\Microsoft\Teams\Cache",
           rf"{LOCAL}\Packages\MSTeams_*\LocalCache\Microsoft\MSTeams\EBWebView\Default\Cache"),
    _cache("spotify_cache", "Spotify önbelleği", rf"{LOCAL}\Spotify\Data"),
    _cache("shader_cache", "Ekran kartı shader önbelleği",
           rf"{LOCAL}\D3DSCache", rf"{LOCAL}\NVIDIA\DXCache", rf"{LOCAL}\NVIDIA\GLCache",
           rf"{LOCAL}\AMD\DxCache", rf"{LOCAL}\AMD\DxcCache"),
    _cache("crash_dumps", "Çökme dökümleri", rf"{LOCAL}\CrashDumps",
           why="Çöken programların hata ayıklama dökümleri.",
           if_deleted="Sadece geliştiriciye hata raporu gönderemezsin."),
    _cache("wer_reports", "Windows hata raporları",
           rf"{LOCAL}\Microsoft\Windows\WER", r"%PROGRAMDATA%\Microsoft\Windows\WER\ReportArchive",
           r"%PROGRAMDATA%\Microsoft\Windows\WER\ReportQueue",
           why="Windows Hata Bildirimi'nin biriktirdiği raporlar.",
           if_deleted="Hiçbir program etkilenmez."),
    _cache("windows_update", "Windows Update indirmeleri", r"%WINDIR%\SoftwareDistribution\Download",
           why="Kurulmuş güncellemelerin indirme dosyaları.",
           if_deleted="Bekleyen bir güncelleme varsa tekrar indirilir; yönetici izni gerekir.",
           needs_admin=True, min_age_days=7),
    _cache("delivery_optimization", "Teslim İyileştirme önbelleği",
           r"%WINDIR%\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache",
           why="Güncellemeleri diğer bilgisayarlarla paylaşmak için tutulan kopyalar.",
           if_deleted="Bir şey kaybolmaz; yönetici izni gerekir.", needs_admin=True),
    LocationRule(_cat(
        "thumbnail_cache", "Küçük resim önbelleği", S,
        why="Dosya Gezgini'nin önizleme resimleri.",
        if_deleted="Klasörler ilk açılışta önizlemeleri yeniden oluşturur.",
        auto_ok=False), (rf"{LOCAL}\Microsoft\Windows\Explorer\thumbcache_*.db",)),
    LocationRule(_cat(
        "recycle_bin", "Geri Dönüşüm Kutusu", S,
        why="Daha önce sildiğin dosyalar burada bekliyor.",
        if_deleted="Bu dosyalar KALICI olarak silinir, geri alınamaz.",
        special="recycle_bin"), ()),

    # ---------------- 🟡 İNCELE ----------------
    LocationRule(_cat(
        "docker_data", "Docker disk imajı", R,
        why="Docker imajları, konteynerleri ve volume'leri bu sanal diskte.",
        if_deleted="Klasörü silmek tüm Docker verisini götürür; bunun yerine `docker system prune -a` kullan.",
        advice="docker system prune -a"), (rf"{LOCAL}\Docker\wsl",)),
    LocationRule(_cat(
        "android_images", "Android emülatör imajları", R,
        why="Android Studio emülatör sistem imajları; kullanmadığın sürümler büyük yer kaplar.",
        if_deleted="Silinen sürümle emülatör açılmaz; SDK Manager'dan tekrar indirilebilir."),
        (rf"{LOCAL}\Android\Sdk\system-images\*",)),
    LocationRule(_cat(
        "android_avd", "Android sanal cihazları (AVD)", R,
        why="Oluşturduğun emülatör cihazlarının diskleri.",
        if_deleted="O sanal cihaz ve içindeki veriler silinir."), (rf"{HOME}\.android\avd\*.avd",)),
    LocationRule(_cat(
        "hf_cache", "Hugging Face model önbelleği", R,
        why="İndirilmiş yapay zeka modelleri; genelde çok büyüktür.",
        if_deleted="Model tekrar gerektiğinde yeniden indirilir (GB'larca olabilir)."),
        (rf"{HOME}\.cache\huggingface",)),
    LocationRule(_cat(
        "generic_dot_cache", "Genel .cache klasörü", R,
        why="Çeşitli araçların önbellekleri; çoğu yeniden oluşur.",
        if_deleted="İlgili araçlar verilerini tekrar indirir/oluşturur.", contents_only=True),
        (rf"{HOME}\.cache",)),
    LocationRule(_cat(
        "rustup_toolchains", "Rust toolchain'leri", R,
        why="Kurulu Rust sürümleri; eski/kullanılmayan sürümler yer kaplar.",
        if_deleted="Silinen toolchain'i kullanan projeler derlenmez; `rustup toolchain list` ile kontrol et.",
        advice="rustup toolchain uninstall <sürüm>"), (rf"{HOME}\.rustup\toolchains\*",)),

    # ---------------- 🔴 SİLME ----------------
    LocationRule(_cat(
        "hiberfil", "Hazırda bekletme dosyası", D,
        why="Hazırda bekletme ve Hızlı Başlatma için RAM içeriğini tutar.",
        if_deleted="Elle silinemez. Hazırda bekletmeyi kullanmıyorsan yönetici terminalde komutu çalıştır.",
        advice="powercfg -h off"), (r"%SYSTEMDRIVE%\hiberfil.sys",)),
    LocationRule(_cat(
        "pagefile", "Sayfa (takas) dosyası", D,
        why="Windows sanal belleği; RAM dolunca kullanılır.",
        if_deleted="Silmek sistemi kararsız yapar. Boyutu Sistem > Gelişmiş > Sanal bellek'ten ayarlanır.",
        advice="sysdm.cpl > Gelişmiş > Performans > Sanal bellek"),
        (r"%SYSTEMDRIVE%\pagefile.sys", r"%SYSTEMDRIVE%\swapfile.sys")),
    LocationRule(_cat(
        "win_installer", "Windows Installer önbelleği", D,
        why="Kurulu programların kaldırma/onarma için ihtiyaç duyduğu .msi/.msp dosyaları.",
        if_deleted="Programlar kaldırılamaz veya güncellenemez hale gelir.",
        advice="Elle silme. Disk Temizleme (cleanmgr) kullan."), (r"%WINDIR%\Installer",)),
    LocationRule(_cat(
        "windows_old", "Eski Windows kurulumu (Windows.old)", D,
        why="Windows yükseltmesinden sonra geri dönmek için tutulan eski sistem.",
        if_deleted="Önceki Windows sürümüne geri dönemezsin. Elle silmek yerine Disk Temizleme kullan.",
        advice="cleanmgr > Sistem dosyalarını temizle > Önceki Windows yüklemeleri"),
        (r"%SYSTEMDRIVE%\Windows.old",)),
)

# Dedektörlerin kullandığı kategoriler
STALE_NODE_MODULES = _cat(
    "stale_node_modules", "Eski projelerin node_modules klasörleri", R,
    why="90+ gündür dokunulmamış projelerin bağımlılıkları.",
    if_deleted="Projeye geri dönersen `npm install` ile tekrar oluşturulur.")
STALE_VENV = _cat(
    "stale_venv", "Eski projelerin Python sanal ortamları", R,
    why="90+ gündür dokunulmamış projelerin .venv klasörleri.",
    if_deleted="`python -m venv .venv` ve `pip install -r requirements.txt` ile yeniden kurulur.")
STALE_BUILD = _cat(
    "stale_build", "Eski projelerin derleme çıktıları", R,
    why="Rust target/, Next.js .next/ gibi tamamen yeniden üretilebilir çıktılar.",
    if_deleted="Bir sonraki derlemede yeniden oluşturulur (ilk derleme uzun sürer).")
OLD_INSTALLERS = _cat(
    "old_installers", "İndirilenler: eski kurulum/arşiv dosyaları", R,
    why="30+ günlük .exe/.msi/.zip/.iso dosyaları; program kurulduysa genelde gerekmez.",
    if_deleted="Tekrar lazım olursa yeniden indirmen gerekir.")
OLD_DOWNLOADS = _cat(
    "old_downloads", "İndirilenler: uzun süredir dokunulmamış dosyalar", R,
    why="180+ gündür değiştirilmemiş indirilen dosyalar.",
    if_deleted="Dosya Geri Dönüşüm Kutusu'na gider; önemliyse önce taşı.")
LARGE_OLD = _cat(
    "large_old", "Büyük ve uzun süredir kullanılmayan dosyalar", R,
    why="500 MB üstü, 180+ gündür açılmamış/değiştirilmemiş dosyalar.",
    if_deleted="Dosya Geri Dönüşüm Kutusu'na gider; içeriğini bildiğinden emin ol.")
DUPLICATES = _cat(
    "duplicates", "Kopya dosyalar", R,
    why="İçeriği byte byte aynı olan dosyalar; her gruptan bir kopya tutulur.",
    if_deleted="Asıl kopya yerinde kalır; bir program o yoldaki dosyayı bekliyorsa bozulabilir.")
PROTECTED = _cat(
    "protected", "Korumalı sistem/kişisel alanlar", D,
    why="Windows, programlar veya kişisel belgeler.",
    if_deleted="Sistem veya programlar bozulabilir, kişisel veri kaybolur.")

ALL_CATEGORIES: tuple[Category, ...] = tuple(r.category for r in LOCATION_RULES) + (
    STALE_NODE_MODULES, STALE_VENV, STALE_BUILD, OLD_INSTALLERS,
    OLD_DOWNLOADS, LARGE_OLD, DUPLICATES, PROTECTED,
)
