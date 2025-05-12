# app.py
# Backend Flask application with SSE for download progress (Rebuilt)

import os
import re
import yt_dlp
import threading
import time
import uuid
import json
import copy
from flask import Flask, request, jsonify, send_from_directory, abort, Response, stream_with_context
from flask_cors import CORS
import logging

# --- الإعداد الأولي ---
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(name)s:%(message)s')
# السماح بالطلبات للـ API من أي مصدر (للتطوير) - يجب تقييده في الإنتاج
CORS(app, resources={r"/api/*": {"origins": "*"}})

DOWNLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)
app.config['DOWNLOAD_FOLDER'] = DOWNLOAD_FOLDER
app.logger.info(f"Download folder set to: {app.config['DOWNLOAD_FOLDER']}")

# --- قاموس لتتبع حالة مهام التنزيل ---
download_tasks = {}
tasks_lock = threading.Lock() # قفل لحماية الوصول المتزامن

# --- دالة لتنظيف اسم الملف ---
def sanitize_filename(filename):
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    max_len = 100
    if len(sanitized) > max_len:
        name_part, ext_part = os.path.splitext(sanitized)
        sanitized = name_part[:max_len - len(ext_part) - 3] + "..." + ext_part
    return sanitized if sanitized else "downloaded_file"

# --- خطاف التقدم المخصص ---
class ProgressHook:
    def __init__(self, task_id):
        self.task_id = task_id

    def __call__(self, d):
        task_id = self.task_id
        with tasks_lock:
            if task_id not in download_tasks: return # المهمة ربما ألغيت

            task_info = download_tasks[task_id]
            # تجنب تحديث الحالة إذا كانت المهمة قد انتهت بالفعل (خطأ أو نجاح)
            if task_info['status'] in ['finished', 'error']:
                 # app.logger.debug(f"Task {task_id}: Hook called after final state '{task_info['status']}'. Ignoring.")
                 return

            current_status = d['status']
            new_progress_data = task_info.get('progress', {}) # ابدأ من التقدم الحالي

            if current_status == 'downloading':
                task_info['status'] = 'downloading'
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded_bytes = d.get('downloaded_bytes', 0)
                percentage = (downloaded_bytes / total_bytes * 100) if total_bytes > 0 else 0
                new_progress_data = {
                    'percentage': round(percentage, 1),
                    'speed': d.get('_speed_str', 'N/A'),
                    'eta': d.get('_eta_str', 'N/A'),
                    'total_bytes': total_bytes,
                    'total_bytes_string': d.get('_total_bytes_str', 'N/A'),
                    'downloaded_bytes': downloaded_bytes
                }
            elif current_status == 'finished':
                 # تم الانتهاء من التنزيل أو المعالجة
                final_filename = d.get('filename') or task_info.get('filename')
                task_info['status'] = 'finished'
                task_info['filename'] = final_filename
                if final_filename:
                    task_info['download_url'] = f"/api/files/{os.path.basename(final_filename)}"
                new_progress_data = task_info.get('progress', {})
                new_progress_data['percentage'] = 100
                app.logger.info(f"Task {task_id}: Hook reported 'finished'. Filename: {final_filename}")

            elif current_status == 'error':
                task_info['status'] = 'error'
                task_info['error_message'] = "فشل خطاف التقدم في yt-dlp."
                app.logger.error(f"Task {task_id}: Hook reported 'error'.")

            # تحديث جزء التقدم
            task_info['progress'] = new_progress_data
            # تحديث القاموس الرئيسي
            download_tasks[task_id] = task_info


