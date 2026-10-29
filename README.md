# OtoClean

Windows için disk temizleme uygulaması. Diskini tarar, bulduğu her şeyi
**🟢 Güvenli / 🟡 İncele / 🔴 Dokunma** diye ayırır ve her birinin *neden* o grupta olduğunu,
*silersen ne olacağını* Türkçe açıklar. Tek tıkla **Gereksizleri Temizle** düğmesi, silmeden önce
neyi sileceğini listeler ve onayını bekler. Kâğıt ve Beyaz olmak üzere iki tema vardır.

## Kurulum (Windows 10/11, 64 bit)

Kurulum programı yoktur; indirip açman yeterli. Python gerekmez.

1. [Releases](https://github.com/pengueniniz/otoclean/releases/latest) sayfasından
   **`OtoClean-windows-x64.zip`** dosyasını indir.
2. Zip'e sağ tıkla → **Tümünü ayıkla…** → örneğin `C:\Programlar\OtoClean` klasörüne çıkar.
   Zip'in içinden doğrudan çalıştırma; `_internal` klasörü exe'nin yanında durmalı.
3. Klasördeki **`OtoClean.exe`**'yi çift tıkla.
4. Windows "Bilgisayarınız korundu" (SmartScreen) uyarısı gösterirse **Ek bilgi → Yine de çalıştır**'a bas.
   Bu uyarı exe dijital olarak imzalanmadığı için çıkar.
5. İstersen `OtoClean.exe`'ye sağ tıkla → **Daha fazla seçenek → Masaüstüne gönder (kısayol oluştur)**.

`C:\Windows\Temp` gibi yönetici izni isteyen konumlar için uygulamadaki
**Yönetici olarak yeniden başlat** düğmesini kullan.

### İlk kullanım

1. **Hızlı Tara**'ya bas (yarım dakika sürer) ya da doğrudan **Gereksizleri Temizle**'ye bas.
2. Açılan pencerede silinecek her şey kategori, boyut ve silme yöntemiyle listelenir.
   Chrome, Discord gibi önbelleği kilitleyen uygulamalar açıksa uyarır; onları kapat.
3. Emin olmak istersen önce alttaki **Deneme modu**'nu aç: hiçbir şey silinmez, sadece ne kadar yer
   açılacağı hesaplanır.
4. Haftalık otomatik temizlik için alttaki **Haftalık otomatik güvenli temizlik** kutusunu işaretle
   (yalnızca 🟢 öğeler temizlenir).

### Kaldırma

Haftalık temizliği açtıysan önce kutunun işaretini kaldır, sonra klasörü sil.
Ayarlar ve geçmiş `%LOCALAPPDATA%\OtoClean` klasöründedir; onu da silebilirsin.

## Kaynaktan çalıştırma

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

```powershell
.\.venv\Scripts\python.exe -m otoclean            # masaüstü uygulaması
.\.venv\Scripts\python.exe -m otoclean --auto-safe # arayüzsüz güvenli temizlik
.\.venv\Scripts\python.exe -m otoclean --schedule on   # haftalık görevi kur (off: kaldır)
.\build.ps1                                        # testler + dist\OtoClean\OtoClean.exe
```

## Nasıl karar verir?

| Seviye | Ne bulur | Ne yapılır |
|---|---|---|
| 🟢 Güvenli | Temp, tarayıcı/VS Code/Discord/Spotify önbellekleri, npm/pip/uv/yarn/pnpm/bun/NuGet/Cargo/Gradle önbellekleri, shader önbellekleri, çökme dökümleri, hata raporları, Windows Update indirmeleri, Geri Dönüşüm Kutusu | Varsayılan seçili (yönetici gerektirenler ve Geri Dönüşüm Kutusu hariç) |
| 🟡 İncele | İndirilenler'deki 30+ günlük kurulum/arşiv dosyaları, 180+ günlük dosyalar, 90+ gündür dokunulmamış projelerin `node_modules`/`.venv`/`target`/`.next` klasörleri, 500 MB+ ve 180+ gündür kullanılmayan dosyalar, birebir kopyalar, Docker/Android imajları, `.cache` | Sen seçersin; asla otomatik silinmez |
| 🔴 Dokunma | `hiberfil.sys`, `pagefile.sys`, `Windows\Installer`, `Windows.old` | Seçilemez; doğru aracı söyler (`powercfg -h off`, Disk Temizleme…) |

## Güvenlik önlemleri

- **İki katlı koruma:** `core/protected.py` hem sınıflandırmada hem silme anında kontrol edilir.
  Windows, Program Files, ProgramData, `.git`, `.ssh`, sürücü kökleri ve önemli klasörlerin üstleri asla silinmez.
  Belgeler/Masaüstü/OneDrive gibi kişisel klasörlerde yalnızca yeniden üretilebilir proje çıktıları silinebilir.
- Varsayılan olarak her şey **Geri Dönüşüm Kutusu'na** gider. Önbellekler için "kalıcı sil" isteğe bağlıdır;
  🟡 öğeler her zaman kutuya gider.
- npm/pip/uv gibi araçların varsa **kendi temizleme komutu** kullanılır.
- Son 24 saatte değişen temp dosyalarına dokunulmaz; kullanımdaki dosyalar atlanıp raporlanır.
- Junction/sembolik bağlantılar taranmaz; hardlink'ler kopya sayılmaz.
- Kopya gruplarında bir asıl dosya her zaman tutulur ve asıl dosya başka bir başlık altında önerilmez.
- **Deneme modu** hiçbir şey silmeden ne kadar yer açılacağını hesaplar.
- Silme anında yolda junction/symlink varsa veya yolun gerçek konumu korumalıysa silinmez;
  `\\?\`, UNC ve 8.3 kısa ad yazımları da gerçek yola çözülerek kontrol edilir.
- Tarama sonrası boyutu/tarihi değişen dosyalar silinmez. Araç komutları nötr bir geçici
  klasörde çalışır; çalışma dizinine bırakılmış exe'ler kabul edilmez.
- Kopya ve büyük-eski önerileri yalnızca kullanıcı içeriğine yapılır (AppData, Program Files,
  sanal ortamlar, oyun kütüphaneleri hariç); yalnızca bulutta duran OneDrive dosyaları okunmaz.

## Bilinen sınırlamalar

- 260 karakteri aşan yollar taranırken/silinirken atlanabilir ve "atlandı" olarak raporlanır.
- Zamanlanmış görev, kurulduğu andaki exe/venv yolunu kullanır; uygulama taşınırsa görevi
  kapatıp yeniden aç.

## Veriler

`%LOCALAPPDATA%\OtoClean\`: `settings.json`, `history.db` (temizlik geçmişi), `otoclean.log`.

## Geliştirme

```powershell
.\.venv\Scripts\python.exe -m pytest -q --cov=otoclean
```

Yeni bir önbellek eklemek için `otoclean/core/rules/catalog.py` içindeki `LOCATION_RULES` listesine
bir `_cache(...)` satırı eklemek yeterli.

## Lisans

MIT. Yazılım "olduğu gibi" sunulur; silinen dosyalardan kullanıcı sorumludur. Emin olmadığın
öğeleri silme ve önce Deneme modunu kullan.
