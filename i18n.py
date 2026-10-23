from __future__ import annotations

import re

UI_LANGUAGES = ("zh", "en")

ENGLISH = {
    "本地 TTS 试听台 · wxPython": "Local TTS Audition · wxPython",
    "本地 TTS 模型试听台": "Local TTS Model Audition",
    "界面语言": "Interface language",
    "全部模型预先下载到本地；合成阶段不访问网络。桌面耗时不代表手机性能。":
        "All models are stored locally. Synthesis stays offline. Desktop timings do not represent mobile performance.",
    "下载 / 检查全部模型": "Download / check all models",
    "取消下载": "Cancel download",
    "停止批量": "Stop batch",
    "语言": "Speech language",
    "音色 ID": "Speaker ID",
    "语速": "Speed",
    "CPU 线程": "CPU threads",
    "采样步数": "Steps",
    "试听文本": "Sample text",
    "填入片段": "Insert sample",
    "声音克隆参考（仅 ZipVoice / Pocket；留空使用包内样例前 10 秒以内）":
        "Voice cloning reference (ZipVoice / Pocket only; leave empty for the bundled sample, up to 10 seconds)",
    "ZipVoice：填写参考录音的准确转写；内置样例无需填写":
        "ZipVoice: enter the exact reference transcript; not needed for the bundled sample",
    "播放参考录音": "Play reference",
    "恢复内置样例": "Use bundled sample",
    "浏览…": "Browse…",
    "选择参考音频": "Choose reference audio",
    "音频文件 (*.wav;*.flac;*.ogg)|*.wav;*.flac;*.ogg":
        "Audio files (*.wav;*.flac;*.ogg)|*.wav;*.flac;*.ogg",
    "合成并试听": "Synthesize and play",
    "一键生成 20 种语言试听": "Generate 20-language auditions",
    "合成后自动播放": "Play automatically",
    "就绪": "Ready",
    "合成结果与片段试听": "Generated audio and segment preview",
    "尚无合成结果。结果将自动保存到 outputs 文件夹。":
        "No generated audio yet. Results are saved automatically in the outputs folder.",
    "播放完整音频": "Play full audio",
    "试听片段": "Preview clip",
    "停止播放": "Stop",
    "另存完整 WAV": "Save full WAV",
    "导出片段 WAV": "Export clip WAV",
    "起点 / 秒": "Start / sec",
    "时长 / 秒": "Duration / sec",
    "打开结果目录": "Open output folder",
    "未播放": "Not playing",
    "播放结束": "Playback finished",
    "播放 {elapsed:.1f} / {duration:.1f} 秒": "Playing {elapsed:.1f} / {duration:.1f} sec",
    "已下载": "Downloaded",
    "缺少本地模型（约 {size:.0f} MB），请先下载全部":
        "Local model missing (about {size:.0f} MB); download all models first",
    "请手动输入 {language} 语言的试听文本": "Enter sample text in {language}",
    "日常短句": "Everyday",
    "小说片段": "Story",
    "数字与日期": "Numbers and dates",
    "疑问与语气": "Expression",
    "下载已取消。": "Download cancelled.",
    "任务已取消。": "Task cancelled.",
    "解压模型，请稍候": "Extracting model; please wait",
    "加载模型": "Loading model",
    "正在合成语音；首次推理可能较慢": "Synthesizing audio; the first inference may take longer",
    "{label}：{received:.1f} / {total:.1f} MB": "{label}: {received:.1f} / {total:.1f} MB",
    "[{index}/20] {language}：{label}": "[{index}/20] {language}: {label}",
    "{message}": "{message}",
    "失败：{error}": "Failed: {error}",
    "{error}\n\n详细信息见 tts-demo.log。": "{error}\n\nSee tts-demo.log for details.",
    "任务失败": "Task failed",
    "全部模型已就绪：{path}": "All models are ready: {path}",
    "请检查输入": "Check input",
    "合成完成，已保存：{name}": "Synthesis complete; saved: {name}",
    "缺少本地模型：{models}。请先下载全部模型。": "Local models missing: {models}. Download all models first.",
    "请检查模型": "Check models",
    "已停止": "stopped",
    "已完成": "complete",
    "20 种语言试听{state}：{completed}/20 段已保存。选择列表中的语言后点击播放。":
        "20-language audition {state}: {completed}/20 clips saved. Select a language in the list and click Play.",
    "{language} ({code}) | {model} | 音色 {sid} | {duration:.1f}s | {text}":
        "{language} ({code}) | {model} | Speaker {sid} | {duration:.1f}s | {text}",
    "已载入 {count} 段本地音频，可直接播放或截取试听。":
        "Loaded {count} local clips. Play the full audio or preview a segment.",
    "已载入 {count} 段音频，另有 {failed} 条历史记录读取失败，详见日志。":
        "Loaded {count} clips; {failed} history records could not be read. See the log.",
    "{language} | {rate} Hz | 音频 {duration:.2f}s | 推理 {elapsed:.2f}s | RTF {rtf:.3f} | 加载 {load:.2f}s":
        "{language} | {rate} Hz | Audio {duration:.2f}s | Inference {elapsed:.2f}s | RTF {rtf:.3f} | Load {load:.2f}s",
    "片段设置无效": "Invalid clip settings",
    "播放失败：{error}\n音频已保存在 outputs，可用外部播放器打开。":
        "Playback failed: {error}\nAudio is saved in outputs and can be opened in another player.",
    "播放失败": "Playback failed",
    "请先下载模型，或选择本地参考音频。": "Download the model first, or choose a local reference audio file.",
    "参考音频不可用": "Reference audio unavailable",
    "导出 WAV": "Export WAV",
    "WAV 音频 (*.wav)|*.wav": "WAV audio (*.wav)|*.wav",
    "已导出：{path}": "Exported: {path}",
    "导出失败": "Export failed",
    "系统未能打开结果目录，请手动打开 outputs。":
        "The system could not open the output folder. Open outputs manually.",
    "无法打开目录": "Could not open folder",
    "任务尚未结束。下载将取消；模型加载或合成阶段请等待完成后关闭。":
        "A task is still running. Downloads will be cancelled; wait for model loading or synthesis to finish before closing.",
    "请稍候": "Please wait",
    "无法保存界面语言设置，请检查配置写入权限。":
        "Could not save the interface language. Check permission to write the application settings.",
    "设置保存失败": "Could not save settings",
    "中文": "Chinese", "英语": "English", "日语": "Japanese", "韩语": "Korean",
    "法语": "French", "德语": "German", "西班牙语": "Spanish", "葡萄牙语": "Portuguese",
    "意大利语": "Italian", "俄语": "Russian", "阿拉伯语": "Arabic", "印地语": "Hindi",
    "印度尼西亚语": "Indonesian", "越南语": "Vietnamese", "土耳其语": "Turkish",
    "荷兰语": "Dutch", "波兰语": "Polish", "瑞典语": "Swedish", "乌克兰语": "Ukrainian",
    "罗马尼亚语": "Romanian", "保加利亚语": "Bulgarian", "克罗地亚语": "Croatian",
    "捷克语": "Czech", "丹麦语": "Danish", "爱沙尼亚语": "Estonian", "芬兰语": "Finnish",
    "希腊语": "Greek", "匈牙利语": "Hungarian", "拉脱维亚语": "Latvian", "立陶宛语": "Lithuanian",
    "斯洛伐克语": "Slovak", "斯洛文尼亚语": "Slovenian",
    "Kokoro 82M INT8 · 中英双语": "Kokoro 82M INT8 · Chinese / English",
    "Matcha · 中文女声": "Matcha · Chinese female voice",
    "ZipVoice-Distill INT8 · 中英声音克隆": "ZipVoice-Distill INT8 · Chinese / English voice cloning",
    "KittenTTS 0.8 Nano INT8 · 英文轻量": "KittenTTS 0.8 Nano INT8 · Lightweight English",
    "Pocket TTS INT8 · 英文声音克隆": "Pocket TTS INT8 · English voice cloning",
    "Piper · 中文 huayan": "Piper · Chinese huayan",
    "Piper INT8 · 英文 lessac": "Piper INT8 · English lessac",
    "Supertonic 3 INT8 · 多语言（无中文）": "Supertonic 3 INT8 · Multilingual (no Chinese)",
    "均衡朗读；53 个音色。中文推荐 45–52，英文推荐 0–27；不支持声音克隆。":
        "Balanced narration; 53 speakers. Chinese: 45–52; English: 0–27 recommended. No voice cloning.",
    "固定中文女声，适合朗读；另需下载 Vocos 声码器。":
        "Fixed Chinese female voice for narration; requires the Vocos vocoder.",
    "参考音频 + 准确转写文本；首次可使用模型包自带演示录音。仅克隆已获授权的声音。":
        "Reference audio + exact transcript. A bundled demo recording is available. Only clone authorized voices.",
    "0.8 轻量 ONNX 系列，不是 KittenTTS 2；8 个固定英文音色。":
        "Lightweight 0.8 ONNX series, not KittenTTS 2; eight preset English speakers.",
    "此下载包为英文版；参考录音无需转写。仅克隆已获授权的声音。":
        "This package is English-only; no reference transcript needed. Only clone authorized voices.",
    "固定中文音色；轻量本地朗读。音色授权请查看下载包中的模型说明。":
        "Fixed Chinese voice for lightweight local narration. Check the bundled model card for voice licensing.",
    "固定英文音色；低资源对照模型。音色授权请查看模型说明。":
        "Fixed English voice; low-resource baseline. Check the model card for voice licensing.",
    "31 种语言、10 个音色，不支持中文；上游已归档，作为试听对照。":
        "31 languages and ten speakers; no Chinese. Upstream is archived; included for comparison.",
    "模型配置校验失败，请查看控制台和模型文件。":
        "Model configuration validation failed. Check the console and model files.",
    "未知模型。": "Unknown model.",
    "请输入要合成的文本。": "Enter text to synthesize.",
    "Demo 单次最多合成 5000 个字符，请分段试听。":
        "This demo supports up to 5000 characters per synthesis. Split longer text into segments.",
    "当前模型不支持所选语言。": "The selected model does not support this speech language.",
    "当前语言不支持中文，请切换中文模型或使用对应语言文本。":
        "Chinese text is not supported by this speech language. Choose a Chinese model or use matching text.",
    "语速应在 0.5–2.0 之间。": "Speed must be between 0.5 and 2.0.",
    "线程数应为 1–16，采样步数应为 1–32。": "Use 1–16 CPU threads and 1–32 steps.",
    "ZipVoice 自定义参考音频必须填写准确的参考转写文本。":
        "Custom ZipVoice reference audio requires an accurate transcript.",
    "片段起点必须非负，时长必须大于零。":
        "The clip start must be nonnegative and its duration must be greater than zero.",
    "片段起点超出音频范围。": "The clip start is beyond the audio duration.",
    "参考音频为空、包含无效数值或静音。": "Reference audio is empty, invalid, or silent.",
    "自定义参考录音请截取为 30 秒以内，建议使用 3–10 秒干净人声。":
        "Custom reference audio must be at most 30 seconds; 3–10 seconds of clean speech is recommended.",
    "模型尚未完整下载，请先运行 prepare_models.py 下载全部模型。合成阶段不会访问网络。":
        "Local models are incomplete. Run prepare_models.py first. Synthesis does not access the network.",
    "模型尚未加载。": "The model has not been loaded.",
    "模型没有生成有效音频，请核对文本、语言和参考录音。":
        "The model did not generate valid audio. Check the text, speech language, and reference recording.",
    "模型生成了静音，请更换音色或检查参考录音。":
        "The model generated silence. Choose another speaker or check the reference recording.",
    "不支持的音频记录版本。": "Unsupported audio history version.",
    "历史音频不是有效的单声道音频。": "The history file is not valid mono audio.",
}

