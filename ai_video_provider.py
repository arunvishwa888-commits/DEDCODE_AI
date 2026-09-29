import os
import json
import math
import wave
import struct
import re
import subprocess
from abc import ABC, abstractmethod
from PIL import Image, ImageDraw, ImageFont

# =========================================================================
# MODULAR TTS PROVIDER ABSTRACTION
# =========================================================================

class TTSProvider(ABC):
    """
    Abstract Base Class for text-to-speech voice narration synthesis.
    Supports easy swapping between Google TTS, macOS native voice,
    OpenAI TTS, and fallback synthetic tone generation.
    """
    @abstractmethod
    def synthesize_speech(self, text: str, output_path: str) -> float:
        """
        Synthesizes text into an audio file at output_path.
        Returns the duration of the audio in seconds.
        """
        pass


class GoogleTTSProvider(TTSProvider):
    """Production server-side English TTS using Google TTS (gTTS)."""
    def synthesize_speech(self, text: str, output_path: str) -> float:
        try:
            from gTTS import gTTS
            tts = gTTS(text=text, lang='en', tld='com')
            tts.save(output_path)
            
            # Estimate or calculate duration from word count (~2.6 words/sec, min 4s)
            word_count = len(text.split())
            duration = max(4.0, math.ceil(word_count / 2.6))
            return duration
        except Exception as e:
            print(f"[GoogleTTSProvider] Failed: {e}, falling back to MacNativeTTS...")
            mac_fallback = MacNativeTTSProvider()
            return mac_fallback.synthesize_speech(text, output_path)


class MacNativeTTSProvider(TTSProvider):
    """High-quality macOS native voice narration using /usr/bin/say."""
    def synthesize_speech(self, text: str, output_path: str) -> float:
        try:
            temp_aiff = output_path.replace(".mp3", ".aiff").replace(".wav", ".aiff")
            if temp_aiff == output_path:
                temp_aiff = output_path + ".aiff"

            # Use macOS say command with natural voice (Samantha, Alex, or Daniel)
            subprocess.run(["say", "-v", "Samantha", "-o", temp_aiff, text], check=True, capture_output=True)

            # Convert to target format using ffmpeg
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run([ffmpeg_exe, "-y", "-i", temp_aiff, "-c:a", "libmp3lame", "-b:a", "192k", output_path], check=True, capture_output=True)

            if os.path.exists(temp_aiff):
                os.remove(temp_aiff)

            word_count = len(text.split())
            duration = max(4.0, math.ceil(word_count / 2.6))
            return duration
        except Exception as e:
            print(f"[MacNativeTTSProvider] Failed: {e}, using LocalSynth fallback...")
            synth = LocalSynthProvider()
            return synth.synthesize_speech(text, output_path)


