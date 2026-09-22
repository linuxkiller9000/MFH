import os
import subprocess
import threading
import time
import wave
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime

import cv2
import mss
import numpy as np
import imageio
import imageio_ffmpeg
import pyaudiowpatch as pyaudio
import pygame
from PIL import Image, ImageTk

# Optional native OS drag & drop. The app still works normally if tkinterdnd2
# is not installed; install it with: pip install tkinterdnd2
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

RESOLUTIONS = {
    "4K (2160p)": (3840, 2160),
    "1080p (Full HD)": (1920, 1080),
    "720p (HD)": (1280, 720),
    "480p (SD)": (854, 480),
    "360p (Low)": (640, 360),
    "240p (Very Low)": (426, 240),
    "144p (Ultra Low)": (256, 144),
}

def get_all_audio_devices():
    p = pyaudio.PyAudio()
    labels = []
    indices = []

    try:
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice") or dev.get("maxInputChannels", 0) > 0:
                name = dev.get("name", f"Device {i}")
                labels.append(f"{name} [ID: {i}]")
                indices.append(i)

        if not indices:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_output_id = wasapi_info.get("defaultOutputDevice")
            if default_output_id is not None:
                default_speakers = p.get_device_info_by_index(default_output_id)
                loopback = p.get_wasapi_loopback_analogue_by_dict(default_speakers)
                labels.append(f"System Audio ({loopback['name']})")
                indices.append(loopback["index"])

    except Exception as e:
        print(f"[Audio Scan Error] {e}")
    finally:
        p.terminate()

    return labels, indices


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, current_res, current_fps, current_audio_idx, show_mouse, audio_labels, audio_indices):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("380x360")
        self.resizable(False, False)
        self.configure(bg="#2d2d30")
        self.transient(parent)
        self.grab_set()

        self.result = None
        self.audio_indices = audio_indices

        tk.Label(self, text="Video Resolution", bg="#2d2d30", fg="#ffffff", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20, pady=(15, 2))
        self.combo_res = ttk.Combobox(self, values=list(RESOLUTIONS.keys()), state="readonly")
        self.combo_res.set(current_res)
        self.combo_res.pack(fill="x", padx=20, pady=(0, 10))

        tk.Label(self, text="Target Framerate", bg="#2d2d30", fg="#ffffff", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20, pady=(5, 2))
        self.combo_fps = ttk.Combobox(self, values=["60 FPS", "30 FPS", "15 FPS"], state="readonly")
        self.combo_fps.set(current_fps)
        self.combo_fps.pack(fill="x", padx=20, pady=(0, 10))

        tk.Label(self, text="Audio Input Device", bg="#2d2d30", fg="#ffffff", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20, pady=(5, 2))
        self.combo_audio = ttk.Combobox(self, values=audio_labels, state="readonly")
        if audio_labels:
            if current_audio_idx in audio_indices:
                self.combo_audio.current(audio_indices.index(current_audio_idx))
            else:
                self.combo_audio.current(0)
        self.combo_audio.pack(fill="x", padx=20, pady=(0, 15))

        self.var_mouse = tk.BooleanVar(value=show_mouse)
        self.chk_mouse = tk.Checkbutton(
            self, text="Show Mouse Cursor in Recording", variable=self.var_mouse,
            bg="#2d2d30", fg="#ffffff", selectcolor="#3e3e42", activebackground="#2d2d30", activeforeground="#ffffff", font=("Segoe UI", 9)
        )
        self.chk_mouse.pack(anchor="w", padx=20, pady=(0, 15))

        btn_box = tk.Frame(self, bg="#2d2d30")
        btn_box.pack(fill="x", padx=20)
        
        btn_save = tk.Button(btn_box, text="Save Settings", bg="#007acc", fg="#ffffff", relief="flat", font=("Segoe UI", 9, "bold"), command=self.on_save)
        btn_save.pack(side="right")

    def on_save(self):
        sel_audio_idx = None
        if self.audio_indices and self.combo_audio.current() != -1:
            sel_audio_idx = self.audio_indices[self.combo_audio.current()]
            
        self.result = {
            "res": self.combo_res.get(),
            "fps": self.combo_fps.get(),
            "audio_idx": sel_audio_idx,
            "show_mouse": self.var_mouse.get()
        }
        self.destroy()


