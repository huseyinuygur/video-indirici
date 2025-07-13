from flask import Flask, render_template, request, send_file, flash, jsonify, url_for
import yt_dlp
import os
import threading
import time
import uuid # Benzersiz ID'ler oluşturmak için
import base64 # Ortam değişkeninden çerezleri okumak için

app = Flask(__name__)
# Flash mesajları için gizli anahtar. Üretim ortamında (Render) FLASK_SECRET_KEY ortam değişkeninden alınmalı.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecretkeyforsecureapp')

# İndirilen videoların kaydedileceği klasör - ARTIK SUNUCUYA İNDİRMEYECEĞİZ, SADECE GEÇİCİ ÇEREZ İÇİN KULLANILACAK
# Bu klasörü sadece çerez dosyasını geçici olarak yazmak için kullanabiliriz, veya /tmp kullanabiliriz.
# Daha basit olması için COOKIES_FILE_PATH'i /tmp'ye yönlendirelim.
# DOWNLOAD_FOLDER = 'downloads'
# if not os.path.exists(DOWNLOAD_FOLDER):
#     os.makedirs(DOWNLOAD_FOLDER) # Bu satırlar artık gerekli değil

# İndirme durumunu takip etmek için bir sözlük.
# Anahtar: session_id, Değer: {'status': 'pending/extracting_info/formats_available/failed', ...}
# formats_available durumunda 'available_formats': [{'format_id': '...', 'quality': '...', 'filesize': '...', 'direct_url': '...'}]
download_status = {}

# Çerez dosyasının adı ve yolu. Bu dosya geçici olarak oluşturulacak ve silinecek.
# /tmp dizini, çoğu Linux tabanlı sistemde geçici dosyalar için kullanılır ve otomatik temizlenir.
COOKIES_FILE_NAME = 'youtube_cookies.txt'
COOKIES_FILE_PATH = os.path.join('/tmp', COOKIES_FILE_NAME) # Çerez dosyasını /tmp'ye yazıyoruz

def create_cookies_file_from_env():
    """
    Ortam değişkeninden (YOUTUBE_COOKIES) Base64 kodlu çerez içeriğini alıp
    geçici bir çerez dosyası oluşturur.
    Bu dosya, yt-dlp tarafından kullanılacak ve işlem sonunda silinecektir.
    """
    cookies_base64 = os.environ.get('YOUTUBE_COOKIES')
    if cookies_base64:
        try:
            cookies_content = base64.b64decode(cookies_base64).decode('utf-8')
            with open(COOKIES_FILE_PATH, 'w') as f:
                f.write(cookies_content)
            print(f"Çerez dosyası oluşturuldu: {COOKIES_FILE_PATH}")
            return True
        except Exception as e:
            print(f"HATA: Çerez dosyası ortam değişkeninden oluşturulurken hata: {e}")
            return False
    print("UYARI: YOUTUBE_COOKIES ortam değişkeni bulunamadı veya boş. Çerezler kullanılmayacak.")
    return False

