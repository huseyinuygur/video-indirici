from flask import Flask, render_template, request, send_file, flash, jsonify, url_for
import yt_dlp
import os
import threading
import time
import uuid # Benzersiz ID'ler oluşturmak için

app = Flask(__name__)
# Flash mesajları için gizli anahtar. Üretim ortamında daha karmaşık olmalı.
app.secret_key = 'supersecretkeyforsecureapp'

# İndirilen videoların kaydedileceği klasör
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# İndirme durumunu takip etmek için bir sözlük.
# Anahtar: session_id, Değer: {'status': 'pending/downloading/completed/failed', 'progress': '%', 'filepath': '...', 'error': '...'}
download_status = {}

# Çerez dosyasının yolu. Bu dosya GitHub'a ASLA yüklenmemelidir.
# PythonAnywhere/Render gibi sunucularda, bu dosyayı projenizin kök dizinine manuel olarak yüklemeniz gerekir.
# Güvenli bir ortam değişkeni kullanmak daha iyidir, ancak basitlik için doğrudan yolu belirtiyoruz.
# Eğer çerez dosyası yoksa, yt-dlp bot algılamaya takılabilir.
COOKIES_FILE = os.path.join(os.getcwd(), 'youtube_cookies.txt')

def download_video_thread(video_url, session_id):
    """
    Videoyu ayrı bir thread'de indiren fonksiyon.
    İlerleme durumunu download_status sözlüğünde günceller.
    """
    # Dosya adını belirlemeden önce videonun bilgilerini çek
    try:
        # download=False ile sadece bilgiyi çek, indirme yapma
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(video_url, download=False)
            title = info.get('title', 'video')
            # Geçersiz dosya adı karakterlerini temizle
            title = "".join([c for c in title if c.isalnum() or c in (' ', '.', '_', '-')]).rstrip()
            original_filename = f"{title}.mp4" # Varsayılan MP4 formatı
            
            # Dosya adı çakışmasını önlemek için benzersiz bir isim oluştur
            # Bu, aynı videonun birden fazla kez indirilmesini sağlar
            unique_filename = f"{uuid.uuid4()}_{original_filename}"
            filepath = os.path.join(DOWNLOAD_FOLDER, unique_filename)

    except Exception as e:
        download_status[session_id] = {'status': 'failed', 'error': f'URL bilgisi alınırken hata: {e}'}
        print(f"URL bilgisi alınırken hata: {e}")
        return

    # yt-dlp seçenekleri
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', # MP4 formatını tercih et
        'outtmpl': filepath, # İndirilen dosyanın yolu ve adı
        'progress_hooks': [lambda d: update_progress(d, session_id)], # İlerleme takibi için hook
        'noplaylist': True, # Sadece tek videoyu indir, oynatma listesini değil
        'nocheckcertificate': True, # SSL sertifikası hatalarını göz ardı et (nadiren gerekebilir)
        'retries': 3, # Ağ hatalarında 3 kez tekrar dene
        'fragment_retries': 3, # Parça indirme hatalarında 3 kez tekrar dene
        'socket_timeout': 10, # Soket zaman aşımı 10 saniye
    }

    # Çerez dosyası mevcutsa ydl_opts'a ekle
    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE
        print(f"Çerez dosyası kullanılıyor: {COOKIES_FILE}")
    else:
        print(f"UYARI: Çerez dosyası bulunamadı: {COOKIES_FILE}. Çerezsiz denenecek, bu bot algılamaya yol açabilir.")

    try:
        # İndirme işlemini başlat
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url]) # Videoyu indir
        
        # İndirme tamamlandıktan sonra durumu güncelle
        download_status[session_id] = {'status': 'completed', 'filepath': filepath, 'original_filename': original_filename}
        print(f"Video başarıyla indirildi: {filepath}")

    except Exception as e:
        # Hata durumunda durumu güncelle
        download_status[session_id] = {'status': 'failed', 'error': f'Video indirilirken hata oluştu: {e}'}
        print(f"Video indirilirken hata oluştu: {e}")
    finally:
        # İndirme tamamlandığında veya hata oluştuğunda geçici dosyaları temizle
        # Bu kısım yt-dlp tarafından otomatik yapılır, ancak ek temizlik gerekebilir
        pass

