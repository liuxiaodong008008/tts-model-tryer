from __future__ import annotations

import gc
import hashlib
import json
import math
import tarfile
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import sherpa_onnx as sherpa
import soundfile as sf

ROOT = Path(__file__).resolve().parent
RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
Progress = Callable[[str, int, int], None]
Samples = npt.NDArray[np.float32]


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    tag: str = "tts-models"

    @property
    def url(self) -> str:
        return f"{RELEASE}/{self.tag}/{self.name}"


@dataclass(frozen=True)
class Model:
    key: str
    title: str
    family: str
    archive: Asset
    languages: tuple[str, ...]
    description: str
    extras: tuple[Asset, ...] = ()
    speakers: int = 1
    default_sid: int = 0
    reference: str = ""
    reference_text: str = ""

    @property
    def folder(self) -> str:
        return self.archive.name.removesuffix(".tar.bz2")

    @property
    def download_mb(self) -> float:
        return (self.archive.size + sum(a.size for a in self.extras)) / 1_000_000


MODELS = (
    Model(
        "kokoro", "Kokoro 82M INT8 · 中英双语", "kokoro",
        Asset("kokoro-int8-multi-lang-v1_0.tar.bz2", 132303094),
        ("zh", "en"),
        "均衡朗读；53 个音色。中文推荐 45–52，英文推荐 0–27；不支持声音克隆。",
        speakers=53, default_sid=45,
    ),
    Model(
        "matcha", "Matcha · 中文女声", "matcha",
        Asset("matcha-icefall-zh-baker.tar.bz2", 75480460),
        ("zh",), "固定中文女声，适合朗读；另需下载 Vocos 声码器。",
        extras=(Asset("vocos-22khz-univ.onnx", 53884024, "vocoder-models"),),
    ),
    Model(
        "zipvoice", "ZipVoice-Distill INT8 · 中英声音克隆", "zipvoice",
        Asset("sherpa-onnx-zipvoice-distill-int8-zh-en-emilia.tar.bz2", 109162785),
        ("zh", "en"), "参考音频 + 准确转写文本；首次可使用模型包自带演示录音。仅克隆已获授权的声音。",
        extras=(
            Asset("vocos_24khz.onnx", 54157409, "vocoder-models"),
        ),
        reference="test_wavs/leijun-1.wav",
        reference_text="那还是三十六年前, 一九八七年. 我呢考上了武汉大学的计算机系.",
    ),
    Model(
        "kitten", "KittenTTS 0.8 Nano INT8 · 英文轻量", "kitten",
        Asset("kitten-nano-en-v0_8-int8.tar.bz2", 31220690),
        ("en",), "0.8 轻量 ONNX 系列，不是 KittenTTS 2；8 个固定英文音色。",
        speakers=8,
    ),
    Model(
        "pocket", "Pocket TTS INT8 · 英文声音克隆", "pocket",
        Asset("sherpa-onnx-pocket-tts-int8-2026-01-26.tar.bz2", 98336520),
        ("en",), "此下载包为英文版；参考录音无需转写。仅克隆已获授权的声音。",
        reference="test_wavs/bria.wav",
    ),
    Model(
        "piper-zh", "Piper · 中文 huayan", "piper",
        Asset("vits-piper-zh_CN-huayan-medium.tar.bz2", 67255926),
        ("zh",), "固定中文音色；轻量本地朗读。音色授权请查看下载包中的模型说明。",
    ),
    Model(
        "piper-en", "Piper INT8 · 英文 lessac", "piper",
        Asset("vits-piper-en_US-lessac-medium-int8.tar.bz2", 20969179),
        ("en",), "固定英文音色；低资源对照模型。音色授权请查看模型说明。",
    ),
    Model(
        "supertonic", "Supertonic 3 INT8 · 多语言（无中文）", "supertonic",
        Asset("sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2", 128774318),
        ("en", "ja", "ko", "fr", "de", "es", "pt", "it", "ar", "bg", "hr",
         "cs", "da", "nl", "et", "fi", "el", "hi", "hu", "id", "lv", "lt",
         "pl", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi"),
        "31 种语言、10 个音色，不支持中文；上游已归档，作为试听对照。",
        speakers=10, default_sid=6,
    ),
)
MODEL_BY_KEY = {m.key: m for m in MODELS}

LANGUAGE_NAMES = {
    "zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语", "fr": "法语",
    "de": "德语", "es": "西班牙语", "pt": "葡萄牙语", "it": "意大利语",
    "ru": "俄语", "ar": "阿拉伯语", "hi": "印地语", "id": "印度尼西亚语",
    "vi": "越南语", "tr": "土耳其语", "nl": "荷兰语", "pl": "波兰语",
    "sv": "瑞典语", "uk": "乌克兰语", "ro": "罗马尼亚语", "bg": "保加利亚语",
    "hr": "克罗地亚语", "cs": "捷克语", "da": "丹麦语", "et": "爱沙尼亚语",
    "fi": "芬兰语", "el": "希腊语", "hu": "匈牙利语", "lv": "拉脱维亚语",
    "lt": "立陶宛语", "sk": "斯洛伐克语", "sl": "斯洛文尼亚语",
}
AUDITION_LANGUAGES = (
    "zh", "en", "ja", "ko", "fr", "de", "es", "pt", "it", "ru",
    "ar", "hi", "id", "vi", "tr", "nl", "pl", "sv", "uk", "ro",
)

PRESETS = {
    "zh": (
        ("日常短句", "你好，欢迎试听本地语音合成。今天阳光很好，我们一起出去走走吧。"),
        ("小说片段", "雨停了，窗外的树叶还挂着水珠。她放下手里的书，轻轻推开窗，一阵清凉的风迎面吹来。"),
        ("数字与日期", "今天是二零二六年十月二十三日，下午两点半。您的订单金额是一百二十八元五角，请核对收货信息。"),
        ("疑问与语气", "真的吗？这声音竟然是在本地生成的！不用连接网络，也能听起来这么自然。"),
    ),
    "en": (
        ("Everyday", "Hello! Welcome to this offline text to speech demo. It is a beautiful day. Let's take a walk together."),
        ("Story", "The rain had stopped, but drops of water still clung to the leaves. She closed her book and opened the window."),
        ("Numbers", "Your appointment is on October twenty third, at two thirty in the afternoon. The total is one hundred and twenty eight dollars."),
        ("Expression", "Really? This voice was generated right here, without an internet connection! That sounds wonderful."),
    ),
    "ja": (("日本語", "こんにちは。これは端末内で動作する音声合成のテストです。今日はとても良い天気ですね。"),),
    "ko": (("한국어", "안녕하세요. 이것은 기기에서 실행되는 음성 합성 테스트입니다. 오늘 날씨가 정말 좋네요."),),
    "fr": (("Français", "Bonjour ! Ceci est un test de synthèse vocale hors ligne. Il fait très beau aujourd'hui."),),
    "de": (("Deutsch", "Hallo! Dies ist ein Test der lokalen Sprachausgabe. Heute ist ein wunderschöner Tag."),),
    "es": (("Español", "Hola. Esta es una prueba de síntesis de voz sin conexión. Hoy hace un día maravilloso."),),
    "pt": (("Português", "Olá! Este é um teste de síntese de voz sem conexão com a internet. Hoje está um dia muito bonito."),),
    "it": (("Italiano", "Ciao! Questa è una prova di sintesi vocale senza connessione a Internet. Oggi è una bellissima giornata."),),
    "ru": (("Русский", "Здравствуйте! Это проверка синтеза речи без подключения к интернету. Сегодня прекрасная погода."),),
    "ar": (("العربية", "مرحباً! هذا اختبار لتحويل النص إلى كلام دون اتصال بالإنترنت. الطقس جميل اليوم."),),
    "hi": (("हिन्दी", "नमस्ते! यह बिना इंटरनेट के चलने वाले वाणी संश्लेषण का परीक्षण है। आज मौसम बहुत अच्छा है।"),),
    "id": (("Bahasa Indonesia", "Halo! Ini adalah uji sintesis suara tanpa koneksi internet. Cuaca hari ini sangat cerah."),),
    "vi": (("Tiếng Việt", "Xin chào! Đây là bài kiểm tra tổng hợp giọng nói không cần kết nối internet. Hôm nay thời tiết rất đẹp."),),
    "tr": (("Türkçe", "Merhaba! Bu, internet bağlantısı olmadan çalışan bir konuşma sentezi testidir. Bugün hava çok güzel."),),
    "nl": (("Nederlands", "Hallo! Dit is een test van spraaksynthese zonder internetverbinding. Het is vandaag prachtig weer."),),
    "pl": (("Polski", "Dzień dobry! To jest test syntezy mowy bez połączenia z internetem. Dzisiaj jest piękna pogoda."),),
    "sv": (("Svenska", "Hej! Det här är ett test av talsyntes utan internetanslutning. Det är mycket vackert väder idag."),),
    "uk": (("Українська", "Вітаю! Це перевірка синтезу мовлення без підключення до інтернету. Сьогодні чудова погода."),),
    "ro": (("Română", "Bună ziua! Acesta este un test de sinteză vocală fără conexiune la internet. Astăzi este o zi foarte frumoasă."),),
}


class DownloadCancelled(Exception):
    pass


def download(asset: Asset, target: Path, progress: Progress, cancel: threading.Event) -> None:
    if target.is_file() and target.stat().st_size == asset.size:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(asset.url, headers={"User-Agent": "Local-TTS-Demo/1.0"})
    received = 0
    last_report = 0.0
    try:
        with urllib.request.urlopen(request, timeout=30) as response, partial.open("wb") as out:
            while True:
                if cancel.is_set():
                    raise DownloadCancelled("下载已取消。")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                received += len(chunk)
                if time.monotonic() - last_report > 0.2:
                    progress(asset.name, received, asset.size)
                    last_report = time.monotonic()
        if received != asset.size:
            raise OSError(f"{asset.name} 大小不符：应为 {asset.size}，实际 {received}。请重试下载。")
        partial.replace(target)
        progress(asset.name, received, asset.size)
    finally:
        partial.unlink(missing_ok=True)


def extract_archive(archive: Path, staging: Path, folder: str) -> None:
    with tarfile.open(archive, "r:bz2") as tar:
        for member in tar.getmembers():
            parts = Path(member.name.replace("\\", "/")).parts
            if (
                not parts or parts[0] != folder or ".." in parts
                or member.issym() or member.islnk()
                or not (member.isdir() or member.isfile())
            ):
                raise ValueError(f"不安全的模型压缩包条目：{member.name}")
        tar.extractall(staging, filter="data")


class ModelStore:
    def __init__(self, root: Path = ROOT / "models"):
        self.root = root

    def directory(self, model: Model) -> Path:
        return self.root / model.folder

    def ready(self, model: Model) -> bool:
        return (self.directory(model) / ".ready").is_file() and all(
            (self.root / a.name).is_file() and (self.root / a.name).stat().st_size == a.size
            for a in model.extras
        )

    def prepare(self, model: Model, progress: Progress, cancel: threading.Event) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.ready(model):
            return self.directory(model)
        for asset in model.extras:
            download(asset, self.root / asset.name, progress, cancel)
        destination = self.directory(model)
        if not (destination / ".ready").is_file():
            installing = destination / ".installing"
            if destination.exists() and not installing.is_file():
                raise FileExistsError(f"模型目录不完整：{destination}。请将该目录移走后重试。")
            archive = self.root / model.archive.name
            download(model.archive, archive, progress, cancel)
            if cancel.is_set():
                raise DownloadCancelled("下载已取消。")
            progress("解压模型，请稍候", 0, 0)
            # A completion marker avoids renaming directories held by Windows scanners.
            destination.mkdir(exist_ok=True)
            installing.write_text(model.archive.url, encoding="utf-8")
            extract_archive(archive, self.root, model.folder)
            (destination / ".ready").write_text(model.archive.url, encoding="utf-8")
            installing.unlink()
            archive.unlink()
        return destination


def required(directory: Path, name: str) -> str:
    path = directory / name
    if not path.exists():
        raise FileNotFoundError(f"模型缺少文件：{path}")
    return str(path)


def first_file(directory: Path, *names: str) -> str:
    for name in names:
        if (directory / name).is_file():
            return str(directory / name)
    raise FileNotFoundError(f"{directory} 中找不到文件：{', '.join(names)}")


def create_config(model: Model, directory: Path, shared: Path, threads: int) -> sherpa.OfflineTtsConfig:
    config = sherpa.OfflineTtsModelConfig(num_threads=threads, provider="cpu", debug=False)
    family = model.family
    if family == "kokoro":
        config.kokoro = sherpa.OfflineTtsKokoroModelConfig(
            model=first_file(directory, "model.int8.onnx", "model.onnx"),
            voices=required(directory, "voices.bin"),
            tokens=required(directory, "tokens.txt"),
            data_dir=required(directory, "espeak-ng-data"),
            dict_dir=required(directory, "dict"),
            lexicon=",".join(required(directory, n) for n in ("lexicon-us-en.txt", "lexicon-zh.txt")),
        )
    elif family == "kitten":
        config.kitten = sherpa.OfflineTtsKittenModelConfig(
            model=required(directory, "model.int8.onnx"),
            voices=required(directory, "voices.bin"),
            tokens=required(directory, "tokens.txt"),
            data_dir=required(directory, "espeak-ng-data"),
        )
    elif family == "matcha":
        config.matcha = sherpa.OfflineTtsMatchaModelConfig(
            acoustic_model=required(directory, "model-steps-3.onnx"),
            vocoder=required(shared, "vocos-22khz-univ.onnx"),
            tokens=required(directory, "tokens.txt"),
            lexicon=required(directory, "lexicon.txt"),
        )
    elif family == "piper":
        filename = "zh_CN-huayan-medium.onnx" if model.key == "piper-zh" else "en_US-lessac-medium.onnx"
        config.vits = sherpa.OfflineTtsVitsModelConfig(
            model=required(directory, filename),
            tokens=required(directory, "tokens.txt"),
            data_dir=required(directory, "espeak-ng-data"),
        )
    elif family == "zipvoice":
        config.zipvoice = sherpa.OfflineTtsZipvoiceModelConfig(
            encoder=required(directory, "encoder.int8.onnx"),
            decoder=required(directory, "decoder.int8.onnx"),
            vocoder=required(shared, "vocos_24khz.onnx"),
            tokens=required(directory, "tokens.txt"),
            lexicon=required(directory, "lexicon.txt"),
            data_dir=required(directory, "espeak-ng-data"),
        )
    elif family == "pocket":
        config.pocket = sherpa.OfflineTtsPocketModelConfig(
            lm_flow=required(directory, "lm_flow.int8.onnx"),
            lm_main=required(directory, "lm_main.int8.onnx"),
            encoder=required(directory, "encoder.onnx"),
            decoder=required(directory, "decoder.int8.onnx"),
            text_conditioner=required(directory, "text_conditioner.onnx"),
            vocab_json=required(directory, "vocab.json"),
            token_scores_json=required(directory, "token_scores.json"),
        )
    elif family == "supertonic":
        config.supertonic = sherpa.OfflineTtsSupertonicModelConfig(
            duration_predictor=required(directory, "duration_predictor.int8.onnx"),
            text_encoder=required(directory, "text_encoder.int8.onnx"),
            vector_estimator=required(directory, "vector_estimator.int8.onnx"),
            vocoder=required(directory, "vocoder.int8.onnx"),
            tts_json=required(directory, "tts.json"),
            unicode_indexer=required(directory, "unicode_indexer.bin"),
            voice_style=required(directory, "voice.bin"),
        )
    else:
        raise ValueError(f"不支持的模型类型：{family}")
    rules = []
    if family in ("kokoro", "matcha"):
        for stem in ("phone", "date", "number"):
            candidate = directory / f"{stem}{'-zh' if family == 'kokoro' else ''}.fst"
            if candidate.is_file():
                rules.append(str(candidate))
    result = sherpa.OfflineTtsConfig(model=config, rule_fsts=",".join(rules))
    if not result.validate():
        raise ValueError("模型配置校验失败，请查看控制台和模型文件。")
    return result


@dataclass(frozen=True)
class Request:
    model_key: str
    text: str
    language: str
    sid: int = 0
    speed: float = 1.0
    threads: int = 2
    steps: int = 5
    reference: str = ""
    reference_text: str = ""


def audition_requests(threads: int = 2) -> tuple[Request, ...]:
    requests = []
    for language in AUDITION_LANGUAGES:
        model = MODEL_BY_KEY["kokoro" if language == "zh" else "supertonic"]
        requests.append(Request(
            model_key=model.key, text=PRESETS[language][0][1], language=language,
            sid=model.default_sid, threads=threads, steps=8,
        ))
    return tuple(requests)


@dataclass(frozen=True)
class Result:
    path: Path
    samples: Samples
    sample_rate: int
    elapsed: float
    load_seconds: float
    request: Request

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate

    @property
    def rtf(self) -> float:
        return self.elapsed / self.duration


def validate_request(request: Request) -> Model:
    if request.model_key not in MODEL_BY_KEY:
        raise ValueError("未知模型。")
    model = MODEL_BY_KEY[request.model_key]
    if not request.text.strip():
        raise ValueError("请输入要合成的文本。")
    if len(request.text) > 5000:
        raise ValueError("Demo 单次最多合成 5000 个字符，请分段试听。")
    if request.language not in model.languages:
        raise ValueError("当前模型不支持所选语言。")
    if request.language != "zh" and any("\u3400" <= c <= "\u9fff" for c in request.text):
        if request.language not in ("ja",):
            raise ValueError("当前语言不支持中文，请切换中文模型或使用对应语言文本。")
    if not 0 <= request.sid < model.speakers:
        raise ValueError(f"音色 ID 应为 0–{model.speakers - 1}。")
    if not math.isfinite(request.speed) or not 0.5 <= request.speed <= 2.0:
        raise ValueError("语速应在 0.5–2.0 之间。")
    if not 1 <= request.threads <= 16 or not 1 <= request.steps <= 32:
        raise ValueError("线程数应为 1–16，采样步数应为 1–32。")
    if request.reference and not Path(request.reference).is_file():
        raise FileNotFoundError(f"参考音频不存在：{request.reference}")
    if model.family == "zipvoice" and request.reference and not request.reference_text.strip():
        raise ValueError("ZipVoice 自定义参考音频必须填写准确的参考转写文本。")
    return model


def clip_audio(samples: Samples, rate: int, start: float, duration: float) -> Samples:
    if rate <= 0 or not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
        raise ValueError("片段起点必须非负，时长必须大于零。")
    begin = int(start * rate)
    end = min(len(samples), int((start + duration) * rate))
    if begin >= len(samples) or end <= begin:
        raise ValueError("片段起点超出音频范围。")
    return samples[begin:end]


def load_reference(path: Path, built_in: bool = False) -> tuple[Samples, int]:
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if built_in:
        mono = mono[:10 * rate]
    if not len(mono) or not np.isfinite(mono).all() or np.max(np.abs(mono)) < 1e-5:
        raise ValueError("参考音频为空、包含无效数值或静音。")
    if len(mono) / rate > 30:
        raise ValueError("自定义参考录音请截取为 30 秒以内，建议使用 3–10 秒干净人声。")
    return mono, rate


class Engine:
    def __init__(self, store: ModelStore | None = None, output: Path = ROOT / "outputs"):
        self.store = store or ModelStore()
        self.output = output
        self._tts: sherpa.OfflineTts | None = None
        self._loaded: tuple[str, int] | None = None

    def synthesize(
        self, request: Request, progress: Progress, cancel: threading.Event,
        *, observe: Callable[[str], None] | None = None,
    ) -> Result:
        model = validate_request(request)
        if not self.store.ready(model):
            raise FileNotFoundError("模型尚未完整下载，请先运行 prepare_models.py 下载全部模型。合成阶段不会访问网络。")
        directory = self.store.directory(model)
        if cancel.is_set():
            raise DownloadCancelled("任务已取消。")
        changing_model = self._loaded != (model.key, request.threads)
        if changing_model and observe:
            observe("load_start")
        load_start = time.perf_counter()
        if changing_model:
            progress("加载模型", 0, 0)
            self._tts = None
            self._loaded = None
            gc.collect()
            self._tts = sherpa.OfflineTts(create_config(model, directory, self.store.root, request.threads))
            self._loaded = (model.key, request.threads)
        load_seconds = time.perf_counter() - load_start
        if changing_model and observe:
            observe("load_end")
        config = sherpa.GenerationConfig()
        config.sid = request.sid
        config.speed = request.speed
        config.num_steps = request.steps
        if model.family == "supertonic":
            config.extra["lang"] = request.language
        if model.family in ("zipvoice", "pocket"):
            reference = Path(request.reference) if request.reference else directory / model.reference
            mono, rate = load_reference(reference, built_in=not request.reference)
            config.reference_audio = mono
            config.reference_sample_rate = rate
            config.reference_text = request.reference_text if request.reference else model.reference_text
        progress("正在合成语音；首次推理可能较慢", 0, 0)
        if observe:
            observe("synthesis_start")
        start = time.perf_counter()
        if self._tts is None:
            raise RuntimeError("模型尚未加载。")
        generated = self._tts.generate(request.text.strip(), config)
        elapsed = time.perf_counter() - start
        if observe:
            observe("synthesis_end")
        samples = np.asarray(generated.samples, dtype=np.float32)
        if not samples.size or generated.sample_rate <= 0 or not np.isfinite(samples).all():
            raise RuntimeError("模型没有生成有效音频，请核对文本、语言和参考录音。")
        if np.max(np.abs(samples)) < 1e-5:
            raise RuntimeError("模型生成了静音，请更换音色或检查参考录音。")
        self.output.mkdir(parents=True, exist_ok=True)
        unique = time.time_ns()
        path = self.output / f"{model.key}_{unique}.wav"
        sf.write(path, samples, generated.sample_rate, subtype="PCM_16")
        metadata = {
            "schema_version": 1, "model_key": model.key,
            "model": model.title, "text": request.text, "language": request.language,
            "sid": request.sid, "speed": request.speed, "elapsed_seconds": elapsed,
            "load_seconds": load_seconds, "sample_rate": generated.sample_rate,
            "duration_seconds": len(samples) / generated.sample_rate,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        path.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return Result(path, samples, generated.sample_rate, elapsed, load_seconds, request)


def read_result(metadata_path: Path) -> Result:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata["schema_version"] != 1:
        raise ValueError("不支持的音频记录版本。")
    request = Request(
        model_key=metadata["model_key"], text=metadata["text"],
        language=metadata["language"], sid=int(metadata["sid"]), speed=float(metadata["speed"]),
    )
    validate_request(request)
    path = metadata_path.with_suffix(".wav")
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError(f"历史音频文件校验失败：{path.name}")
    samples, rate = sf.read(path, dtype="float32")
    if samples.ndim != 1 or samples.size == 0 or not np.isfinite(samples).all():
        raise ValueError("历史音频不是有效的单声道音频。")
    return Result(path, samples, rate, float(metadata["elapsed_seconds"]), float(metadata["load_seconds"]), request)
