from flask import Flask, render_template, request, send_file, flash
import yt_dlp
import os
import threading
import time

app = Flask(__name__)
app.secret_key = 'supersecretkey1234512345' # Flash mesajları için gerekli

DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# İndirme durumunu takip etmek için basit bir sözlük
download_status = {}

def download_video_thread(video_url, filename, session_id):
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, filename),
        'progress_hooks': [lambda d: update_progress(d, session_id)],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            download_status[session_id] = {'status': 'completed', 'filepath': os.path.join(DOWNLOAD_FOLDER, filename)}
            print(f"Video downloaded to: {os.path.join(DOWNLOAD_FOLDER, filename)}")
    except Exception as e:
        download_status[session_id] = {'status': 'failed', 'error': str(e)}
        print(f"Error downloading video: {e}")

def update_progress(d, session_id):
    if d['status'] == 'downloading':
        p = d['_percent_str']
        download_status[session_id] = {'status': 'downloading', 'progress': p}
        print(f"Downloading for {session_id}: {p}")
    elif d['status'] == 'finished':
        download_status[session_id] = {'status': 'processing'}
        print(f"Finished downloading raw for {session_id}, now processing...")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    video_url = request.form['video_url']
    if not video_url:
        flash('Lütfen bir video URL\'si girin!', 'error')
        return render_template('index.html')

    # Basit bir session ID oluşturalım. Gerçek bir uygulamada daha sağlam bir mekanizma gerekebilir.
    session_id = str(time.time()).replace('.', '')

    # Dosya adını URL'den türetelim veya sabit bir ad verelim
    # Gerçek uygulamalarda dosya adı çakışmalarını engellemek için daha iyi bir strateji gerekir.
    try:
        with yt_dlp.YoutubeDL() as ydl:
            info = ydl.extract_info(video_url, download=False)
            title = info.get('title', 'video')
            # Geçersiz karakterleri temizle
            title = "".join([c for c in title if c.isalnum() or c in (' ', '.', '_', '-')]).rstrip()
            filename = f"{title}.mp4"
            filepath = os.path.join(DOWNLOAD_FOLDER, filename)
            # Eğer dosya zaten varsa, farklı bir isimle kaydet
            counter = 1
            while os.path.exists(filepath):
                filename = f"{title}_{counter}.mp4"
                filepath = os.path.join(DOWNLOAD_FOLDER, filename)
                counter += 1
    except Exception as e:
        flash(f'URL işlenirken hata oluştu: {e}', 'error')
        return render_template('index.html')

    download_status[session_id] = {'status': 'pending'}
    # İndirme işlemini ayrı bir thread'de başlat
    thread = threading.Thread(target=download_video_thread, args=(video_url, filename, session_id))
    thread.start()

    flash(f'Video indirme işlemi başlatıldı. Lütfen biraz bekleyin. İndirme durumu: /status/{session_id}', 'info')
    return render_template('index.html') # Kullanıcıyı ana sayfaya yönlendir

@app.route('/status/<session_id>')
def get_download_status(session_id):
    status_info = download_status.get(session_id, {'status': 'not_found'})
    return status_info # JSON olarak döndürülecek

@app.route('/download_file/<session_id>')
def download_file(session_id):
    status_info = download_status.get(session_id)
    if status_info and status_info['status'] == 'completed' and 'filepath' in status_info:
        filepath = status_info['filepath']
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True)
        else:
            flash('Dosya bulunamadı.', 'error')
            return "Dosya bulunamadı.", 404
    else:
        flash('Dosya henüz hazır değil veya bir hata oluştu.', 'error')
        return "Dosya henüz hazır değil veya bir hata oluştu.", 404

if __name__ == '__main__':
    app.run(debug=True)