class MFHScreenRecorder(TkinterDnD.Tk if DND_AVAILABLE else tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MFH Screen Recorder Pro - v1.0")
        self.geometry("1120x720")
        self.minsize(950, 620)
        
        # Optional Cat Icon Handler (expects cat_icon.png in working directory or skips smoothly)
        if os.path.exists("cat_icon.png"):
            try:
                self.iconphoto(False, tk.PhotoImage(file="cat_icon.png"))
            except Exception:
                pass

        pygame.mixer.init()

        self.output_dir = os.getcwd()
        self.is_recording = False
        self.is_paused = False
        self.start_time = None
        self.pause_start_time = None
        self.total_paused_duration = 0
        self.audio_delay_ms = 0
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()

        self.audio_labels, self.audio_indices = get_all_audio_devices()
        self.selected_res = "1080p (Full HD)"
        self.selected_fps = "30 FPS"
        self.selected_audio_idx = self.audio_indices[0] if self.audio_indices else None
        self.show_mouse_cursor = True

        self.audio_levels = [0.0] * 50
        self.file_paths = {}

        # Video Player variables & thread lock
        self.player_cap = None
        self.is_playing_video = False
        self.player_thread = None
        self.player_lock = threading.Lock()
        self.total_frames = 0
        self.current_frame_idx = 0
        self.is_seeking = False
        self.current_video_path = None
        self.temp_audio_extract_path = os.path.join(os.getcwd(), "temp_player_audio.wav")
        self.player_fps = 30.0
        self.player_audio_loaded = False
        self.player_generation = 0

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._setup_theme()
        self._build_menu()
        self._build_ui()
        self._setup_drag_and_drop()
        self.bind("<space>", lambda e: self._toggle_playback())
        self.bind("<Left>", lambda e: self._nudge_player(-5))
        self.bind("<Right>", lambda e: self._nudge_player(5))
        self.bind("<Control-o>", lambda e: self._choose_video_file())
        self._refresh_file_tree()
        self._update_loop()

    def _setup_theme(self):
        self.configure(bg="#2d2d30")
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.style.configure(".", background="#2d2d30", foreground="#ffffff")
        self.style.configure("TNotebook", background="#3e3e42", borderwidth=0)
        self.style.configure("TNotebook.Tab", background="#252526", foreground="#cccccc", padding=[12, 5], font=("Segoe UI", 9))
        self.style.map("TNotebook.Tab", background=[("selected", "#007acc")], foreground=[("selected", "#ffffff")])

        self.style.configure("Treeview", background="#252526", foreground="#ffffff", fieldbackground="#252526", borderwidth=0, font=("Segoe UI", 9))
        self.style.configure("Treeview.Heading", background="#333337", foreground="#ffffff", font=("Segoe UI", 9, "bold"))
        self.style.map("Treeview", background=[("selected", "#007acc")])
        self.style.configure(
            "TScale",
            background="#252526",
            troughcolor="#1e1e1e",
            borderwidth=0
        )

    def _build_menu(self):
        menubar = tk.Menu(self, bg="#333337", fg="#ffffff", activebackground="#007acc", activeforeground="#ffffff", bd=0)
        
        file_menu = tk.Menu(menubar, tearoff=0, bg="#2d2d30", fg="#ffffff", activebackground="#007acc", activeforeground="#ffffff")
        file_menu.add_command(label="Save As / Select Directory...", command=self._choose_output_dir)
        file_menu.add_command(label="Set to Current Directory", command=self._set_current_dir)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        settings_menu = tk.Menu(menubar, tearoff=0, bg="#2d2d30", fg="#ffffff", activebackground="#007acc", activeforeground="#ffffff")
        settings_menu.add_command(label="Configure Settings...", command=self._open_settings)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        self.config(menu=menubar)

    def _build_ui(self):
        header_frame = tk.Frame(self, bg="#333337", height=35)
        header_frame.pack(fill="x", side="top")
        
        header_inner = tk.Frame(header_frame, bg="#333337")
        header_inner.pack(fill="x", padx=12, pady=5)

        lbl_title = tk.Label(
            header_inner, text="MFH Screen Recorder Pro",
            font=("Segoe UI", 11, "bold"), bg="#333337", fg="#ffffff"
        )
        lbl_title.pack(side="left")

        lbl_version = tk.Label(
            header_inner, text="v1.1  •  Record · Preview · Play",
            font=("Segoe UI", 8), bg="#333337", fg="#888888"
        )
        lbl_version.pack(side="left", padx=(10, 0))

        self.lbl_dnd = tk.Label(
            header_inner,
            text="↳ Drop a video anywhere to open it" if DND_AVAILABLE else "Drag & drop: install tkinterdnd2",
            font=("Segoe UI", 8),
            bg="#333337",
            fg="#00d2ff" if DND_AVAILABLE else "#888888"
        )
        self.lbl_dnd.pack(side="right")

        workspace = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg="#2d2d30", bd=0, sashwidth=4)
        workspace.pack(fill="both", expand=True, padx=5, pady=5)

        left_panel = tk.Frame(workspace, bg="#252526", width=260)
        workspace.add(left_panel, minsize=210)

        mode_card = tk.LabelFrame(left_panel, text=" Capture Mode ", bg="#252526", fg="#aaaaaa", font=("Segoe UI", 9, "bold"), bd=1, relief="solid")
        mode_card.pack(fill="x", padx=8, pady=8)

        self.mode_var = tk.StringVar(value="both")
        rb_audio = tk.Radiobutton(mode_card, text="Audio Only", variable=self.mode_var, value="audio", bg="#252526", fg="#ffffff", selectcolor="#333337", activebackground="#252526", activeforeground="#ffffff")
        rb_vid = tk.Radiobutton(mode_card, text="Video Only", variable=self.mode_var, value="video", bg="#252526", fg="#ffffff", selectcolor="#333337", activebackground="#252526", activeforeground="#ffffff")
        rb_both = tk.Radiobutton(mode_card, text="Both", variable=self.mode_var, value="both", bg="#252526", fg="#ffffff", selectcolor="#333337", activebackground="#252526", activeforeground="#ffffff")
        
        rb_audio.pack(anchor="w", padx=10, pady=2)
        rb_vid.pack(anchor="w", padx=10, pady=2)
        rb_both.pack(anchor="w", padx=10, pady=2)

        tree_card = tk.LabelFrame(
            left_panel, text=" Media Library  •  Double-click to play ",
            bg="#252526", fg="#aaaaaa", font=("Segoe UI", 9, "bold"),
            bd=1, relief="solid"
        )
        tree_card.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        tree_toolbar = tk.Frame(tree_card, bg="#252526")
        tree_toolbar.pack(fill="x", padx=7, pady=(7, 4))

        self.btn_refresh_files = tk.Button(
            tree_toolbar, text="↻ Refresh", bg="#3e3e42", fg="#ffffff",
            activebackground="#4e4e52", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 8, "bold"),
            command=self._refresh_file_tree, cursor="hand2"
        )
        self.btn_refresh_files.pack(side="left")

        self.lbl_library_hint = tk.Label(
            tree_toolbar, text="Drop files/folders here",
            bg="#252526", fg="#777777", font=("Segoe UI", 8)
        )
        self.lbl_library_hint.pack(side="right")


        self.file_tree = ttk.Treeview(tree_card, columns=("size"), show="tree headings")
        self.file_tree.heading("#0", text="Recordings", anchor="w")
        self.file_tree.heading("size", text="Size", anchor="e")
        self.file_tree.column("#0", stretch=True)
        self.file_tree.column("size", width=65, stretch=False, anchor="e")
        self.file_tree.pack(fill="both", expand=True)
        self.file_tree.bind("<Double-1>", self._on_file_double_click)

        right_panel = tk.Frame(workspace, bg="#2d2d30")
        workspace.add(right_panel, minsize=400)

        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill="both", expand=True)

        # Tab 1: Live Preview
        self.preview_tab = tk.Frame(self.notebook, bg="#333337")
        self.notebook.add(self.preview_tab, text=" Live Preview ")

        self.preview_label = tk.Label(self.preview_tab, bg="#333337", fg="#aaaaaa", text="Live Preview Standby", font=("Segoe UI", 11, "italic"))
        self.preview_label.pack(fill="both", expand=True)

        # Tab 2: In-App Video Player (Custom Line Timeline + Live Volume %)
        self.player_tab = tk.Frame(self.notebook, bg="#2d2d30")
        self.notebook.add(self.player_tab, text=" Video Player ")

        # Premium Screen Card Container
        player_screen_frame = tk.Frame(self.player_tab, bg="#1e1e1e", bd=1, relief="solid")
        player_screen_frame.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        self.player_label = tk.Label(
            player_screen_frame, bg="#1e1e1e", fg="#888888",
            text="Select a video from explorer to play\n\nor drag & drop a video here",
            font=("Segoe UI", 11, "italic"), justify="center"
        )
        self.player_label.pack(fill="both", expand=True)

        # Premium Control Panel Container Card
        player_control_card = tk.Frame(self.player_tab, bg="#252526", bd=1, relief="solid")
        player_control_card.pack(fill="x", side="bottom", padx=10, pady=(0, 10))

        # Custom Single-Line Timeline Canvas
        timeline_box = tk.Frame(player_control_card, bg="#252526")
        timeline_box.pack(fill="x", padx=12, pady=(10, 4))

        self.timeline_canvas = tk.Canvas(timeline_box, bg="#1e1e1e", height=14, highlightthickness=1, highlightbackground="#4e4e52")
        self.timeline_canvas.pack(fill="x", expand=True)
        self.timeline_canvas.bind("<Button-1>", self._on_timeline_click)
        self.timeline_canvas.bind("<B1-Motion>", self._on_timeline_drag)
        self.timeline_canvas.bind("<ButtonRelease-1>", self._on_timeline_release)

        # Buttons & Volume Row inside card
        controls_row = tk.Frame(player_control_card, bg="#252526")
        controls_row.pack(fill="x", padx=12, pady=(2, 10))

        self.btn_play_vid = tk.Button(
            controls_row, text="▶ Play", bg="#007acc", fg="#ffffff",
            activebackground="#005999", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 9, "bold"), width=9,
            command=self._toggle_playback, cursor="hand2"
        )
        self.btn_play_vid.pack(side="left", padx=(0, 6))

        self.btn_stop_vid = tk.Button(
            controls_row, text="■ Stop", bg="#4e4e52", fg="#ffffff",
            activebackground="#3e3e42", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 9, "bold"), width=9,
            command=self._stop_playback, cursor="hand2"
        )
        self.btn_stop_vid.pack(side="left", padx=0)

        self.lbl_player_time = tk.Label(controls_row, text="00:00 / 00:00", bg="#252526", fg="#00e676", font=("Consolas", 9, "bold"))
        self.lbl_player_time.pack(side="left", padx=(15, 0))

        self.lbl_vol_val = tk.Label(controls_row, text="Vol: 80%", bg="#252526", fg="#cccccc", font=("Segoe UI", 9, "bold"), width=7)
        self.lbl_vol_val.pack(side="right", padx=(2, 0))

        self.volume_slider = ttk.Scale(controls_row, from_=0, to=1, orient="horizontal", command=self._on_volume_change)
        self.volume_slider.set(0.8)
        self.volume_slider.pack(side="right", ipadx=15)

        bottom_dock = tk.Frame(self, bg="#333337", height=70)
        bottom_dock.pack(fill="x", side="bottom")

        ctl_frame = tk.Frame(bottom_dock, bg="#333337")
        ctl_frame.pack(side="left", padx=15, pady=12)

        self.btn_rec = tk.Button(ctl_frame, text="● REC", bg="#d32f2f", cursor="hand2", fg="#ffffff", relief="flat", font=("Segoe UI", 9, "bold"), width=8, command=self.toggle_recording)
        self.btn_rec.pack(side="left", padx=3)

        self.btn_pause = tk.Button(ctl_frame, text="Pause", bg="#4e4e52", cursor="hand2", fg="#ffffff", relief="flat", font=("Segoe UI", 9, "bold"), state="disabled", width=8, command=self.toggle_pause)
        self.btn_pause.pack(side="left", padx=3)

        wave_frame = tk.Frame(bottom_dock, bg="#333337")
        wave_frame.pack(side="left", fill="x", expand=True, padx=15)

        self.wave_canvas = tk.Canvas(wave_frame, bg="#252526", height=40, highlightthickness=1, highlightbackground="#4e4e52")
        self.wave_canvas.pack(fill="x", expand=True)

        stats_frame = tk.Frame(bottom_dock, bg="#333337")
        stats_frame.pack(side="right", padx=15)

        self.lbl_time = tk.Label(stats_frame, text="Time: 00:00:00", bg="#333337", fg="#00e676", font=("Consolas", 10, "bold"))
        self.lbl_time.pack(anchor="e")

        self.lbl_size = tk.Label(stats_frame, text="Size: 0.0 MB", bg="#333337", fg="#aaaaaa", font=("Segoe UI", 9))
        self.lbl_size.pack(anchor="e")

    def _setup_drag_and_drop(self):
        if not DND_AVAILABLE:
            return

        widgets = [
            self,
            self.file_tree,
            self.player_label,
            self.preview_label,
            self.player_tab,
            self.preview_tab,
        ]
        for widget in widgets:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
                widget.dnd_bind("<<DragEnter>>", self._on_drag_enter)
                widget.dnd_bind("<<DragLeave>>", self._on_drag_leave)
            except Exception as e:
                print(f"[DnD Setup] {e}")

    def _on_drag_enter(self, event):
        try:
            self.lbl_dnd.config(text="↳ Release to open / import")
        except Exception:
            pass
        return "break"

    def _on_drag_leave(self, event):
        try:
            self.lbl_dnd.config(text="↳ Drop a video anywhere to open it")
        except Exception:
            pass
        return "break"

    def _on_drop(self, event):
        try:
            paths = list(self.tk.splitlist(event.data))
        except Exception:
            paths = [event.data]

        self._on_drag_leave(event)

        for raw_path in paths:
            path = os.path.normpath(raw_path.strip("{}"))
            if not path:
                continue

            # Dropping a folder changes the recording/output directory.
            if os.path.isdir(path):
                self.output_dir = path
                self._refresh_file_tree()
                continue

            if not os.path.isfile(path):
                continue

            ext = os.path.splitext(path)[1].lower()
            if ext in (".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v"):
                self.notebook.select(self.player_tab)
                self._load_video_in_player(path)
            elif ext == ".wav":
                # WAV is supported by the recorder library, but the current
                # player is a video player, so leave it in the library.
                messagebox.showinfo(
                    "Audio file",
                    "This is an audio-only file.\n"
                    "The in-app player currently accepts video files."
                )

        return "break"

    def _choose_video_file(self):
        path = filedialog.askopenfilename(
            title="Open Video",
            filetypes=[
                ("Video files", "*.mp4 *.avi *.mkv *.mov *.webm *.m4v"),
                ("All files", "*.*"),
            ],
            initialdir=self.output_dir
        )
        if path:
            self.notebook.select(self.player_tab)
            self._load_video_in_player(path)

    def _nudge_player(self, seconds):
        if not self.current_video_path or self.total_frames <= 0:
            return
        fps = self.player_fps or 30.0
        target = self.current_frame_idx + int(seconds * fps)
        target = max(0, min(target, self.total_frames - 1))
        w = max(self.timeline_canvas.winfo_width(), 1)
        self._handle_timeline_seek_event(
            (target / max(self.total_frames - 1, 1)) * w
        )

    def _choose_output_dir(self):
        d = filedialog.askdirectory(initialdir=self.output_dir)
        if d:
            self.output_dir = d
            self._refresh_file_tree()

    def _set_current_dir(self):
        self.output_dir = os.getcwd()
        self._refresh_file_tree()

    def _open_settings(self):
        dlg = SettingsDialog(self, self.selected_res, self.selected_fps, self.selected_audio_idx, self.show_mouse_cursor, self.audio_labels, self.audio_indices)
        self.wait_window(dlg)
        if dlg.result:
            self.selected_res = dlg.result["res"]
            self.selected_fps = dlg.result["fps"]
            self.selected_audio_idx = dlg.result["audio_idx"]
            self.show_mouse_cursor = dlg.result["show_mouse"]

    def _refresh_file_tree(self):
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        self.file_paths.clear()

        try:
            files = os.listdir(self.output_dir)
            for f in sorted(files):
                if f.lower().endswith((".mp4", ".wav", ".avi", ".mkv", ".mov", ".webm", ".m4v")):
                    path = os.path.join(self.output_dir, f)
                    size_mb = os.path.getsize(path) / (1024 * 1024)
                    display_name = os.path.splitext(f)[0]
                    item_id = self.file_tree.insert("", "end", text=display_name, values=(f"{size_mb:.1f} MB",))
                    self.file_paths[item_id] = path
        except Exception as e:
            print(f"[Tree Error] {e}")

    def _on_file_double_click(self, event):
        sel = self.file_tree.selection()
        if not sel:
            return
        item_id = sel[0]
        path = self.file_paths.get(item_id)
        if path and os.path.splitext(path)[1].lower() in (".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v"):
            self.notebook.select(self.player_tab)
            self._load_video_in_player(path)

    def _load_video_in_player(self, path):
        if not os.path.isfile(path):
            return

        self._stop_playback(reset_ui=False)

        with self.player_lock:
            self.player_generation += 1
            generation = self.player_generation
            self.current_video_path = path
            self.player_cap = cv2.VideoCapture(path)

            if not self.player_cap.isOpened():
                self.player_cap = None
                messagebox.showerror("Video Player", f"Could not open:\n{path}")
                return

            self.total_frames = int(self.player_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.current_frame_idx = 0
            self.player_fps = self.player_cap.get(cv2.CAP_PROP_FPS) or 30.0
            self._draw_custom_timeline(0)

        # Extract audio once per loaded video. pygame's mixer is kept alive
        # between pause/resume; this is important because unpause() cannot
        # resume a channel that has already been stopped.
        self.player_audio_loaded = False
        try:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            extract_cmd = [
                ffmpeg_exe, "-y", "-i", path,
                "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                self.temp_audio_extract_path
            ]
            result = subprocess.run(
                extract_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            if (
                result.returncode == 0
                and os.path.exists(self.temp_audio_extract_path)
                and os.path.getsize(self.temp_audio_extract_path) > 44
            ):
                pygame.mixer.music.load(self.temp_audio_extract_path)
                pygame.mixer.music.set_volume(self.volume_slider.get())
                self.player_audio_loaded = True
        except Exception as e:
            print(f"[Player Audio Extract Error] {e}")

        self.is_playing_video = True
        self.is_seeking = False
        self.btn_play_vid.config(text="❚❚ Pause")

        if self.player_audio_loaded:
            try:
                pygame.mixer.music.play(start=0.0)
            except Exception as e:
                print(f"[Player Audio Start Error] {e}")

        self.player_thread = threading.Thread(
            target=self._playback_loop, args=(generation,), daemon=True
        )
        self.player_thread.start()

    def _playback_loop(self, generation):
        fps = self.player_fps or 30.0
        delay = 1.0 / fps

        while self.is_playing_video:
            start_t = time.time()

            with self.player_lock:
                if generation != self.player_generation:
                    return

                if not self.player_cap or not self.player_cap.isOpened():
                    break

                if self.is_seeking:
                    frame = None
                else:
                    ret, frame = self.player_cap.read()
                    if not ret:
                        self.is_playing_video = False
                        break

                    self.current_frame_idx = int(
                        self.player_cap.get(cv2.CAP_PROP_POS_FRAMES)
                    )
                    frame_idx = self.current_frame_idx
                    self.after(
                        0,
                        lambda f=frame_idx, p=fps:
                            self._update_timeline_and_time(f, p)
                    )

            if frame is not None:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = frame_rgb.shape[:2]
                max_w, max_h = 740, 420
                scale = min(max_w / w, max_h / h)
                nw, nh = int(w * scale), int(h * scale)

                if nw > 0 and nh > 0:
                    frame_rgb = cv2.resize(
                        frame_rgb, (nw, nh), interpolation=cv2.INTER_LINEAR
                    )

                img_pil = Image.fromarray(frame_rgb)
                img_tk = ImageTk.PhotoImage(image=img_pil)
                self.after(0, self._update_player_frame, img_tk)

                elapsed = time.time() - start_t
                if delay > elapsed:
                    time.sleep(delay - elapsed)
            else:
                time.sleep(0.01)

        if generation != self.player_generation:
            return

        self.is_playing_video = False

        # Stop audio only when the video actually reaches its end.
        if self.current_frame_idx >= max(self.total_frames - 1, 0):
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

        self.after(0, lambda: self.btn_play_vid.config(text="▶ Play"))

    def _draw_custom_timeline(self, frame_idx):
        self.timeline_canvas.delete("all")
        w = self.timeline_canvas.winfo_width()
        h = self.timeline_canvas.winfo_height()
        h = h if h > 1 else 14

        if w <= 1:
            w = 700

        max_f = max(self.total_frames - 1, 1)
        progress_ratio = min(max(frame_idx / max_f, 0.0), 1.0)
        fill_width = int(w * progress_ratio)

        self.timeline_canvas.create_rectangle(
            0, h // 2 - 2, w, h // 2 + 2,
            fill="#3e3e42", outline=""
        )
        if fill_width > 0:
            self.timeline_canvas.create_rectangle(
                0, h // 2 - 2, fill_width, h // 2 + 2,
                fill="#007acc", outline=""
            )

        self.timeline_canvas.create_oval(
            fill_width - 5, h // 2 - 5,
            fill_width + 5, h // 2 + 5,
            fill="#00d2ff", outline="#ffffff", width=1
        )

    def _update_timeline_and_time(self, frame_idx, fps):
        self.current_frame_idx = frame_idx
        self._draw_custom_timeline(frame_idx)
        cur_sec = int(frame_idx / fps)
        tot_sec = int(self.total_frames / fps) if self.total_frames > 0 else 0
        cur_str = f"{cur_sec // 60:02d}:{cur_sec % 60:02d}"
        tot_str = f"{tot_sec // 60:02d}:{tot_sec % 60:02d}"
        self.lbl_player_time.config(text=f"{cur_str} / {tot_str}")

    def _on_timeline_click(self, event):
        self._handle_timeline_seek_event(event.x)

    def _on_timeline_drag(self, event):
        self._handle_timeline_seek_event(event.x)

    def _handle_timeline_seek_event(self, click_x):
        w = self.timeline_canvas.winfo_width()
        if w <= 0 or self.total_frames <= 0:
            return

        ratio = max(min(click_x / w, 1.0), 0.0)
        target_frame = int(ratio * max(self.total_frames - 1, 1))

        self.is_seeking = True
        try:
            with self.player_lock:
                if not self.player_cap or not self.player_cap.isOpened():
                    return

                fps = self.player_cap.get(cv2.CAP_PROP_FPS) or self.player_fps or 30.0
                self.player_fps = fps
                self.player_cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                self.current_frame_idx = target_frame
                self._update_timeline_and_time(target_frame, fps)

                target_sec = target_frame / fps

                # Seeking must recreate the music position. Do not call
                # unpause() after pygame.mixer.music.stop().
                if self.player_audio_loaded:
                    try:
                        pygame.mixer.music.play(start=max(0.0, target_sec))
                        if not self.is_playing_video:
                            pygame.mixer.music.pause()
                    except Exception as e:
                        print(f"[Player Seek Audio Error] {e}")

                ret, frame = self.player_cap.read()
                if ret:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w_f = frame_rgb.shape[:2]
                    max_w, max_h = 740, 420
                    scale = min(max_w / w_f, max_h / h)
                    nw, nh = int(w_f * scale), int(h * scale)

                    if nw > 0 and nh > 0:
                        frame_rgb = cv2.resize(
                            frame_rgb, (nw, nh), interpolation=cv2.INTER_LINEAR
                        )

                    img_pil = Image.fromarray(frame_rgb)
                    img_tk = ImageTk.PhotoImage(image=img_pil)
                    self._update_player_frame(img_tk)
        finally:
            self.is_seeking = False

    def _on_timeline_release(self, event):
        self.is_seeking = False

    def _update_player_frame(self, img_tk):
        if self.winfo_exists():
            self.player_label.configure(image=img_tk, text="")
            self.player_label.image = img_tk

    def _on_volume_change(self, val):
        vol_float = float(val)
        percent = int(vol_float * 100)
        self.lbl_vol_val.config(text=f"Vol: {percent}%")
        try:
            pygame.mixer.music.set_volume(vol_float)
        except Exception:
            pass

    def _toggle_playback(self):
        with self.player_lock:
            is_open = self.player_cap and self.player_cap.isOpened()
            current_frame = self.current_frame_idx
            fps = self.player_fps or 30.0
            generation = self.player_generation

        if not is_open:
            return

        if self.is_playing_video:
            # Pause BOTH video and audio. Do not stop the mixer.
            self.is_playing_video = False
            self.btn_play_vid.config(text="▶ Play")
            try:
                pygame.mixer.music.pause()
            except Exception:
                pass
            return

        # Resume video.
        self.is_playing_video = True
        self.btn_play_vid.config(text="❚❚ Pause")

        # If the audio was stopped (for example after EOF or a previous
        # seek), unpause() is not enough. Start it again at the video time.
        if self.player_audio_loaded:
            try:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.unpause()
                else:
                    pygame.mixer.music.play(
                        start=max(0.0, current_frame / fps)
                    )
            except Exception as e:
                print(f"[Player Resume Audio Error] {e}")

        self.player_thread = threading.Thread(
            target=self._playback_loop, args=(generation,), daemon=True
        )
        self.player_thread.start()

    def _stop_playback(self, reset_ui=True):
        self.is_playing_video = False
        self.is_seeking = False

        # Invalidate any playback thread currently winding down.
        self.player_generation += 1

        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

        self.player_audio_loaded = False

        with self.player_lock:
            if self.player_cap:
                self.player_cap.release()
                self.player_cap = None

        if os.path.exists(self.temp_audio_extract_path):
            try:
                os.remove(self.temp_audio_extract_path)
            except Exception:
                pass

        if reset_ui:
            self.player_label.configure(
                image="",
                text="Select a video from explorer to play\n\nor drag & drop a video here"
            )
            self._draw_custom_timeline(0)
            self.lbl_player_time.config(text="00:00 / 00:00")
            self.btn_play_vid.config(text="▶ Play")

    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def toggle_pause(self):
        if not self.is_recording:
            return

        if not self.is_paused:
            self.is_paused = True
            self.pause_start_time = time.time()
            self.pause_event.set()
            self.btn_pause.config(text="Resume", bg="#ff9800")
        else:
            self.is_paused = False
            self.total_paused_duration += (time.time() - self.pause_start_time)
            self.pause_event.clear()
            self.btn_pause.config(text="Pause", bg="#4e4e52")

    def start_recording(self):
        self.is_recording = True
        self.is_paused = False
        self.start_time = time.time()
        self.total_paused_duration = 0
        self.audio_delay_ms = 0
        self.stop_event.clear()
        self.pause_event.clear()

        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.temp_video = os.path.join(script_dir, "temp_video.mp4")
        self.temp_audio = os.path.join(script_dir, "temp_audio.wav")

        self.btn_rec.config(text="■ STOP", bg="#ff1744")
        self.btn_pause.config(state="normal", text="Pause", bg="#4e4e52")

        fps_num = int(self.selected_fps.split()[0])
        mode = self.mode_var.get()
        rec_audio = mode in ("audio", "both")
        rec_video = mode in ("video", "both")

        if rec_audio:
            self.audio_queue = queue.Queue()
            self.audio_thread = threading.Thread(
                target=self._record_audio_loop,
                args=(self.temp_audio, self.selected_audio_idx, self.audio_queue),
                daemon=True
            )
            self.audio_thread.start()

        if rec_video:
            self.video_thread = threading.Thread(
                target=self._record_video_loop,
                args=(fps_num, self.selected_res),
                daemon=True
            )
            self.video_thread.start()

    def _record_audio_loop(self, audio_filename, device_index, q):
        if device_index is None:
            return

        p = pyaudio.PyAudio()
        try:
            dev_info = p.get_device_info_by_index(device_index)
            channels = int(dev_info.get("maxInputChannels", 2))
            rate = int(dev_info.get("defaultSampleRate", 48000))

            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=1024,
            )

            first_audio_time = None

            flush_frames = 10
            while flush_frames > 0 and not self.stop_event.is_set():
                try:
                    avail = stream.get_read_available()
                    if avail > 0:
                        stream.read(avail, exception_on_overflow=False)
                        flush_frames -= 1
                except Exception:
                    pass
                time.sleep(0.01)

            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    time.sleep(0.05)
                    continue

                try:
                    avail = stream.get_read_available()
                    if avail > 0:
                        data = stream.read(avail, exception_on_overflow=False)
                        if data:
                            if first_audio_time is None:
                                first_audio_time = time.time()
                            q.put(data)
                            samples = np.frombuffer(data, dtype=np.int16)
                            if len(samples) > 0:
                                peak = np.max(np.abs(samples)) / 32768.0
                                self.audio_levels.append(float(peak))
                                if len(self.audio_levels) > 50:
                                    self.audio_levels.pop(0)
                except Exception:
                    time.sleep(0.05)

                time.sleep(0.005)

            stream.stop_stream()
            stream.close()
        except Exception as e:
            print(f"[Audio Error] {e}")
        finally:
            p.terminate()

        audio_frames = []
        while not q.empty():
            audio_frames.append(q.get())

        if audio_frames:
            with wave.open(audio_filename, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(b"".join(audio_frames))

        if first_audio_time and self.start_time:
            self.audio_delay_ms = int((first_audio_time - self.start_time) * 1000)

    def _record_video_loop(self, fps, resolution_key):
        sct = mss.MSS()
        monitor = sct.monitors[1]
        target_w, target_h = RESOLUTIONS.get(resolution_key, (1920, 1080))
        native_w, native_h = monitor["width"], monitor["height"]
        needs_scale = (target_w, target_h) != (native_w, native_h)

        writer = imageio.get_writer(
            self.temp_video,
            fps=fps,
            codec="libx264",
            pixelformat="yuv420p",
            quality=8,
            output_params=["-preset", "fast", "-crf", "20"],
            macro_block_size=1,
        )

        frame_duration = 1.0 / fps
        start_time = time.perf_counter()
        next_frame_time = start_time
        written_frames = 0
        last_ui_update = 0

        while not self.stop_event.is_set():
            if self.pause_event.is_set():
                time.sleep(0.05)
                continue

            current_time = time.perf_counter()
            sct_img = sct.grab(monitor)
            frame = np.array(sct_img)
            frame_rgb = frame[:, :, [2, 1, 0]]

            if needs_scale:
                interp = cv2.INTER_AREA if target_w < native_w else cv2.INTER_LINEAR
                scaled_frame_rgb = cv2.resize(frame_rgb, (target_w, target_h), interpolation=interp)
            else:
                scaled_frame_rgb = frame_rgb

            if current_time - last_ui_update >= 0.08:
                last_ui_update = current_time
                preview_frame = cv2.resize(frame_rgb, (640, 360), interpolation=cv2.INTER_LINEAR)
                img_pil = Image.fromarray(preview_frame)
                img_tk = ImageTk.PhotoImage(image=img_pil)
                self.after(0, self._update_preview, img_tk)

            while current_time >= next_frame_time:
                writer.append_data(scaled_frame_rgb)
                written_frames += 1
                next_frame_time = start_time + (written_frames * frame_duration)

            time.sleep(0.003)

        writer.close()

    def _update_preview(self, img_tk):
        if self.winfo_exists():
            self.preview_label.configure(image=img_tk, text="")
            self.preview_label.image = img_tk

    def stop_recording(self):
        self.btn_rec.config(state="disabled")
        self.btn_pause.config(state="disabled")
        self.stop_event.set()

        default_name = f"Rec_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        user_name = simpledialog.askstring("Save Recording", "Enter a name for your video:", initialvalue=default_name)
        if not user_name:
            user_name = default_name
        
        user_name = "".join(c for c in user_name if c.isalnum() or c in ('_', '-')).strip()
        self.current_output_file = os.path.join(self.output_dir, f"{user_name}.mp4")

        threading.Thread(target=self._finalize_output, daemon=True).start()

    def _finalize_output(self):
        if hasattr(self, "audio_thread") and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=3.0)
        if hasattr(self, "video_thread") and self.video_thread.is_alive():
            self.video_thread.join(timeout=3.0)

        fps_num = int(self.selected_fps.split()[0])
        has_video = os.path.exists(self.temp_video)
        has_audio = os.path.exists(self.temp_audio)

        if has_video and has_audio:
            merge_audio_and_video(self.temp_video, self.temp_audio, self.current_output_file, fps_num, self.audio_delay_ms)
        elif has_video and not has_audio:
            os.rename(self.temp_video, self.current_output_file)
        elif has_audio and not has_video:
            audio_out = self.current_output_file.replace(".mp4", ".wav")
            os.rename(self.temp_audio, audio_out)

        if os.path.exists(self.temp_video):
            os.remove(self.temp_video)
        if os.path.exists(self.temp_audio):
            os.remove(self.temp_audio)

        self.after(0, self._reset_ui_after_save)

    def _reset_ui_after_save(self):
        self.is_recording = False
        self.is_paused = False
        self.btn_rec.config(text="● REC", bg="#d32f2f", state="normal")
        self.btn_pause.config(text="Pause", bg="#4e4e52", state="disabled")
        self.lbl_time.config(text="Time: 00:00:00")
        self._refresh_file_tree()

    def _update_loop(self):
        if self.is_recording and self.start_time:
            if not self.is_paused:
                elapsed = int(time.time() - self.start_time - self.total_paused_duration)
            else:
                elapsed = int(self.pause_start_time - self.start_time - self.total_paused_duration)

            hrs, rem = divmod(elapsed, 3600)
            mins, secs = divmod(rem, 60)
            self.lbl_time.config(text=f"Time: {hrs:02d}:{mins:02d}:{secs:02d}")

            if os.path.exists(self.temp_video):
                sz = os.path.getsize(self.temp_video) / (1024 * 1024)
                self.lbl_size.config(text=f"Size: {sz:.1f} MB")

        self._draw_waveform()
        self.after(100, self._update_loop)

    def _draw_waveform(self):
        self.wave_canvas.delete("all")
        w = self.wave_canvas.winfo_width()
        h = self.wave_canvas.winfo_height()
        mid_y = h / 2

        if w <= 1 or h <= 1:
            return

        points = []
        n = len(self.audio_levels)
        dx = w / max(n - 1, 1)

        for i, val in enumerate(self.audio_levels):
            x = i * dx
            amplitude = val * (h / 2) * 0.9
            points.append((x, mid_y - amplitude))

        for i in range(n - 1, -1, -1):
            val = self.audio_levels[i]
            x = i * dx
            amplitude = val * (h / 2) * 0.9
            points.append((x, mid_y + amplitude))

        if len(points) > 2:
            flat_points = [coord for pt in points for coord in pt]
            self.wave_canvas.create_polygon(flat_points, fill="#007acc", outline="#00d2ff")

    def on_close(self):
        self._stop_playback()
        if self.is_recording:
            if messagebox.askokcancel("Quit", "Recording in progress. Stop and exit?"):
                self.stop_event.set()
                self.destroy()
        else:
            self.destroy()


def merge_audio_and_video(video_path, audio_path, output_path, fps, audio_delay_ms=0):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    if os.path.exists(audio_path) and os.path.getsize(audio_path) > 44:
        if audio_delay_ms > 0:
            audio_filter = f"adelay={audio_delay_ms}|{audio_delay_ms}"
            cmd = [
                ffmpeg_exe,
                "-y",
                "-r", str(fps),
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-af", audio_filter,
                "-shortest",
                output_path,
            ]
        else:
            cmd = [
                ffmpeg_exe,
                "-y",
                "-r", str(fps),
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                output_path,
            ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        if os.path.exists(video_path):
            os.rename(video_path, output_path)


if __name__ == "__main__":
    app = MFHScreenRecorder()
    app.mainloop()