def update_progress(d, session_id):
    """
    yt-dlp'den gelen ilerleme bilgilerini download_status sözlüğünde günceller.
    """
    if d['status'] == 'downloading':
        p = d.get('_percent_str', 'N/A')
        download_status[session_id] = {'status': 'downloading', 'progress': p}
        # print(f"İndiriliyor ({session_id}): {p}")
    elif d['status'] == 'finished':
        download_status[session_id] = {'status': 'processing', 'progress': '100%'}
        # print(f"İndirme tamamlandı, işleniyor ({session_id})...")
    elif d['status'] == 'error':
        download_status[session_id] = {'status': 'failed', 'error': d.get('error', 'Bilinmeyen hata.')}
        # print(f"İndirme hatası ({session_id}): {d.get('error', 'Bilinmeyen hata.')}")

@app.route('/')
def index():
    """Ana sayfayı render eder."""
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def initiate_download():
    """
    Video indirme işlemini başlatan endpoint.
    Kullanıcıyı doğrudan indirmeye yönlendirmez, bir session ID ile durumu takip etmesini sağlar.
    """
    video_url = request.form['video_url']
    if not video_url:
        flash('Lütfen bir video URL\'si girin!', 'error')
        return render_template('index.html')

    # Benzersiz bir oturum ID'si oluştur
    session_id = str(uuid.uuid4())
    download_status[session_id] = {'status': 'pending', 'progress': '0%'}

    # İndirme işlemini ayrı bir thread'de başlat
    thread = threading.Thread(target=download_video_thread, args=(video_url, session_id))
    thread.start()

    flash(f'Video indirme işlemi başlatıldı! Durumu takip ediliyor. Lütfen bekleyin.', 'info')
    # Kullanıcıyı ana sayfaya yönlendir ve JavaScript ile durumu sorgulaması için session_id'yi gönder
    return render_template('index.html', session_id=session_id)

@app.route('/status/<session_id>')
def get_download_status(session_id):
    """
    Belirli bir indirme işleminin mevcut durumunu JSON olarak döndürür.
    Frontend bu endpoint'i düzenli olarak sorgulayacak.
    """
    status_info = download_status.get(session_id, {'status': 'not_found', 'error': 'İndirme bulunamadı.'})
    
    # Eğer indirme tamamlandıysa, indirme linkini de ekle
    if status_info['status'] == 'completed':
        # Flask'ın url_for fonksiyonu ile dinamik link oluştur
        download_link = url_for('serve_downloaded_file', session_id=session_id)
        status_info['download_link'] = download_link
    
    return jsonify(status_info)

@app.route('/download_file/<session_id>')
def serve_downloaded_file(session_id):
    """
    İndirme tamamlandığında dosyayı kullanıcıya sunan endpoint.
    Dosya sunulduktan sonra sunucudan silinir (geçici depolama için).
    """
    status_info = download_status.get(session_id)

    if status_info and status_info['status'] == 'completed' and 'filepath' in status_info:
        filepath = status_info['filepath']
        original_filename = status_info.get('original_filename', 'video.mp4')

        if os.path.exists(filepath):
            try:
                # Dosyayı kullanıcıya gönder
                # as_attachment=True ile dosya indirme olarak sunulur
                # download_name ile dosyanın kullanıcının bilgisayarında görünecek adı belirlenir
                return send_file(filepath, as_attachment=True, download_name=original_filename)
            except Exception as e:
                flash(f'Dosya gönderilirken hata oluştu: {e}', 'error')
                return "Dosya gönderilirken hata oluştu.", 500
            finally:
                # Dosya gönderildikten sonra sunucudan sil (geçici depolama)
                # Bu, özellikle Render gibi ephemeral dosya sistemlerinde önemlidir
                if os.path.exists(filepath):
                    os.remove(filepath)
                    print(f"Dosya sunucudan silindi: {filepath}")
                # İndirme durumunu sözlükten kaldır
                if session_id in download_status:
                    del download_status[session_id]
        else:
            flash('Dosya bulunamadı veya zaten silindi.', 'error')
            return "Dosya bulunamadı veya zaten silindi.", 404
    else:
        flash('Dosya henüz hazır değil veya bir hata oluştu.', 'error')
        return "Dosya henüz hazır değil veya bir hata oluştu.", 404

if __name__ == '__main__':
    # Yerelde test ederken host='0.0.0.0' ile mobil cihazlardan erişimi açabilirsiniz
    # Üretim ortamında (Render/PythonAnywhere) bu ayarlar WSGI sunucusu tarafından yönetilir.
    app.run(debug=True, host='0.0.0.0', port=5000)
