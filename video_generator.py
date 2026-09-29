import os
import json
import threading
import time
import queue
import traceback
from database import get_db_connection
from ai_video_provider import GeminiPILVideoProvider, GoogleTTSProvider

# =========================================================================
# GLOBAL BACKGROUND QUEUE & WORKER ARCHITECTURE
# =========================================================================

class VideoGenerationQueueManager:
    """
    Thread-safe Queue Manager with Controlled Concurrency.
    Prevents server CPU saturation and supports:
    - Single module generation
    - Course bulk generation
    - Multi-course bulk generation
    - Pause / Resume / Cancel / Retry Failed
    """
    def __init__(self, max_workers: int = 2):
        self.max_workers = max_workers
        self.job_queue = queue.Queue()
        self.is_paused = False
        self.active_jobs = set() # Set of running job IDs
        self.lock = threading.Lock()
        self._init_workers()

    def _init_workers(self):
        for i in range(self.max_workers):
            t = threading.Thread(target=self._worker_loop, name=f"VideoWorker-{i+1}", daemon=True)
            t.start()

    def _worker_loop(self):
        while True:
            # Check if queue is paused
            if self.is_paused:
                time.sleep(1.0)
                continue

            try:
                job_data = self.job_queue.get(timeout=2.0)
            except queue.Empty:
                continue

            job_id = job_data["job_id"]
            module_id = job_data["module_id"]
            user_id = job_data["user_id"]
            custom_script = job_data.get("custom_script")

            with self.lock:
                self.active_jobs.add(job_id)

            try:
                _process_video_generation(job_id, module_id, user_id, custom_script)
            except Exception as e:
                print(f"[QueueWorker Exception] Job {job_id}: {e}")
            finally:
                with self.lock:
                    self.active_jobs.discard(job_id)
                self.job_queue.task_done()

    def enqueue(self, job_id, module_id, user_id, custom_script=None):
        self.job_queue.put({
            "job_id": job_id,
            "module_id": module_id,
            "user_id": user_id,
            "custom_script": custom_script
        })

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def get_status(self):
        return {
            "is_paused": self.is_paused,
            "queued_count": self.job_queue.qsize(),
            "active_running_count": len(self.active_jobs),
            "max_workers": self.max_workers
        }


# Singleton Queue Instance
queue_manager = VideoGenerationQueueManager(max_workers=2)


def _update_job_stage(conn, job_id, stage_name, progress_pct, status="IN_PROGRESS", error_msg=None, version_id=None):
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE ai_video_jobs 
    SET current_stage = ?, progress_pct = ?, status = ?, error_message = ?, version_id = COALESCE(?, version_id), updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (stage_name, progress_pct, status, error_msg, version_id, job_id))
    conn.commit()


def launch_async_video_generation(module_id, user_id, custom_script=None):
    """
    Creates a new generation job in DB and adds to controlled queue.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check for active running job for this module
    cursor.execute("""
    SELECT id, status FROM ai_video_jobs 
    WHERE module_id = ? AND status IN ('PENDING', 'IN_PROGRESS', 'QUEUED')
    """, (module_id,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return existing["id"], False # Job already active

    cursor.execute("""
    INSERT INTO ai_video_jobs (module_id, status, current_stage, progress_pct, created_by_user_id)
    VALUES (?, 'QUEUED', 'QUEUED in Generation Queue...', 5, ?)
    """, (module_id, user_id))
    job_id = cursor.lastrowid
    conn.commit()
    conn.close()

    queue_manager.enqueue(job_id, module_id, user_id, custom_script)
    return job_id, True


def launch_bulk_course_video_generation(course_id, user_id):
    """
    Enqueues video generation jobs for ALL modules belonging to a course.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, title, order_index FROM modules WHERE course_id = ? ORDER BY order_index ASC", (course_id,))
    modules = cursor.fetchall()
    
    enqueued_jobs = []
    already_active = []

    for m in modules:
        m_id = m["id"]
        # Check if already running
        cursor.execute("SELECT id, status FROM ai_video_jobs WHERE module_id = ? AND status IN ('PENDING', 'IN_PROGRESS', 'QUEUED')", (m_id,))
        active = cursor.fetchone()
        if active:
            already_active.append({"module_id": m_id, "job_id": active["id"]})
        else:
            cursor.execute("""
            INSERT INTO ai_video_jobs (module_id, status, current_stage, progress_pct, created_by_user_id)
            VALUES (?, 'QUEUED', 'QUEUED in Generation Queue...', 5, ?)
            """, (m_id, user_id))
            job_id = cursor.lastrowid
            queue_manager.enqueue(job_id, m_id, user_id)
            enqueued_jobs.append({"module_id": m_id, "job_id": job_id, "title": m["title"]})

    conn.commit()
    conn.close()
    return enqueued_jobs, already_active