# --- دالة مهمة التنزيل في الخلفية ---
def run_download_task(task_id, video_url, selected_format):
    target_filename = None
    target_filepath = None
    try:
        with tasks_lock:
            if task_id not in download_tasks: return # تم الإلغاء قبل البدء
            download_tasks[task_id]['status'] = 'fetching_info'
        app.logger.info(f"Task {task_id}: [1/4] Fetching video info for {video_url}")

        # استخدام ydl_opts مبدئي لجلب المعلومات فقط
        info_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(info_opts) as ydl:
             info_dict = ydl.extract_info(video_url, download=False) # لا تحمل الآن

        video_title = info_dict.get('title', 'video')
        video_id = info_dict.get('id', 'unknown_id')
        target_extension = 'mp3' if selected_format == 'mp3' else 'mp4'
        base_filename = sanitize_filename(f"{video_title} [{video_id}]")
        target_filename = f"{base_filename}.{target_extension}"
        target_filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], target_filename)

        with tasks_lock:
            if task_id not in download_tasks: return
            download_tasks[task_id]['filename'] = target_filename # اسم مبدئي
            download_tasks[task_id]['status'] = 'preparing_download' # حالة جديدة
        app.logger.info(f"Task {task_id}: [2/4] Preparing download options. Target: {target_filepath}")

        # إعداد خيارات التنزيل الفعلية
        hook = ProgressHook(task_id)
        ydl_opts = {
            'noplaylist': True,
            'ignoreerrors': False, # التقاط الأخطاء
            'outtmpl': target_filepath, # مسار الملف الناتج
            'progress_hooks': [hook],
            'quiet': True, 'no_warnings': True,
            'format': None, 'postprocessors': [], 'merge_output_format': None,
            # إضافة خيارات للتعامل مع أخطاء الشبكة (اختياري)
            'retries': 5,             # عدد مرات إعادة المحاولة عند فشل تحميل جزء
            'fragment_retries': 5,    # عدد مرات إعادة المحاولة لتحميل الأجزاء (HLS/DASH)
            'socket_timeout': 30,     # مهلة الاتصال بالثواني
        }

        # تحديد الصيغة والمعالجات اللاحقة
        if selected_format == "mp3":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3','preferredquality': '192',},
                                         {'key': 'FFmpegMetadata','add_metadata': True,},
                                         {'key': 'EmbedThumbnail', 'already_have_thumbnail': False,}]
        else: # Video formats
            format_codes = { "best_video": 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                             "1080p": 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]',
                             "720p": 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
                             "480p": 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]',}
            format_option = format_codes.get(selected_format, format_codes["best_video"])
            ydl_opts['format'] = format_option
            ydl_opts['merge_output_format'] = 'mp4'

        # تحديث الحالة قبل البدء الفعلي
        with tasks_lock:
            if task_id not in download_tasks: return
            download_tasks[task_id]['status'] = 'downloading'
        app.logger.info(f"Task {task_id}: [3/4] Starting yt-dlp download process...")

        # البدء بالتحميل
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        app.logger.info(f"Task {task_id}: [4/4] yt-dlp process finished.")
        # التحقق النهائي (الخطاف يجب أن يكون قد أتم العمل)
        time.sleep(0.5) # إعطاء فرصة للخطاف للتحديث
        with tasks_lock:
            if task_id in download_tasks and download_tasks[task_id]['status'] not in ['finished', 'error']:
                app.logger.warning(f"Task {task_id}: Hook didn't set final status. Checking manually...")
                if target_filepath and os.path.exists(target_filepath):
                    download_tasks[task_id]['status'] = 'finished'
                    # التأكد من أن اسم الملف ورابط التحميل موجودان
                    if not download_tasks[task_id].get('filename'): download_tasks[task_id]['filename'] = target_filename
                    if not download_tasks[task_id].get('download_url'): download_tasks[task_id]['download_url'] = f"/api/files/{os.path.basename(target_filename)}"
                    if 'progress' not in download_tasks[task_id]: download_tasks[task_id]['progress'] = {}
                    download_tasks[task_id]['progress']['percentage'] = 100
                    app.logger.info(f"Task {task_id}: Manual check confirms file exists. Marked as finished.")
                else:
                    download_tasks[task_id]['status'] = 'error'
                    download_tasks[task_id]['error_message'] = 'فشل التحقق من الملف بعد انتهاء العملية.'
                    app.logger.error(f"Task {task_id}: Manual check found file missing. Marked as error.")

    except yt_dlp.utils.DownloadError as e:
        err_str = str(e)
        app.logger.error(f"Task {task_id}: DownloadError - {err_str}")
        with tasks_lock:
            if task_id in download_tasks:
                download_tasks[task_id]['status'] = 'error'
                if "ffmpeg was not found" in err_str or "ffmpeg is not installed" in err_str:
                    err_msg = "خطأ: تأكد من تثبيت ffmpeg وإضافته للـ PATH."
                elif "Unsupported URL" in err_str: err_msg = f"الرابط غير مدعوم."
                elif "Video unavailable" in err_str: err_msg = "الفيديو غير متاح."
                elif "HTTP Error 429" in err_str: err_msg = "خطأ: تم حظر الطلب مؤقتًا (Too Many Requests)."
                else: err_msg = f"خطأ تحميل: {err_str[:150]}..."
                download_tasks[task_id]['error_message'] = err_msg
    except Exception as e:
        app.logger.error(f"Task {task_id}: Unexpected error in background task", exc_info=True)
        with tasks_lock:
            if task_id in download_tasks:
                download_tasks[task_id]['status'] = 'error'
                download_tasks[task_id]['error_message'] = "حدث خطأ غير متوقع في الخادم."
    finally:
         app.logger.info(f"Task {task_id}: Background thread ended.")
         # يمكن إضافة منطق لتنظيف المهام القديمة جدًا هنا