class OpenAITTSProvider(TTSProvider):
    """Cloud OpenAI TTS (alloy/echo/fable/onyx/nova/shimmer) when API key is configured."""
    def __init__(self, api_key: str = None, voice: str = "nova"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.voice = voice

    def synthesize_speech(self, text: str, output_path: str) -> float:
        if not self.api_key:
            fallback = GoogleTTSProvider()
            return fallback.synthesize_speech(text, output_path)
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            response = client.audio.speech.create(
                model="tts-1",
                voice=self.voice,
                input=text
            )
            response.stream_to_file(output_path)
            word_count = len(text.split())
            return max(4.0, math.ceil(word_count / 2.6))
        except Exception as e:
            print(f"[OpenAITTSProvider] Error: {e}, falling back to GoogleTTS...")
            fallback = GoogleTTSProvider()
            return fallback.synthesize_speech(text, output_path)


class LocalSynthProvider(TTSProvider):
    """Reliable fallback sine-wave educational audio generator requiring zero external APIs."""
    def synthesize_speech(self, text: str, output_path: str) -> float:
        word_count = len(text.split())
        duration = max(4.0, math.ceil(word_count / 2.6))
        sample_rate = 22050
        n_samples = int(sample_rate * duration)
        
        wav_path = output_path if output_path.endswith(".wav") else output_path.replace(".mp3", ".wav")
        with wave.open(wav_path, "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            for i in range(n_samples):
                t = float(i) / sample_rate
                value = int(1000.0 * math.sin(2.0 * math.pi * 220.0 * t) * (1.0 - (i / n_samples) * 0.5))
                data = struct.pack("<h", value)
                wav_file.writeframesraw(data)
                
        if output_path.endswith(".mp3"):
            try:
                import imageio_ffmpeg
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                subprocess.run([ffmpeg_exe, "-y", "-i", wav_path, "-c:a", "libmp3lame", "-b:a", "192k", output_path], check=True, capture_output=True)
                if os.path.exists(wav_path):
                    os.remove(wav_path)
            except Exception:
                pass
        return duration


# =========================================================================
# AI VIDEO PROVIDER ARCHITECTURE
# =========================================================================

class AIVideoProvider(ABC):
    """
    Provider-independent AI Video Architecture Base Class.
    Abstracts script generation, storyboard creation, visual rendering,
    audio narration, subtitles, and video assembly.
    """
    @abstractmethod
    def generate_script_and_storyboard(self, module_data, course_data, assessment_questions=None):
        pass

    @abstractmethod
    def render_scene_slides(self, script_data, output_dir):
        pass

    @abstractmethod
    def generate_audio_and_subtitles(self, script_data, output_dir):
        pass

    @abstractmethod
    def assemble_video(self, slide_image_paths, audio_paths, output_mp4_path, duration_per_scene=None):
        pass


class GeminiPILVideoProvider(AIVideoProvider):
    """
    Concrete Educational Video Provider generating high-definition 1080p
    video lessons with synchronized English narration, live code demonstrations,
    architectural flowcharts, and WebVTT subtitles.
    """

    def __init__(self, tts_provider: TTSProvider = None):
        self.width = 1920
        self.height = 1080
        # Default to GoogleTTS or MacNativeTTS
        self.tts = tts_provider or GoogleTTSProvider()

    def generate_script_and_storyboard(self, module_data, course_data, assessment_questions=None):
        """
        Builds a comprehensive 10-part educational teaching script directly from
        the module title, description, content, key concepts, and assessment questions.
        """
        course_title = course_data.get("title", "Software Engineering")
        module_title = module_data.get("title", "Lesson Module")
        module_desc = module_data.get("description", "")
        module_content = module_data.get("content", "")
        
        # Parse key concepts
        key_concepts = module_data.get("key_concepts_json") or []
        if isinstance(key_concepts, str):
            try:
                key_concepts = json.loads(key_concepts)
            except Exception:
                key_concepts = [module_title]
        if not key_concepts:
            key_concepts = [module_title, "Core Concepts", "Implementation & Practice", "Production Architecture"]

        # Extract real code snippet from module content if present
        code_snippets = []
        if "```" in (module_content or ""):
            matches = re.findall(r"```(?:\w+)?\n(.*?)```", module_content, re.DOTALL)
            code_snippets = [m.strip() for m in matches if m.strip()]

        if code_snippets:
            code_to_show = code_snippets[0]
        else:
            # Fallback code demo tailored to topic
            mod_lower = module_title.lower()
            if "python" in mod_lower or "numpy" in mod_lower or "data" in mod_lower:
                code_to_show = (
                    "import numpy as np\n\n"
                    "# 1. Initialize data matrix & inspect shape\n"
                    "data = np.array([[12.5, 45.2], [np.nan, 38.9], [19.8, 52.1]])\n"
                    "mean_val = np.nanmean(data, axis=0)\n\n"
                    "# 2. Vectorized NaN imputation & normalization\n"
                    "clean_matrix = np.where(np.isnan(data), mean_val, data)\n"
                    "standardized = (clean_matrix - np.mean(clean_matrix, axis=0)) / np.std(clean_matrix, axis=0)\n"
                    "print('Processed Shape:', standardized.shape)\n"
                    "print('Feature 1 Cleaned:', standardized[:, 0])"
                )
            elif "sql" in mod_lower or "database" in mod_lower:
                code_to_show = (
                    "-- Analytical Window Aggregation Pipeline\n"
                    "SELECT \n"
                    "    user_id,\n"
                    "    course_id,\n"
                    "    score,\n"
                    "    AVG(score) OVER(PARTITION BY course_id) as cohort_average,\n"
                    "    DENSE_RANK() OVER(PARTITION BY course_id ORDER BY score DESC) as rank\n"
                    "FROM learning_progress\n"
                    "WHERE score >= 70\n"
                    "ORDER BY course_id, rank ASC;"
                )
            else:
                code_to_show = (
                    f"# {module_title} — Production Pipeline Implementation\n"
                    "from dataclasses import dataclass\n\n"
                    "@dataclass\n"
                    "class ModulePipeline:\n"
                    "    name: str\n"
                    "    is_active: bool = True\n\n"
                    "    def execute(self, payload: dict) -> dict:\n"
                    "        # Validate and transform input stream\n"
                    "        assert payload is not None, 'Payload cannot be null'\n"
                    "        return {'status': 'SUCCESS', 'result': payload}\n\n"
                    "pipeline = ModulePipeline(name='ProductionEngine')\n"
                    "print(pipeline.execute({'batch_size': 64}))"
                )

        # Parse assessment question for interactive check
        questions_list = []
        if assessment_questions:
            if isinstance(assessment_questions, str):
                try:
                    questions_list = json.loads(assessment_questions)
                except Exception:
                    pass
            elif isinstance(assessment_questions, list):
                questions_list = assessment_questions

        quiz_q = questions_list[0].get("question", f"How do you apply {module_title} in production?") if questions_list else f"What is the key takeaway of {module_title}?"

        # Construct Comprehensive 10-Part Teaching Storyboard
        storyboard = {
            "course_title": course_title,
            "module_title": module_title,
            "scenes": [
                {
                    "scene_num": 1,
                    "type": "INTRO",
                    "header": "DEDCODE AI EDUCATIONAL SYSTEM",
                    "title": module_title,
                    "subtitle": f"Course: {course_title}",
                    "narration": f"Welcome to this lesson on {module_title} in the {course_title} curriculum. In this module, we will master the core foundations, analyze practical implementation code, and review production deployment workflows.",
                    "duration": 7
                },
                {
                    "scene_num": 2,
                    "type": "OBJECTIVES",
                    "header": "LEARNING OBJECTIVES",
                    "title": "What You Will Master Today",
                    "bullet_points": key_concepts[:4],
                    "narration": f"By the end of this lesson, you will master: {', '.join(key_concepts[:3])}. We will cover both the theoretical foundations and hands-on coding requirements.",
                    "duration": 8
                },
                {
                    "scene_num": 3,
                    "type": "CONCEPT_EXPLANATION",
                    "header": "THEORETICAL FOUNDATION",
                    "title": f"Understanding {module_title}",
                    "text_body": module_desc or f"Explore the foundational architecture, design principles, and engineering methodologies behind {module_title}.",
                    "highlight": key_concepts[0] if key_concepts else module_title,
                    "narration": f"{module_desc or f'Let us first examine the core architecture of {module_title}. Understanding how data and state interact is fundamental for building reliable software.'}",
                    "duration": 8
                },
                {
                    "scene_num": 4,
                    "type": "VISUAL_DIAGRAM",
                    "header": "ARCHITECTURAL WORKFLOW",
                    "title": "Data Pipeline & Execution Flow",
                    "diagram_steps": [
                        "1. Data Ingestion & Input",
                        "2. Transformation & Cleaning",
                        "3. Execution & Processing",
                        "4. Output & State Persistence"
                    ],
                    "narration": "Notice how data flows through our system architecture. Each stage isolates errors, enforces type validation, and maintains state consistency across pipelines.",
                    "duration": 8
                },
                {
                    "scene_num": 5,
                    "type": "CODE_DEMO",
                    "header": "LIVE CODE DEMONSTRATION",
                    "title": "Source Code Syntax & Implementation",
                    "code": code_to_show,
                    "expected_output": f"✓ {module_title} pipeline executed cleanly",
                    "narration": "Now let us examine the live implementation code. Notice the clean function signatures, vectorized data handling, and structured output formatting.",
                    "duration": 10
                },
                {
                    "scene_num": 6,
                    "type": "COMMON_MISTAKES",
                    "header": "COMMON PITFALLS & SOLUTIONS",
                    "title": "Key Anti-Patterns to Avoid",
                    "pitfalls": [
                        f"Unhandled exceptions or silent failures during {module_title} execution",
                        "Mutating global state or leaking training distributions into validation sets",
                        "Omitting boundary checks on edge-case inputs and empty datasets"
                    ],
                    "narration": "Avoid common pitfalls such as unhandled boundary exceptions and unintended state mutations. Always enforce strict input validation and immutable data structures.",
                    "duration": 8
                },
                {
                    "scene_num": 7,
                    "type": "PRACTICAL_EXAMPLE",
                    "header": "PRODUCTION SCENARIO",
                    "title": "Industry Deployment Workflow",
                    "scenario": f"Deploying {module_title} pipelines in production microservices with automated telemetry, fault tolerance, and low latency.",
                    "narration": "In real-world engineering, this pattern ensures high throughput, resilient failover, and predictable performance across distributed production systems.",
                    "duration": 8
                },
                {
                    "scene_num": 8,
                    "type": "MINI_CHALLENGE",
                    "header": "CHECK YOUR UNDERSTANDING",
                    "title": "Knowledge Assessment Challenge",
                    "question": quiz_q,
                    "narration": f"Here is a quick concept check: {quiz_q}. Consider how you would approach this using the principles we just discussed.",
                    "duration": 8
                },
                {
                    "scene_num": 9,
                    "type": "RECAP",
                    "header": "KEY TAKEAWAYS",
                    "title": "Summary of Core Concepts",
                    "takeaways": [
                        f"Mastered core principles of {module_title}",
                        "Implemented modular, production-ready code syntax",
                        "Understood error boundaries, performance optimizations, and anti-patterns"
                    ],
                    "narration": "To summarize: we covered the core principles, verified the code implementation, and established key best practices for production development.",
                    "duration": 7
                },
                {
                    "scene_num": 10,
                    "type": "OUTRO",
                    "header": "MODULE COMPLETED",
                    "title": "Great Job! Take the Assessment",
                    "subtitle": "Complete the quiz below to unlock the next module and earn Learning Credits!",
                    "narration": "Great job completing this lesson! Head over to the Module Assessment below to verify your skills and unlock the next milestone in your curriculum.",
                    "duration": 6
                }
            ]
        }
        return storyboard

    def _get_font(self, size, is_bold=False):
        """Cross-platform font loader with macOS, Linux, and Windows standard fallbacks."""
        font_candidates = [
            # macOS fonts
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFPro.ttf",
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if is_bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
            # Linux fonts
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if is_bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if is_bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            # Windows fonts
            "C:\\Windows\\Fonts\\arialbd.ttf" if is_bold else "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf"
        ]
        for path in font_candidates:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def render_scene_slides(self, storyboard_json, output_dir):
        """Renders crystal-clear 1080p slide graphics for each scene in the storyboard."""
        os.makedirs(output_dir, exist_ok=True)
        image_paths = []
        
        scenes = storyboard_json.get("scenes", [])
        for scene in scenes:
            scene_num = scene.get("scene_num", 1)
            img = Image.new("RGB", (self.width, self.height), color="#0F141C")
            draw = ImageDraw.Draw(img)

            # Outer Card Canvas Container
            draw.rectangle([(50, 50), (self.width - 50, self.height - 50)], outline="#262F3D", width=2, fill="#161D27")
            
            # Top Header Bar
            draw.rectangle([(50, 50), (self.width - 50, 150)], fill="#FF684F")
            header_text = scene.get("header", "DEDCODE AI LESSON")
            font_header = self._get_font(34, is_bold=True)
            draw.text((90, 85), header_text, fill="#FFFFFF", font=font_header)

            # Scene Title
            title_text = scene.get("title", "")
            font_title = self._get_font(48, is_bold=True)
            draw.text((90, 185), title_text, fill="#F7FAFC", font=font_title)

            scene_type = scene.get("type", "")

            if scene_type == "INTRO":
                font_sub = self._get_font(38)
                draw.text((90, 290), scene.get("subtitle", ""), fill="#A0AEC0", font=font_sub)
                
                # Decorative DEDCODE Showcase Card
                draw.rectangle([(90, 380), (self.width - 90, 800)], fill="#1E2633", outline="#3B4758", width=2)
                draw.text((140, 450), f"Course: {storyboard_json.get('course_title', '')}", fill="#FF684F", font=self._get_font(44, is_bold=True))
                draw.text((140, 550), f"Module: {storyboard_json.get('module_title', '')}", fill="#FFFFFF", font=self._get_font(44, is_bold=True))
                draw.text((140, 650), "AI Interactive Video Lesson • Full English Narration • 1080p HD", fill="#CBD5E0", font=self._get_font(30))

            elif scene_type == "OBJECTIVES":
                bullets = scene.get("bullet_points", [])
                font_bullet = self._get_font(36)
                y_pos = 290
                for bp in bullets:
                    draw.ellipse([(90, y_pos + 10), (114, y_pos + 34)], fill="#FF684F")
                    draw.text((140, y_pos), bp, fill="#E2E8F0", font=font_bullet)
                    y_pos += 85

            elif scene_type == "CONCEPT_EXPLANATION":
                font_body = self._get_font(34)
                body = scene.get("text_body", "")
                words = body.split(" ")
                lines, curr_line = [], ""
                for w in words:
                    if len(curr_line + " " + w) < 72:
                        curr_line += " " + w
                    else:
                        lines.append(curr_line)
                        curr_line = w
                if curr_line:
                    lines.append(curr_line)

                y_pos = 280
                for line in lines[:5]:
                    draw.text((90, y_pos), line.strip(), fill="#CBD5E0", font=font_body)
                    y_pos += 52

                highlight = scene.get("highlight")
                if highlight:
                    draw.rectangle([(90, 640), (self.width - 90, 780)], fill="#1A365D", outline="#2B6CB0", width=2)
                    draw.text((120, 670), "KEY CONCEPT HIGHLIGHT:", fill="#90CDF4", font=self._get_font(26, is_bold=True))
                    draw.text((120, 710), highlight, fill="#FFFFFF", font=self._get_font(38, is_bold=True))

            elif scene_type == "VISUAL_DIAGRAM":
                steps = scene.get("diagram_steps", [])
                x_pos = 90
                font_step = self._get_font(28, is_bold=True)
                for idx, step in enumerate(steps):
                    box_rect = [(x_pos, 380), (x_pos + 370, 640)]
                    draw.rectangle(box_rect, fill="#1E2633", outline="#FF684F", width=2)
                    draw.text((x_pos + 20, 420), f"PHASE 0{idx+1}", fill="#FF684F", font=self._get_font(22, is_bold=True))
                    
                    txt = step.replace(f"{idx+1}. ", "")
                    draw.text((x_pos + 20, 480), txt[:22], fill="#FFFFFF", font=font_step)
                    
                    if idx < len(steps) - 1:
                        draw.line([(x_pos + 380, 510), (x_pos + 420, 510)], fill="#CBD5E0", width=4)
                    x_pos += 430

            elif scene_type == "CODE_DEMO":
                code_text = scene.get("code", "")
                draw.rectangle([(90, 270), (self.width - 90, 720)], fill="#0D1117", outline="#30363D", width=2)
                # macOS IDE Control Dots
                draw.ellipse([(110, 290), (126, 306)], fill="#FF5F56")
                draw.ellipse([(136, 290), (152, 306)], fill="#FFBD2E")
                draw.ellipse([(162, 290), (178, 306)], fill="#27C93F")
                draw.text((200, 288), "main.py — Code Implementation", fill="#8B949E", font=self._get_font(20))
                draw.line([(90, 320), (self.width - 90, 320)], fill="#30363D", width=2)
                
                font_code = self._get_font(28)
                code_lines = code_text.split("\n")
                y_pos = 340
                for line in code_lines[:8]:
                    draw.text((120, y_pos), line, fill="#79C0FF", font=font_code)
                    y_pos += 38

                # Output Console Box
                draw.rectangle([(90, 740), (self.width - 90, 840)], fill="#161B22", outline="#238636", width=2)
                draw.text((110, 755), "Terminal Output:", fill="#7EE787", font=self._get_font(20, is_bold=True))
                draw.text((110, 785), scene.get("expected_output", "Process finished with exit code 0"), fill="#FFFFFF", font=self._get_font(26))

            elif scene_type == "COMMON_MISTAKES":
                pitfalls = scene.get("pitfalls", [])
                font_pf = self._get_font(32)
                y_pos = 290
                for pf in pitfalls:
                    draw.rectangle([(90, y_pos), (self.width - 90, y_pos + 110)], fill="#441C1C", outline="#E53E3E", width=2)
                    draw.text((120, y_pos + 18), "⚠ ANTI-PATTERN & SOLUTION:", fill="#FEB2B2", font=self._get_font(22, is_bold=True))
                    draw.text((120, y_pos + 52), pf, fill="#FFFFFF", font=font_pf)
                    y_pos += 140

            elif scene_type == "PRACTICAL_EXAMPLE":
                scenario = scene.get("scenario", "")
                draw.rectangle([(90, 300), (self.width - 90, 750)], fill="#1A365D", outline="#3182CE", width=2)
                draw.text((130, 350), "PRODUCTION SCENARIO:", fill="#90CDF4", font=self._get_font(30, is_bold=True))
                
                words = scenario.split(" ")
                lines, curr = [], ""
                for w in words:
                    if len(curr + " " + w) < 60:
                        curr += " " + w
                    else:
                        lines.append(curr)
                        curr = w
                if curr:
                    lines.append(curr)
                
                y_p = 430
                for line in lines[:5]:
                    draw.text((130, y_p), line.strip(), fill="#FFFFFF", font=self._get_font(36))
                    y_p += 55

            elif scene_type == "MINI_CHALLENGE":
                draw.rectangle([(90, 290), (self.width - 90, 740)], fill="#233853", outline="#4299E1", width=2)
                draw.text((130, 350), "CONCEPT CHECK QUESTION:", fill="#BEE3F8", font=self._get_font(30, is_bold=True))
                draw.text((130, 440), scene.get("question", ""), fill="#FFFFFF", font=self._get_font(38, is_bold=True))
                draw.text((130, 600), "💡 Tip: Think about the data boundaries and edge cases!", fill="#F6AD55", font=self._get_font(30))

            elif scene_type == "RECAP":
                takeaways = scene.get("takeaways", [])
                font_tk = self._get_font(34)
                y_pos = 290
                for tk in takeaways:
                    draw.rectangle([(90, y_pos), (self.width - 90, y_pos + 100)], fill="#1C4532", outline="#38A169", width=2)
                    draw.text((120, y_pos + 30), f"✓  {tk}", fill="#FFFFFF", font=font_tk)
                    y_pos += 130

            elif scene_type == "OUTRO":
                draw.rectangle([(90, 290), (self.width - 90, 750)], fill="#1E2633", outline="#FF684F", width=3)
                draw.text((130, 360), "LESSON COMPLETED!", fill="#FF684F", font=self._get_font(52, is_bold=True))
                draw.text((130, 460), scene.get("subtitle", ""), fill="#E2E8F0", font=self._get_font(34))
                draw.rectangle([(130, 580), (560, 660)], fill="#FF684F")
                draw.text((160, 602), "Take Module Quiz →", fill="#FFFFFF", font=self._get_font(30, is_bold=True))

            # Footer Tag
            draw.text((90, self.height - 100), "DEDCODE AI Educational Video System • Continuous Learning", fill="#718096", font=self._get_font(22))

            out_path = os.path.join(output_dir, f"scene_{scene_num:02d}.png")
            img.save(out_path)
            image_paths.append(out_path)
            
        return image_paths

    def generate_audio_and_subtitles(self, storyboard_json, output_dir):
        """Synthesizes English audio narration per scene and builds synchronized WebVTT subtitles."""
        os.makedirs(output_dir, exist_ok=True)
        scenes = storyboard_json.get("scenes", [])
        audio_paths = []
        
        vtt_lines = ["WEBVTT", ""]
        current_time_sec = 0.0

        for idx, scene in enumerate(scenes):
            scene_num = scene.get("scene_num", idx + 1)
            narration_text = scene.get("narration", f"Scene {scene_num} explanation.")

            audio_filename = f"audio_{scene_num:02d}.mp3"
            audio_path = os.path.join(output_dir, audio_filename)
            
            # Synthesize narration via TTS provider
            duration = self.tts.synthesize_speech(narration_text, audio_path)
            scene["duration"] = duration
            audio_paths.append(audio_path)

            # Build WebVTT block
            start_formatted = self._format_vtt_timestamp(current_time_sec)
            end_formatted = self._format_vtt_timestamp(current_time_sec + duration)
            
            vtt_lines.append(f"{idx + 1}")
            vtt_lines.append(f"{start_formatted} --> {end_formatted}")
            vtt_lines.append(narration_text)
            vtt_lines.append("")

            current_time_sec += duration

        vtt_path = os.path.join(output_dir, "subtitles.vtt")
        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(vtt_lines))

        return audio_paths, vtt_path

    def _format_vtt_timestamp(self, seconds):
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{mins:02d}:{secs:02d}.{millis:03d}"

    def assemble_video(self, slide_image_paths, audio_paths, output_mp4_path, duration_per_scene=None):
        """Assembles slide image frames and narration audio into an H.264 MP4 with FFmpeg."""
        os.makedirs(os.path.dirname(output_mp4_path), exist_ok=True)
        work_dir = os.path.dirname(output_mp4_path)

        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

            # 1. Combine narration audio tracks into master narration MP3
            full_audio_path = os.path.join(work_dir, "master_narration.mp3")
            aud_concat_list = os.path.join(work_dir, "aud_concat.txt")
            with open(aud_concat_list, "w", encoding="utf-8") as f:
                for a_path in audio_paths:
                    filename = os.path.basename(a_path)
                    f.write(f"file '{filename}'\n")

            cmd_concat_audio = [
                ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
                "-i", aud_concat_list, "-c", "copy", full_audio_path
            ]
            subprocess.run(cmd_concat_audio, check=True, capture_output=True)

            # 2. Build slide concat manifest with durations matching narration
            slides_concat_list = os.path.join(work_dir, "slides_concat.txt")
            with open(slides_concat_list, "w", encoding="utf-8") as f:
                for idx, img_path in enumerate(slide_image_paths):
                    img_name = os.path.basename(img_path)
                    dur = 6
                    if duration_per_scene and idx < len(duration_per_scene):
                        dur = duration_per_scene[idx]
                    f.write(f"file '{img_name}'\nduration {dur}\n")
                if slide_image_paths:
                    f.write(f"file '{os.path.basename(slide_image_paths[-1])}'\n")

            # 3. Multiplex slide visuals + master narration audio into final MP4
            cmd_build_video = [
                ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
                "-i", slides_concat_list, "-i", full_audio_path,
                "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p", "-shortest", output_mp4_path
            ]
            subprocess.run(cmd_build_video, check=True, capture_output=True)

            print(f"[AIVideoProvider] MP4 assembled successfully: {output_mp4_path}")
            return output_mp4_path

        except Exception as e:
            print(f"[AIVideoProvider ERROR] FFmpeg assembly: {e}")
            raise e
