#!/usr/bin/env python3

import os
import socket
import difflib
import re
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np
import requests
import sounddevice as sd
from Xlib import X, display
from rapidfuzz import fuzz, process


# ============================================================
# Configuration
# ============================================================

RATE = 16000
CHANNELS = 1

# Physical Caps Lock key
PTT_KEYCODE = 66

# Keep recording briefly after Caps Lock release
POST_ROLL_SECONDS = 0.25

# Speech recognition
ASR_URL = "http://127.0.0.1:8080/v1/audio/transcriptions"
ASR_MODEL = "qwen3-asr-0.6b"

# Rewrite model
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
REWRITE_MODEL = "qwen3:4b-instruct"

# ASR technical-term bias
HOTWORDS_FILE = os.path.expanduser(
    "~/.config/voice-dictate/hotwords.txt"
)

HOTWORD_BOOST = 3.0

NOTIFY_ID = "9042"


# ============================================================
# State
# ============================================================

recording = False
transcribing = False
frames = []
stream = None

# Whether current utterance should bypass rewriting
current_raw_mode = False
current_target_window = None

lock = threading.Lock()


# ============================================================
# Notifications
# ============================================================

def status_ui(message):
    """Send status to the small desktop status window."""
    try:
        with socket.create_connection(
            ("127.0.0.1", 47653),
            timeout=0.15,
        ) as sock:
            sock.sendall(message.encode("utf-8"))
    except OSError:
        # Dictation must still work if the UI isn't running.
        pass