# --- مسار بدء مهمة التنزيل ---
@app.route('/api/download', methods=['POST'])
def start_download_route():
    data = request.get_json()
    if not data: return jsonify({"success": False, "error": "بيانات الطلب مفقودة."}), 400
    video_url = data.get('video_url')
    selected_format = data.get('format')
    if not video_url or not selected_format:
        return jsonify({"success": False, "error": "معلومات الفيديو أو الصيغة مفقودة."}), 400

    task_id = uuid.uuid4().hex
    with tasks_lock:
        download_tasks[task_id] = {
            'status': 'pending', # الحالة الأولية
            'progress': {'percentage': 0, 'speed': '', 'eta': '', 'total_bytes': 0, 'total_bytes_string': '', 'downloaded_bytes': 0},
            'filename': None, 'download_url': None, 'error_message': None
        }

    thread = threading.Thread(target=run_download_task, args=(task_id, video_url, selected_format), daemon=True)
    thread.start()
    app.logger.info(f"Task {task_id}: Queued for {video_url} (Format: {selected_format})")
    return jsonify({"success": True, "task_id": task_id})


# --- مسار بث تحديثات التقدم (SSE) ---
@app.route('/api/stream/<task_id>')
def stream_progress_route(task_id):
    @stream_with_context
    def event_stream(current_task_id):
        last_sent_state_str = None
        app.logger.info(f"Stream {current_task_id}: Client connected.")
        try:
            while True:
                task_state_copy = None
                with tasks_lock:
                    task_state_original = download_tasks.get(current_task_id)
                    if task_state_original:
                        task_state_copy = copy.deepcopy(task_state_original) # نسخ آمن للقراءة

                if not task_state_copy:
                    app.logger.warning(f"Stream {current_task_id}: Task not found in dictionary.")
                    yield f"event: error\ndata: {json.dumps({'message': 'Task not found or removed.'})}\n\n"
                    break

                try:
                    json_data = json.dumps(task_state_copy)
                except TypeError as e:
                     app.logger.error(f"Stream {current_task_id}: Cannot serialize task state: {e}")
                     yield f"event: error\ndata: {json.dumps({'message': f'Internal serialization error: {e}'})}\n\n"
                     break

                # إرسال التحديث فقط إذا تغيرت الحالة
                if json_data != last_sent_state_str:
                    # app.logger.debug(f"Stream {current_task_id}: Sending state: {json_data}") # تفعيل للمتابعة الدقيقة
                    yield f"data: {json_data}\n\n"
                    last_sent_state_str = json_data

                # إيقاف البث إذا انتهت المهمة
                if task_state_copy['status'] in ['finished', 'error']:
                    app.logger.info(f"Stream {current_task_id}: Final state '{task_state_copy['status']}' sent. Closing stream.")
                    break

                time.sleep(0.5) # الانتظار بين التحديثات

        except GeneratorExit:
            app.logger.info(f"Stream {current_task_id}: Client disconnected.")
        except Exception as e:
             app.logger.error(f"Stream {current_task_id}: Unexpected error in generator", exc_info=True)
        finally:
            app.logger.info(f"Stream {current_task_id}: Event stream generator finished.")
            # Consider cleaning up very old tasks from download_tasks periodically elsewhere

    return Response(event_stream(task_id), mimetype='text/event-stream')


# --- مسار خدمة الملفات المحملة ---
@app.route('/api/files/<path:filename>')
def get_file(filename):
    app.logger.info(f"Request to serve file: {filename}")
    try:
        # الأمان: منع محاولة الوصول لملفات خارج مجلد التنزيلات
        safe_path = os.path.abspath(os.path.join(app.config['DOWNLOAD_FOLDER'], filename))
        if not safe_path.startswith(os.path.abspath(app.config['DOWNLOAD_FOLDER'])):
            app.logger.warning(f"Attempt to access file outside download folder: {filename}")
            abort(404)

        return send_from_directory(
            directory=app.config['DOWNLOAD_FOLDER'],
            path=filename, # اسم الملف كما هو مستلم
            as_attachment=True, # مهم لعرض نافذة الحفظ
            download_name=filename # اقتراح اسم الملف للمستخدم
        )
    except FileNotFoundError:
        app.logger.error(f"File not found for serving: {filename}")
        abort(404, description="الملف المطلوب غير موجود.")
    except Exception as e:
         app.logger.error(f"Error serving file {filename}", exc_info=True)
         abort(500, description="خطأ داخلي أثناء محاولة إرسال الملف.")


# --- تشغيل الخادم ---
if __name__ == '__main__':
    app.logger.info("Starting Flask development server (threaded)...")
    # Note: For production, use a proper WSGI server like Gunicorn with gevent workers
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)