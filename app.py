from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import sounddevice as sd
import soundfile as sf
import wx

from tts_backend import (
    LANGUAGE_NAMES, MODELS, MODEL_BY_KEY, PRESETS, ROOT, DownloadCancelled, Engine, Model,
    Request, Result, Samples, audition_requests, clip_audio, load_reference, read_result, validate_request,
)

T = TypeVar("T")


class DemoFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title="本地 TTS 试听台 · wxPython", size=(1120, 880))
        self.SetMinSize((900, 740))
        self.engine = Engine()
        self.cancel = threading.Event()
        self.busy = False
        self.batch_mode = False
        self.results: list[Result] = []
        self.current: Result | None = None
        self.play_started = 0.0
        self.play_duration = 0.0
        self.playing = False
        self._build_ui()
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._tick, self.timer)
        self.Bind(wx.EVT_CLOSE, self._close)
        self.timer.Start(100)
        self._select_model()
        self._load_history()
        self.Centre()

    @property
    def model(self) -> Model:
        return MODELS[self.model_choice.GetSelection()]

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(panel, label="本地 TTS 模型试听台")
        title.SetFont(title.GetFont().Bold().Larger())
        root.Add(title, 0, wx.ALL, 12)
        root.Add(wx.StaticText(panel, label="全部模型预先下载到本地；合成阶段不访问网络。桌面耗时不代表手机性能。"), 0, wx.LEFT | wx.BOTTOM, 12)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.model_choice = wx.Choice(panel, choices=[m.title for m in MODELS])
        self.model_choice.SetSelection(0)
        self.model_choice.Bind(wx.EVT_CHOICE, lambda event: self._select_model())
        row.Add(self.model_choice, 1, wx.RIGHT, 8)
        self.prepare_button = wx.Button(panel, label="下载 / 检查全部模型")
        self.prepare_button.Bind(wx.EVT_BUTTON, self._prepare)
        row.Add(self.prepare_button, 0, wx.RIGHT, 8)
        self.cancel_button = wx.Button(panel, label="取消下载")
        self.cancel_button.Disable()
        self.cancel_button.Bind(wx.EVT_BUTTON, lambda event: self.cancel.set())
        row.Add(self.cancel_button)
        root.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.description = wx.StaticText(panel)
        root.Add(self.description, 0, wx.EXPAND | wx.ALL, 12)

        settings = wx.BoxSizer(wx.HORIZONTAL)
        self.language = wx.Choice(panel)
        self.language.Bind(wx.EVT_CHOICE, lambda event: self._select_language())
        self.sid = wx.SpinCtrl(panel, min=0, max=52, initial=45, size=(75, -1))
        self.speed = wx.SpinCtrlDouble(panel, min=0.5, max=2, initial=1, inc=0.1, size=(85, -1))
        self.speed.SetDigits(1)
        self.threads = wx.SpinCtrl(panel, min=1, max=16, initial=2, size=(65, -1))
        self.steps = wx.SpinCtrl(panel, min=1, max=32, initial=5, size=(65, -1))
        for label, control in (
            ("语言", self.language), ("音色 ID", self.sid), ("语速", self.speed),
            ("CPU 线程", self.threads), ("采样步数", self.steps),
        ):
            settings.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            settings.Add(control, 0, wx.RIGHT, 12)
        root.Add(settings, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        presets = wx.BoxSizer(wx.HORIZONTAL)
        presets.Add(wx.StaticText(panel, label="试听文本"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.preset = wx.Choice(panel)
        self.preset.Bind(wx.EVT_CHOICE, lambda event: self._insert_preset())
        presets.Add(self.preset, 1, wx.RIGHT, 8)
        preset_button = wx.Button(panel, label="填入片段")
        preset_button.Bind(wx.EVT_BUTTON, lambda event: self._insert_preset())
        presets.Add(preset_button)
        root.Add(presets, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.text = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 115))
        root.Add(self.text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        reference_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "声音克隆参考（仅 ZipVoice / Pocket；留空使用包内样例前 10 秒以内）")
        reference_parent = reference_box.GetStaticBox()
        self.reference = wx.FilePickerCtrl(reference_parent, wildcard="Audio files (*.wav;*.flac;*.ogg)|*.wav;*.flac;*.ogg", style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        reference_box.Add(self.reference, 0, wx.EXPAND | wx.ALL, 5)
        ref_row = wx.BoxSizer(wx.HORIZONTAL)
        self.reference_text = wx.TextCtrl(reference_parent)
        self.reference_text.SetHint("ZipVoice：填写参考录音的准确转写；内置样例无需填写")
        ref_row.Add(self.reference_text, 1, wx.RIGHT, 8)
        self.reference_play = wx.Button(reference_parent, label="播放参考录音")
        self.reference_play.Bind(wx.EVT_BUTTON, self._play_reference)
        ref_row.Add(self.reference_play)
        self.clear_reference = wx.Button(reference_parent, label="恢复内置样例")
        self.clear_reference.Bind(wx.EVT_BUTTON, self._clear_reference)
        ref_row.Add(self.clear_reference, 0, wx.LEFT, 8)
        reference_box.Add(ref_row, 0, wx.EXPAND | wx.ALL, 5)
        root.Add(reference_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.generate_button = wx.Button(panel, label="合成并试听")
        self.generate_button.Bind(wx.EVT_BUTTON, self._generate)
        actions.Add(self.generate_button, 0, wx.RIGHT, 10)
        self.batch_button = wx.Button(panel, label="一键生成 20 种语言试听")
        self.batch_button.Bind(wx.EVT_BUTTON, self._generate_twenty)
        actions.Add(self.batch_button, 0, wx.RIGHT, 10)
        self.auto_play = wx.CheckBox(panel, label="合成后自动播放")
        self.auto_play.SetValue(True)
        actions.Add(self.auto_play, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.progress = wx.Gauge(panel, range=100)
        actions.Add(self.progress, 1, wx.ALIGN_CENTER_VERTICAL)
        root.Add(actions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.status = wx.StaticText(panel, label="就绪")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        playback = wx.StaticBoxSizer(wx.VERTICAL, panel, "合成结果与片段试听")
        playback_parent = playback.GetStaticBox()
        self.history = wx.ListBox(playback_parent, size=(-1, 95))
        self.history.Bind(wx.EVT_LISTBOX, self._select_result)
        playback.Add(self.history, 0, wx.EXPAND | wx.ALL, 5)
        self.result_info = wx.StaticText(playback_parent, label="尚无合成结果。结果将自动保存到 outputs 文件夹。")
        playback.Add(self.result_info, 0, wx.EXPAND | wx.ALL, 5)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        self.play_button = wx.Button(playback_parent, label="播放完整音频")
        self.play_button.Bind(wx.EVT_BUTTON, self._play_full)
        self.clip_button = wx.Button(playback_parent, label="试听片段")
        self.clip_button.Bind(wx.EVT_BUTTON, self._play_clip)
        self.stop_button = wx.Button(playback_parent, label="停止播放")
        self.stop_button.Bind(wx.EVT_BUTTON, lambda event: self._stop())
        self.save_button = wx.Button(playback_parent, label="另存完整 WAV")
        self.save_button.Bind(wx.EVT_BUTTON, self._save)
        self.save_clip_button = wx.Button(playback_parent, label="导出片段 WAV")
        self.save_clip_button.Bind(wx.EVT_BUTTON, self._save_clip)
        for button in (self.play_button, self.clip_button, self.stop_button):
            controls.Add(button, 0, wx.RIGHT, 5)
        self.clip_start = wx.SpinCtrlDouble(playback_parent, min=0, max=36000, initial=0, inc=1, size=(80, -1))
        self.clip_duration = wx.SpinCtrlDouble(playback_parent, min=0.1, max=600, initial=8, inc=1, size=(80, -1))
        self.clip_start.SetDigits(2)
        self.clip_duration.SetDigits(2)
        for label, control in (("起点 / 秒", self.clip_start), ("时长 / 秒", self.clip_duration)):
            controls.Add(wx.StaticText(playback_parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)
            controls.Add(control)
        playback.Add(controls, 0, wx.ALL, 5)
        save_row = wx.BoxSizer(wx.HORIZONTAL)
        save_row.Add(self.save_button, 0, wx.RIGHT, 8)
        save_row.Add(self.save_clip_button, 0, wx.RIGHT, 8)
        folder_button = wx.Button(playback_parent, label="打开结果目录")
        folder_button.Bind(wx.EVT_BUTTON, self._open_outputs)
        save_row.Add(folder_button)
        self.play_label = wx.StaticText(playback_parent, label="未播放")
        save_row.Add(self.play_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        playback.Add(save_row, 0, wx.ALL, 5)
        root.Add(playback, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        panel.SetSizer(root)
        self._result_buttons(False)

    def _result_buttons(self, enabled: bool) -> None:
        for button in (self.play_button, self.clip_button, self.save_button, self.save_clip_button):
            button.Enable(enabled)

    def _select_model(self) -> None:
        model = self.model
        self.language.Set([f"{LANGUAGE_NAMES[lang]} ({lang})" for lang in model.languages])
        self.language.SetSelection(0)
        self.sid.SetRange(0, model.speakers - 1)
        self.sid.SetValue(model.default_sid)
        self.reference.SetPath("")
        self.reference_text.SetValue("")
        clone = model.family in ("zipvoice", "pocket")
        for control in (self.reference, self.reference_play, self.clear_reference):
            control.Enable(clone)
        self.reference_text.Enable(model.family == "zipvoice")
        self.steps.Enable(model.family in ("zipvoice", "pocket", "supertonic"))
        self.steps.SetValue(8 if model.family == "supertonic" else 5)
        ready = "已下载" if self.engine.store.ready(model) else f"缺少本地模型（约 {model.download_mb:.0f} MB），请先下载全部"
        self.description.SetLabel(f"{ready}  |  {model.description}")
        self._select_language()

    def _select_language(self) -> None:
        language = self.model.languages[self.language.GetSelection()]
        presets = PRESETS.get(language, ())
        self.preset.Set([label for label, text in presets])
        if presets:
            self.preset.SetSelection(0)
            self._insert_preset()
        else:
            self.text.SetValue("")
            self.text.SetHint(f"请手动输入 {language} 语言的试听文本")
        if self.model.family == "kokoro":
            self.sid.SetValue(45 if language == "zh" else 3)

    def _insert_preset(self) -> None:
        language = self.model.languages[self.language.GetSelection()]
        index = self.preset.GetSelection()
        if index != wx.NOT_FOUND:
            self.text.SetValue(PRESETS[language][index][1])

    def _clear_reference(self, event: wx.CommandEvent) -> None:
        self.reference.SetPath("")
        self.reference_text.SetValue("")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for control in (self.generate_button, self.batch_button, self.prepare_button, self.model_choice, self.language):
            control.Enable(not busy)
        self.cancel_button.Enable(busy)
        if not busy:
            self.batch_mode = False
            self.cancel_button.SetLabel("取消下载")
            self.progress.SetValue(0)

    def _progress(self, label: str, received: int, total: int) -> None:
        wx.CallAfter(self._show_progress, label, received, total)

    def _show_progress(self, label: str, received: int, total: int) -> None:
        if total:
            self.cancel_button.Enable(self.busy)
            self.progress.SetValue(min(100, received * 100 // total))
            self.status.SetLabel(f"{label}：{received / 1e6:.1f} / {total / 1e6:.1f} MB")
        else:
            self.progress.Pulse()
            self.status.SetLabel(label)
            self.cancel_button.Enable(self.busy and self.batch_mode)

    def _run(self, work: Callable[[], T], done: Callable[[T], None], batch: bool = False) -> None:
        if self.busy:
            return
        self._stop()
        self.cancel.clear()
        self.batch_mode = batch
        self.cancel_button.SetLabel("停止批量" if batch else "取消下载")
        self._set_busy(True)

        def worker() -> None:
            try:
                value = work()
            except DownloadCancelled as error:
                wx.CallAfter(self._cancelled, str(error))
            except Exception as error:
                logging.exception("后台任务失败")
                wx.CallAfter(self._failed, str(error))
            else:
                wx.CallAfter(self._done, done, value)

        threading.Thread(target=worker, name="tts-worker", daemon=True).start()

    def _done(self, done: Callable[[T], None], value: T) -> None:
        self._set_busy(False)
        done(value)

    def _cancelled(self, message: str) -> None:
        self._set_busy(False)
        self.status.SetLabel(message)

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        self.status.SetLabel(f"失败：{message}")
        wx.MessageBox(f"{message}\n\n详细信息见 tts-demo.log。", "任务失败", wx.OK | wx.ICON_ERROR, self)

    def _prepare(self, event: wx.CommandEvent) -> None:
        def prepare_all() -> Path:
            for model in MODELS:
                if self.cancel.is_set():
                    raise DownloadCancelled("下载已取消。")
                self.engine.store.prepare(model, self._progress, self.cancel)
            return self.engine.store.root

        self._run(prepare_all, self._prepared)

    def _prepared(self, path: Path) -> None:
        self._select_model()
        self.status.SetLabel(f"全部模型已就绪：{path}")

    def _generate(self, event: wx.CommandEvent) -> None:
        request = Request(
            model_key=self.model.key, text=self.text.GetValue(),
            language=self.model.languages[self.language.GetSelection()],
            sid=self.sid.GetValue(), speed=self.speed.GetValue(),
            threads=self.threads.GetValue(), steps=self.steps.GetValue(),
            reference=self.reference.GetPath(), reference_text=self.reference_text.GetValue(),
        )
        try:
            validate_request(request)
        except (ValueError, FileNotFoundError) as error:
            wx.MessageBox(str(error), "请检查输入", wx.OK | wx.ICON_WARNING, self)
            return
        self._run(lambda: self.engine.synthesize(request, self._progress, self.cancel), self._generated)

    def _generated(self, result: Result) -> None:
        self._append_result(result)
        self.history.SetSelection(len(self.results) - 1)
        self._select_result()
        self.description.SetLabel(f"已下载  |  {self.model.description}")
        self.status.SetLabel(f"合成完成，已保存：{result.path.name}")
        if self.auto_play.GetValue():
            self._play_full()

    def _generate_twenty(self, event: wx.CommandEvent) -> None:
        requests = audition_requests(self.threads.GetValue())
        missing = sorted({
            request.model_key for request in requests
            if not self.engine.store.ready(MODEL_BY_KEY[request.model_key])
        })
        if missing:
            wx.MessageBox(f"缺少本地模型：{', '.join(missing)}。请先下载全部模型。", "请检查模型", wx.OK | wx.ICON_WARNING, self)
            return

        def work() -> int:
            completed = 0
            for index, request in enumerate(requests, 1):
                if self.cancel.is_set():
                    break
                prefix = f"[{index}/20] {LANGUAGE_NAMES[request.language]}"

                def progress(label: str, received: int, total: int) -> None:
                    self._progress(f"{prefix}：{label}", received, total)

                try:
                    result = self.engine.synthesize(request, progress, self.cancel)
                except DownloadCancelled:
                    break
                wx.CallAfter(self._append_result, result)
                completed += 1
            return completed

        self._run(work, self._batch_done, batch=True)

    def _batch_done(self, completed: int) -> None:
        if completed:
            self.history.SetSelection(len(self.results) - completed)
            self._select_result()
        state = "已停止" if self.cancel.is_set() else "已完成"
        self.status.SetLabel(f"20 种语言试听{state}：{completed}/20 段已保存。选择列表中的语言后点击播放。")

    def _append_result(self, result: Result) -> None:
        self.results.append(result)
        model = MODEL_BY_KEY[result.request.model_key]
        language = result.request.language
        self.history.Append(f"{LANGUAGE_NAMES[language]} ({language}) | {model.title} | 音色 {result.request.sid} | {result.duration:.1f}s | {result.request.text[:35]}")

    def _load_history(self) -> None:
        failed = 0
        paths = sorted(self.engine.output.glob("*_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
        for path in reversed(paths):
            try:
                self._append_result(read_result(path))
            except (OSError, ValueError, KeyError, TypeError, sf.LibsndfileError):
                logging.exception("无法读取历史音频：%s", path)
                failed += 1
        if self.results:
            self.history.SetSelection(len(self.results) - 1)
            self._select_result()
            self.status.SetLabel(f"已载入 {len(self.results)} 段本地音频，可直接播放或截取试听。")
        if failed:
            self.status.SetLabel(f"已载入 {len(self.results)} 段音频，另有 {failed} 条历史记录读取失败，详见日志。")

    def _select_result(self, event: wx.CommandEvent | None = None) -> None:
        index = self.history.GetSelection()
        if index == wx.NOT_FOUND:
            return
        self._stop()
        self.current = self.results[index]
        result = self.current
        self.result_info.SetLabel(
            f"{LANGUAGE_NAMES[result.request.language]} | {result.sample_rate} Hz | 音频 {result.duration:.2f}s | "
            f"推理 {result.elapsed:.2f}s | RTF {result.rtf:.3f} | 加载 {result.load_seconds:.2f}s"
        )
        self.clip_start.SetValue(0)
        self.clip_start.SetRange(0, max(0, result.duration - 0.01))
        self._result_buttons(True)

    def _play_full(self, event: wx.CommandEvent | None = None) -> None:
        if self.current:
            self._play(self.current.samples, self.current.sample_rate)

    def _play_clip(self, event: wx.CommandEvent) -> None:
        if self.current:
            try:
                samples = clip_audio(self.current.samples, self.current.sample_rate, self.clip_start.GetValue(), self.clip_duration.GetValue())
                self._play(samples, self.current.sample_rate)
            except ValueError as error:
                wx.MessageBox(str(error), "片段设置无效", wx.OK | wx.ICON_WARNING, self)

    def _play(self, samples: Samples, rate: int) -> None:
        try:
            self._stop()
            sd.play(samples, rate)
            self.play_started = time.monotonic()
            self.play_duration = len(samples) / rate
            self.playing = True
        except (sd.PortAudioError, ValueError) as error:
            logging.exception("音频播放失败")
            wx.MessageBox(f"播放失败：{error}\n音频已保存在 outputs，可用外部播放器打开。", "播放失败", wx.OK | wx.ICON_ERROR, self)

    def _play_reference(self, event: wx.CommandEvent) -> None:
        try:
            path = Path(self.reference.GetPath()) if self.reference.GetPath() else self.engine.store.directory(self.model) / self.model.reference
            if not path.is_file():
                raise FileNotFoundError("请先下载模型，或选择本地参考音频。")
            samples, rate = load_reference(path, built_in=not self.reference.GetPath())
            self._play(samples, rate)
        except (OSError, ValueError, sf.LibsndfileError) as error:
            logging.exception("读取参考音频失败")
            wx.MessageBox(str(error), "参考音频不可用", wx.OK | wx.ICON_ERROR, self)

    def _stop(self) -> None:
        try:
            sd.stop()
        except sd.PortAudioError:
            logging.exception("停止音频播放失败")
        self.playing = False
        self.play_label.SetLabel("未播放")

    def _tick(self, event: wx.TimerEvent) -> None:
        if self.playing:
            elapsed = time.monotonic() - self.play_started
            if elapsed >= self.play_duration:
                self.playing = False
                self.play_label.SetLabel("播放结束")
            else:
                self.play_label.SetLabel(f"播放 {elapsed:.1f} / {self.play_duration:.1f} 秒")

    def _save(self, event: wx.CommandEvent) -> None:
        self._export(False)

    def _save_clip(self, event: wx.CommandEvent) -> None:
        self._export(True)

    def _export(self, clip: bool) -> None:
        if not self.current:
            return
        with wx.FileDialog(self, "导出 WAV", defaultFile="clip.wav" if clip else self.current.path.name, wildcard="WAV audio (*.wav)|*.wav", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            destination = Path(dialog.GetPath())
            try:
                if clip:
                    samples = clip_audio(self.current.samples, self.current.sample_rate, self.clip_start.GetValue(), self.clip_duration.GetValue())
                    sf.write(destination, samples, self.current.sample_rate, subtype="PCM_16")
                elif destination.resolve() != self.current.path.resolve():
                    shutil.copyfile(self.current.path, destination)
                self.status.SetLabel(f"已导出：{destination}")
            except (OSError, ValueError, sf.LibsndfileError) as error:
                logging.exception("导出失败")
                wx.MessageBox(str(error), "导出失败", wx.OK | wx.ICON_ERROR, self)

    def _open_outputs(self, event: wx.CommandEvent) -> None:
        try:
            self.engine.output.mkdir(exist_ok=True)
            if not wx.LaunchDefaultApplication(str(self.engine.output)):
                raise OSError("系统未能打开结果目录，请手动打开 outputs。")
        except OSError as error:
            wx.MessageBox(str(error), "无法打开目录", wx.OK | wx.ICON_ERROR, self)

    def _close(self, event: wx.CloseEvent) -> None:
        if self.busy and event.CanVeto():
            self.cancel.set()
            wx.MessageBox("任务尚未结束。下载将取消；模型加载或合成阶段请等待完成后关闭。", "请稍候", wx.OK | wx.ICON_INFORMATION, self)
            event.Veto()
            return
        self.timer.Stop()
        self._stop()
        self.Destroy()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(ROOT / "tts-demo.log", encoding="utf-8"), logging.StreamHandler()],
    )
    app = wx.App(False)
    frame = DemoFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