ERROR_PATTERNS = (
    (r"音色 ID 应为 0–(\d+)。", "Speaker ID must be between 0 and {0}."),
    (r"参考音频不存在：(.+)", "Reference audio does not exist: {0}"),
    (r"模型缺少文件：(.+)", "Model file missing: {0}"),
    (r"(.+) 中找不到文件：(.+)", "Could not find files in {0}: {1}"),
    (r"不支持的模型类型：(.+)", "Unsupported model type: {0}"),
    (r"不安全的模型压缩包条目：(.+)", "Unsafe model archive entry: {0}"),
    (r"模型目录不完整：(.+)。请将该目录移走后重试。", "Incomplete model directory: {0}. Move it aside and try again."),
    (r"(.+) 大小不符：应为 (\d+)，实际 (\d+)。请重试下载。",
     "{0} has the wrong size: expected {1}, received {2}. Download it again."),
    (r"历史音频文件校验失败：(.+)", "Audio history checksum failed: {0}"),
)


def translate(locale: str, source: str, **values: object) -> str:
    if locale not in UI_LANGUAGES:
        raise ValueError(f"Unsupported interface language: {locale}")
    template = ENGLISH[source] if locale == "en" else source
    return template.format(**values)


def diagnostic(locale: str, message: str) -> str:
    if locale == "zh":
        return message
    if locale != "en":
        raise ValueError(f"Unsupported interface language: {locale}")
    if message in ENGLISH:
        return ENGLISH[message]
    for pattern, template in ERROR_PATTERNS:
        match = re.fullmatch(pattern, message)
        if match:
            return template.format(*match.groups())
    # Keep unrecognized OS/library diagnostics intact rather than hiding details.
    return message