def notify(message, timeout=1500):
    try:
        subprocess.Popen(
            [
                "notify-send",
                "-r", NOTIFY_ID,
                "-t", str(timeout),
                "Cap to Talk",
                message,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ============================================================
# Hotwords
# ============================================================

def load_hotwords():
    if not os.path.exists(HOTWORDS_FILE):
        print("No hotwords file found.", flush=True)
        return []

    words = []
    seen = set()
    total_chars = 0

    with open(HOTWORDS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            word = line.strip()

            if not word or word.startswith("#"):
                continue

            key = word.casefold()

            if key in seen:
                continue

            if len(word) > 128:
                continue

            if len(words) >= 128:
                break

            if total_chars + len(word) > 4000:
                break

            seen.add(key)
            words.append(word)
            total_chars += len(word)

    print(
        f"Loaded {len(words)} hotwords.",
        flush=True,
    )

    return words


HOTWORDS = load_hotwords()


MASTER_HOTWORDS_FILE = os.path.expanduser(
    "~/.config/voice-dictate/master-hotwords.txt"
)


def load_master_hotwords():
    if not os.path.exists(MASTER_HOTWORDS_FILE):
        print(
            "Master hotword dictionary not found; "
            "using active hotwords only.",
            flush=True,
        )
        return list(HOTWORDS)

    words = []
    seen = set()

    with open(
        MASTER_HOTWORDS_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        for line in f:
            term = line.strip()

            if not term or term.startswith("#"):
                continue

            key = term.casefold()

            if key in seen:
                continue

            seen.add(key)
            words.append(term)

    print(
        f"Loaded {len(words)} master glossary terms.",
        flush=True,
    )

    return words


MASTER_HOTWORDS = load_master_hotwords()


def glossary_normalize(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        value.lower(),
    ).strip()


# Short terms such as IP, UI, AWS, etc. are useful when spoken
# exactly, but are too ambiguous for fuzzy correction.
FUZZY_MASTER_HOTWORDS = [
    term
    for term in MASTER_HOTWORDS
    if len(re.sub(r"[^a-z0-9]", "", term.lower())) >= 5
]



# ============================================================
# Audio
# ============================================================


def get_active_window_id():
    try:
        return subprocess.check_output(
            ["xdotool", "getactivewindow"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def window_exists(window_id):
    if not window_id:
        return False

    result = subprocess.run(
        ["xdotool", "getwindowname", str(window_id)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return result.returncode == 0


def audio_callback(indata, frame_count, time_info, status):
    if status:
        print("Audio:", status, flush=True)

    if recording:
        frames.append(indata.copy())


def start_recording(raw_mode=False):
    global recording
    global frames
    global stream
    global current_raw_mode
    global current_target_window

    with lock:
        if recording or transcribing:
            return

        frames = []
        recording = True
        current_raw_mode = raw_mode

        # Remember the window where dictation started.
        current_target_window = get_active_window_id()

        print(
            "Target window:",
            current_target_window,
            flush=True,
        )

        try:
            stream = sd.InputStream(
                samplerate=RATE,
                channels=CHANNELS,
                dtype="float32",
                callback=audio_callback,
            )

            stream.start()

        except Exception as e:
            recording = False
            stream = None

            print(
                "Microphone error:",
                repr(e),
                flush=True,
            )

            notify("⚠ Microphone error", 3000)
            return

    if raw_mode:
        print("Listening — RAW mode...", flush=True)
        notify("🎙 Recording — RAW", 60000)
        status_ui("🎙 Recording — RAW")
    else:
        print("Listening — CLEAN mode...", flush=True)
        notify("🎙 Recording", 60000)
        status_ui("🎙 Recording")


def stop_recording():
    global recording
    global stream

    # Capture the end of the final word.
    time.sleep(POST_ROLL_SECONDS)

    with lock:
        if not recording:
            return

        recording = False

        try:
            if stream is not None:
                stream.stop()
                stream.close()
        finally:
            stream = None

        captured = list(frames)
        raw_mode = current_raw_mode
        target_window = current_target_window

    if not captured:
        return

    audio = np.concatenate(captured, axis=0)

    if len(audio) < RATE * 0.20:
        return

    print("Transcribing...", flush=True)
    notify("⏳ Transcribing…", 60000)
    status_ui("⏳ Transcribing")

    threading.Thread(
        target=process_audio,
        args=(audio, raw_mode, target_window),
        daemon=True,
    ).start()


# ============================================================
# ASR
# ============================================================

def transcribe(audio):
    pcm = np.clip(audio[:, 0], -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)

    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    try:
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(pcm.tobytes())

        form_data = [
            ("model", ASR_MODEL),
            ("response_format", "json"),
        ]

        if HOTWORDS:
            form_data.append(
                ("hotword_boost", str(HOTWORD_BOOST))
            )

            for word in HOTWORDS:
                form_data.append(
                    ("hotword", word)
                )

        with open(path, "rb") as audio_file:
            response = requests.post(
                ASR_URL,
                files={
                    "file": (
                        "speech.wav",
                        audio_file,
                        "audio/wav",
                    )
                },
                data=form_data,
                timeout=120,
            )

        response.raise_for_status()

        try:
            result = response.json()
            return result.get("text", "").strip()

        except ValueError:
            return response.text.strip()

    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


# ============================================================
# Spoken -> written rewrite
# ============================================================

def select_relevant_hotwords(text, max_terms=8):
    """
    Search the ENTIRE master technical dictionary and return
    only the strongest terms relevant to this transcript.
    """

    transcript = glossary_normalize(text)
    padded_transcript = f" {transcript} "

    tokens = transcript.split()

    # Generate speech chunks up to four words long.
    chunks = []

    for size in (1, 2, 3, 4):
        for i in range(len(tokens) - size + 1):
            chunks.append(
                " ".join(tokens[i:i + size])
            )

    scores = {}

    # First collect literal matches from the complete dictionary.
    for term in MASTER_HOTWORDS:
        normalized = glossary_normalize(term)

        if not normalized:
            continue

        if f" {normalized} " in padded_transcript:
            scores[term] = 100.0

    # Then fuzzy-match every speech chunk against the complete
    # technical dictionary. RapidFuzz keeps this fast.
    for chunk in chunks:
        matches = process.extract(
            chunk,
            FUZZY_MASTER_HOTWORDS,
            scorer=fuzz.ratio,
            processor=glossary_normalize,
            score_cutoff=76.0,
            limit=4,
        )

        for term, score, _ in matches:
            previous = scores.get(term, 0.0)

            if score > previous:
                scores[term] = score

    ranked = sorted(
        scores.items(),
        key=lambda item: (
            -item[1],
            len(item[0]),
        ),
    )

    result = []

    for term, score in ranked:
        result.append(term)

        if len(result) >= max_terms:
            break

    return result


def rewrite_transcript(text):
    if len(text.split()) <= 4:
        return text

    relevant_terms = select_relevant_hotwords(text)

    system_prompt = """
Rewrite my spoken dictation into the message I intended to type.

The input comes from automatic speech recognition, so some words,
punctuation, names, or technical terms may be wrong.

Write in my voice and from my point of view.

Clean up:
- filler words
- stutters
- repeated fragments
- abandoned false starts
- awkward spoken grammar

Preserve:
- every meaningful idea and detail
- questions and requests
- uncertainty such as "I think", "maybe", "might", or "I'm not sure"
- alternatives and caveats
- reasons and examples
- technical details, names, numbers, commands, and paths
- my casual tone and profanity

If I correct myself while speaking, keep the corrected thought.

You may reorganize the text or use paragraphs when that makes my meaning
clearer, but do not summarize away distinct information.

A long ramble may become short if it genuinely repeats one idea.
A short statement may stay detailed if it contains many separate ideas.

Correct likely ASR mistakes when the intended wording is clear from context
or the supplied technical spellings.

Do not answer my message.
Do not explain it.
Do not describe me or refer to "the speaker", "the user", or "the transcript".

Output only the message I intended to type.
""".strip()

    if relevant_terms:
        system_prompt += (
            "\n\nLikely relevant technical spellings:\n"
            + "\n".join("- " + term for term in relevant_terms)
        )

    print(
        "Rewrite glossary:",
        ", ".join(relevant_terms) if relevant_terms else "(none)",
        flush=True,
    )

    payload = {
        "model": REWRITE_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": (
                    "Rewrite this raw speech transcript into the clear "
                    "written thought the speaker intended:\n\n"
                    + text
                ),
            },
        ],
        "stream": False,
        "think": False,
        "keep_alive": "5m",
        "options": {
            "temperature": 0.0,
            "num_predict": 1024,
        },
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=120,
    )

    response.raise_for_status()

    result = response.json()

    rewritten = (
        result
        .get("message", {})
        .get("content", "")
        .strip()
    )

    if not rewritten:
        return text

    if (
        len(rewritten) >= 2
        and rewritten[0] == rewritten[-1]
        and rewritten[0] in ('"', "'")
    ):
        rewritten = rewritten[1:-1].strip()

    return rewritten


# ============================================================
# Text output
# ============================================================

def normalize_for_typing(text):
    text = " ".join(text.splitlines())

    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def get_idle_ms():
    try:
        return int(
            subprocess.check_output(
                ["xprintidle"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except Exception:
        return None


def wait_for_user_pause(min_idle_ms=1000):
    """
    Wait until the user has stopped using the keyboard/mouse
    for at least min_idle_ms.
    """

    announced = False

    while True:
        idle = get_idle_ms()

        # If idle detection somehow fails, avoid breaking dictation.
        if idle is None:
            time.sleep(1.0)
            return

        if idle >= min_idle_ms:
            return

        if not announced:
            print("Waiting for user input to pause...", flush=True)
            status_ui("⌨ Waiting for pause…")
            announced = True

        time.sleep(0.10)


def type_text(text, target_window=None):
    text = normalize_for_typing(text)

    if not target_window:
        subprocess.run(
            [
                "xdotool",
                "type",
                "--clearmodifiers",
                "--delay",
                "0",
                text,
            ],
            check=True,
        )
        return

    if not window_exists(target_window):
        raise RuntimeError(
            "The original dictation target window no longer exists."
        )

    current_window = get_active_window_id()

    # If we've moved away from the dictation target, wait until
    # there's been a full second with no keyboard/mouse activity.
    if current_window != target_window:
        wait_for_user_pause(min_idle_ms=1000)

        # Re-check because the active window may have changed while waiting.
        current_window = get_active_window_id()

    status_ui("⌨ Inserting…")

    try:
        if current_window != target_window:
            subprocess.run(
                [
                    "xdotool",
                    "windowactivate",
                    "--sync",
                    str(target_window),
                ],
                check=True,
            )

            time.sleep(0.08)

        subprocess.run(
            [
                "xdotool",
                "type",
                "--clearmodifiers",
                "--delay",
                "0",
                text,
            ],
            check=True,
        )

    finally:
        if (
            current_window
            and current_window != target_window
            and window_exists(current_window)
        ):
            time.sleep(0.05)

            subprocess.run(
                [
                    "xdotool",
                    "windowactivate",
                    "--sync",
                    str(current_window),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


# ============================================================
# Full processing pipeline
# ============================================================

def process_audio(audio, raw_mode, target_window):
    global transcribing

    with lock:
        if transcribing:
            return

        transcribing = True

    try:
        raw_text = transcribe(audio)

        if not raw_text:
            print("No speech recognized.", flush=True)
            notify("No speech recognized", 1500)
            status_ui("⚠ No speech")
            return

        print(
            "RAW >",
            raw_text,
            flush=True,
        )

        if raw_mode:
            final_text = raw_text

            print(
                "RAW mode — skipping rewrite.",
                flush=True,
            )

        else:
            notify("✨ Cleaning up…", 60000)
            status_ui("✨ Cleaning up")

            try:
                final_text = rewrite_transcript(raw_text)

            except Exception as e:
                # Dictation should still work even if Ollama fails.
                print(
                    "Rewrite failed; using raw transcript:",
                    repr(e),
                    flush=True,
                )

                notify(
                    "⚠ Rewrite failed — using raw text",
                    2000,
                )

                final_text = raw_text

        print(
            "FINAL >",
            final_text,
            flush=True,
        )

        status_ui("⌨ Typing")
        type_text(final_text, target_window)

        notify("✓ Dictated", 800)
        status_ui("✓ Done")

    except Exception as e:
        print(
            "Dictation error:",
            repr(e),
            flush=True,
        )

        notify("⚠ Dictation failed", 3000)
        status_ui("⚠ Dictation failed")

    finally:
        with lock:
            transcribing = False


# ============================================================
# Keyboard
# ============================================================

def keyboard_loop():
    d = display.Display()
    root = d.screen().root

    root.grab_key(
        PTT_KEYCODE,
        X.AnyModifier,
        False,
        X.GrabModeAsync,
        X.GrabModeAsync,
    )

    d.sync()

    print(
        "Cap to Talk ready.",
        flush=True,
    )

    print(
        "Caps Lock = cleaned dictation",
        flush=True,
    )

    print(
        "Shift + Caps Lock = raw dictation",
        flush=True,
    )

    notify("Cap to Talk ready", 1200)

    try:
        while True:
            event = d.next_event()

            if (
                event.type == X.KeyPress
                and event.detail == PTT_KEYCODE
            ):
                raw_mode = bool(
                    event.state & X.ShiftMask
                )

                start_recording(
                    raw_mode=raw_mode
                )

            elif (
                event.type == X.KeyRelease
                and event.detail == PTT_KEYCODE
            ):
                stop_recording()

    finally:
        root.ungrab_key(
            PTT_KEYCODE,
            X.AnyModifier,
        )

        d.sync()


if __name__ == "__main__":
    keyboard_loop()