def launch_bulk_all_courses_generation(user_id, course_ids=None):
    """
    Enqueues video generation for all modules across selected (or all) courses.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if course_ids:
        placeholders = ",".join("?" for _ in course_ids)
        cursor.execute(f"SELECT id FROM courses WHERE id IN ({placeholders})", course_ids)
    else:
        cursor.execute("SELECT id FROM courses WHERE is_published = 1")

    courses = cursor.fetchall()
    conn.close()

    total_enqueued = []
    total_skipped = []

    for c in courses:
        enq, skip = launch_bulk_course_video_generation(c["id"], user_id)
        total_enqueued.extend(enq)
        total_skipped.extend(skip)

    return total_enqueued, total_skipped


def retry_failed_video_job(job_id, user_id):
    """
    Retries a failed job by resetting status to QUEUED and re-adding to queue.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM ai_video_jobs WHERE id = ?", (job_id,))
    job = cursor.fetchone()
    if not job:
        conn.close()
        return False, "Job not found."

    cursor.execute("""
    UPDATE ai_video_jobs 
    SET status = 'QUEUED', current_stage = 'Retrying job in queue...', progress_pct = 5, error_message = NULL, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (job_id,))
    conn.commit()
    conn.close()

    queue_manager.enqueue(job_id, job["module_id"], user_id)
    return True, "Job re-enqueued successfully!"


def cancel_video_job(job_id):
    """
    Cancels a pending or queued job.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE ai_video_jobs SET status = 'CANCELLED', current_stage = 'Cancelled by administrator', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return True, "Job cancelled."


# =========================================================================
# CORE PROCESSING PIPELINE WORKER
# =========================================================================

def _process_video_generation(job_id, module_id, user_id, custom_script=None):
    conn = get_db_connection()
    try:
        # Check if job was cancelled while queued
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM ai_video_jobs WHERE id = ?", (job_id,))
        job_status = cursor.fetchone()
        if job_status and job_status["status"] == "CANCELLED":
            conn.close()
            return

        _update_job_stage(conn, job_id, "ANALYZING module content & prerequisites...", 15)

        # 1. Fetch Module & Course Info
        cursor.execute("SELECT * FROM modules WHERE id = ?", (module_id,))
        module_row = cursor.fetchone()
        if not module_row:
            _update_job_stage(conn, job_id, "Module not found", 0, status="FAILED", error_msg="Module ID does not exist.")
            conn.close()
            return

        module_dict = dict(module_row)

        cursor.execute("SELECT * FROM courses WHERE id = ?", (module_dict["course_id"],))
        course_row = cursor.fetchone()
        course_dict = dict(course_row) if course_row else {}

        cursor.execute("SELECT questions_json FROM assessments WHERE module_id = ?", (module_id,))
        ass_row = cursor.fetchone()
        assessment_questions = ass_row["questions_json"] if ass_row else "[]"

        # 2. Initialize Provider Engine
        provider = GeminiPILVideoProvider()

        if custom_script:
            storyboard_json = custom_script
            _update_job_stage(conn, job_id, "Using customized script storyboard...", 30)
        else:
            _update_job_stage(conn, job_id, "SCRIPT GENERATION — Building 10-scene lesson storyboard...", 30)
            storyboard_json = provider.generate_script_and_storyboard(module_dict, course_dict, assessment_questions)

        # 3. Output Directory Setup
        static_dir = os.path.join(os.path.dirname(__file__), "static", "videos", f"module_{module_id}")
        os.makedirs(static_dir, exist_ok=True)

        # Save storyboard JSON for audit & inspection
        with open(os.path.join(static_dir, "storyboard.json"), "w", encoding="utf-8") as f:
            json.dump(storyboard_json, f, indent=2)

        # 4. Audio & Subtitles Generation
        _update_job_stage(conn, job_id, "AUDIO GENERATION — Synthesizing English voice narration & WebVTT subtitles...", 55)
        audio_paths, vtt_path = provider.generate_audio_and_subtitles(storyboard_json, static_dir)

        # 5. Visual Slides Rendering
        _update_job_stage(conn, job_id, "VISUAL GENERATION — Rendering 1080p slide diagrams & live code cards...", 75)
        slide_paths = provider.render_scene_slides(storyboard_json, static_dir)

        # 6. Video Assembly via FFmpeg
        _update_job_stage(conn, job_id, "VIDEO RENDERING — Multiplexing slides + spoken voice into H.264 MP4...", 90)
        output_mp4 = os.path.join(static_dir, "lesson_video.mp4")
        scene_durations = [s.get("duration", 6) for s in storyboard_json.get("scenes", [])]
        provider.assemble_video(slide_paths, audio_paths, output_mp4, duration_per_scene=scene_durations)

        # Calculate Total Duration
        total_duration = sum(s.get("duration", 6) for s in storyboard_json.get("scenes", []))

        # Relative URLs for frontend serving
        rel_video_url = f"/static/videos/module_{module_id}/lesson_video.mp4"
        rel_vtt_url = f"/static/videos/module_{module_id}/subtitles.vtt"

        # 7. Create New Version Record
        cursor.execute("SELECT MAX(version_number) as max_v FROM ai_video_versions WHERE module_id = ?", (module_id,))
        max_v_row = cursor.fetchone()
        next_version = (max_v_row["max_v"] or 0) + 1 if max_v_row else 1

        cursor.execute("""
        INSERT INTO ai_video_versions (
            module_id, version_number, video_file_path, subtitle_file_path,
            duration_seconds, script_json, status
        ) VALUES (?, ?, ?, ?, ?, ?, 'DRAFT')
        """, (
            module_id, next_version, rel_video_url, rel_vtt_url,
            total_duration, json.dumps(storyboard_json)
        ))
        version_id = cursor.lastrowid

        # Automatically publish Version 1 by default, or keep draft for review if already published version exists
        cursor.execute("SELECT id FROM videos WHERE module_id = ?", (module_id,))
        has_published = cursor.fetchone()
        if not has_published:
            publish_ai_video_version(module_id, version_id, user_id)

        _update_job_stage(conn, job_id, "COMPLETED", 100, status="COMPLETED", version_id=version_id)

    except Exception as e:
        err_msg = f"Generation error: {str(e)}"
        print(f"[AI_VIDEO_GENERATOR_ERROR] {traceback.format_exc()}")
        _update_job_stage(conn, job_id, "Generation failed", 0, status="FAILED", error_msg=err_msg)
    finally:
        conn.close()


def publish_ai_video_version(module_id, version_id, admin_id):
    """
    Publishes a generated draft version as the active student video.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM ai_video_versions WHERE id = ? AND module_id = ?", (version_id, module_id))
    ver = cursor.fetchone()
    if not ver:
        conn.close()
        return False, "Video version not found."

    ver_dict = dict(ver)
    v_url = ver_dict["video_file_path"]
    sub_url = ver_dict["subtitle_file_path"]
    dur_sec = ver_dict["duration_seconds"]
    dur_str = f"{dur_sec // 60:02d}:{dur_sec % 60:02d}"

    cursor.execute("SELECT title FROM modules WHERE id = ?", (module_id,))
    mod = cursor.fetchone()
    mod_title = mod["title"] if mod else "Module Lesson"

    # Mark other version records superseded
    cursor.execute("UPDATE ai_video_versions SET status = 'SUPERSEDED' WHERE module_id = ? AND status = 'PUBLISHED'", (module_id,))
    cursor.execute("UPDATE ai_video_versions SET status = 'PUBLISHED' WHERE id = ?", (version_id,))

    # Update or insert into videos table
    cursor.execute("""
    INSERT INTO videos (
        module_id, title, provider, video_id, video_url, embed_url,
        professor, institution, source, duration, transcript,
        is_embeddable, video_file_path, subtitle_file_path, status,
        generation_provider, script_json, published_at
    ) VALUES (
        ?, ?, 'ai-video-studio', ?, ?, ?,
        'DEDCODE AI Tutor', 'DEDCODE Learning Platform', 'AI Video Studio', ?, 'Synchronized WebVTT Transcript',
        1, ?, ?, 'PUBLISHED', 'ai-video-studio', ?, CURRENT_TIMESTAMP
    )
    ON CONFLICT(module_id) DO UPDATE SET
        title = excluded.title,
        provider = 'ai-video-studio',
        video_url = excluded.video_url,
        embed_url = excluded.embed_url,
        duration = excluded.duration,
        video_file_path = excluded.video_file_path,
        subtitle_file_path = excluded.subtitle_file_path,
        status = 'PUBLISHED',
        script_json = excluded.script_json,
        published_at = CURRENT_TIMESTAMP
    """, (
        module_id, mod_title, f"ai-vid-{module_id}", v_url, v_url,
        dur_str, v_url, sub_url, ver_dict["script_json"]
    ))

    conn.commit()
    conn.close()
    return True, "AI Video successfully published to students!"


def unpublish_ai_video(module_id):
    """Unpublishes a module video so it can be revised."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE videos SET status = 'DRAFT' WHERE module_id = ?", (module_id,))
    cursor.execute("UPDATE ai_video_versions SET status = 'DRAFT' WHERE module_id = ? AND status = 'PUBLISHED'", (module_id,))
    conn.commit()
    conn.close()
    return True, "Video unpublished successfully."