def extract_and_process_video_info(video_url, session_id):
    """
    Videodan bilgiyi çeker ve formatları ayıklar.
    İndirme durumunu günceller.
    """
    download_status[session_id] = {'status': 'extracting_info', 'progress': '0%'}
    cookies_successfully_created = create_cookies_file_from_env()

    try:
        ydl_info_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'skip_download': True, # Sadece bilgi çek, indirme yapma
            'retries': 3,
            'socket_timeout': 10,
        }
        if cookies_successfully_created:
            ydl_info_opts['cookiefile'] = COOKIES_FILE_PATH

        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(video_url, download=False) # download=False ile sadece bilgi çek
            
            # Videonun başlığını al
            # HATA DÜZELTİLDİ: 'for c c in title' yerine 'for c in title' olmalıydı.
            title = "".join([c for c in title if c.isalnum() or c in (' ', '.', '_', '-')]).rstrip()
            
            # Kullanılabilir formatları ayıkla
            available_formats = []
            if 'formats' in info:
                for f in info['formats']:
                    # Sadece video veya video+ses formatlarını al (ses formatlarını hariç tut)
                    # ve doğrudan bir URL'si olanları al
                    if f.get('url') and (f.get('vcodec') != 'none' or (f.get('vcodec') != 'none' and f.get('acodec') != 'none')):
                        quality = f.get('format_note') or f.get('format') or f.get('resolution') or 'Unknown Quality'
                        filesize = f.get('filesize') or f.get('filesize_approx') # Byte cinsinden
                        filesize_mb = round(filesize / (1024 * 1024), 2) if filesize else 'N/A' # MB cinsine çevir
                        
                        available_formats.append({
                            'format_id': f.get('format_id'),
                            'quality': quality,
                            'extension': f.get('ext'),
                            'filesize_mb': filesize_mb,
                            'direct_url': f.get('url') # Bu ARTIK DOĞRUDAN İNDİRME URL'Sİ
                        })
                # Kaliteye göre sırala (örneğin daha yüksek çözünürlük/bitrate önce gelsin)
                available_formats.sort(key=lambda x: x.get('filesize_mb', 0) if isinstance(x.get('filesize_mb'), (int, float)) else 0, reverse=True)
            
            if available_formats:
                download_status[session_id] = {
                    'status': 'formats_available',
                    'title': title,
                    'available_formats': available_formats
                }
                print(f"Formatlar başarıyla çekildi ({session_id}): {title}")
            else:
                download_status[session_id] = {'status': 'failed', 'error': 'Video formatları bulunamadı veya doğrudan indirme URL\'leri mevcut değil.'}
                print(f"Video formatları bulunamadı ({session_id}).")

    except Exception as e:
        download_status[session_id] = {'status': 'failed', 'error': f'Video bilgisi çekilirken hata: {e}'}
        print(f"Video bilgisi çekilirken hata: {e}")
    finally:
        # Hata oluştuğunda veya işlem bittiğinde geçici çerez dosyasını sil
        if os.path.exists(COOKIES_FILE_PATH):
            os.remove(COOKIES_FILE_PATH)
            print(f"Geçici çerez dosyası silindi: {COOKIES_FILE_PATH}")

# Bu fonksiyon artık kullanılmayacak, çünkü sunucu indirme yapmıyor.
# def download_specific_format_thread(...)

def update_progress(d, session_id):
    """
    Bu fonksiyon artık doğrudan indirme yapmadığımız için kullanılmayacak,
    ancak yt-dlp'nin bilgi çekme aşamasındaki ilerlemesi için tutulabilir.
    """
    if d['status'] == 'downloading': # Bu durum artık oluşmayacak
        p = d.get('_percent_str', 'N/A')
        download_status[session_id] = {'status': 'extracting_info', 'progress': p}
    elif d['status'] == 'finished': # Bu durum artık oluşmayacak
        download_status[session_id] = {'status': 'extracting_info', 'progress': '100%'}
    elif d['status'] == 'error':
        download_status[session_id] = {'status': 'failed', 'error': d.get('error', 'Bilinmeyen hata.')}

@app.route('/')
def index():
    """Ana sayfayı render eder."""
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def initiate_download():
    """
    Video bilgisi çekme işlemini başlatan endpoint.
    """
    video_url = request.form['video_url']
    if not video_url:
        flash('Lütfen bir video URL\'si girin!', 'error')
        return render_template('index.html')

    session_id = str(uuid.uuid4())
    download_status[session_id] = {'status': 'pending', 'progress': '0%'}

    # Bilgi çekme işlemini ayrı bir thread'de başlat
    thread = threading.Thread(target=extract_and_process_video_info, args=(video_url, session_id))
    thread.start()

    flash(f'Video bilgisi çekiliyor! Lütfen bekleyin.', 'info')
    return render_template('index.html', session_id=session_id)

@app.route('/status/<session_id>')
def get_download_status(session_id):
    """
    Belirli bir indirme işleminin mevcut durumunu JSON olarak döndürür.
    """
    status_info = download_status.get(session_id, {'status': 'not_found', 'error': 'İşlem bulunamadı.'})
    
    # 'completed' durumu artık doğrudan dosya indirme anlamına gelmiyor,
    # formatlar çekildiğinde 'formats_available' olacak.
    # Bu endpoint sadece durumu bildirecek.
    
    return jsonify(status_info)

# Bu endpoint artık kullanılmayacak, çünkü sunucu dosya sunmuyor.
# @app.route('/download_selected_format', methods=['POST'])
# def download_selected_format():
#     ...

# Bu endpoint artık kullanılmayacak, çünkü sunucu dosya sunmuyor.
# @app.route('/download_file/<session_id>')
# def serve_downloaded_file(session_id):
#     ...

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
