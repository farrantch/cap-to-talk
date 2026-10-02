# AI providers

Edit your [platform's configuration file](../README.md#configuration) to use
separate speech recognition and cleanup providers, or one audio-capable model
that does both in a single request. The default remains OpenASR plus Ollama, with audio and text processed
locally. Restart Cap To Talk after editing settings.

| Stage | Provider | API |
| --- | --- | --- |
| Transcription | `openasr` | OpenASR, including its native hotword fields |
| Transcription | `openai` | OpenAI audio transcriptions |
| Transcription | `openai-compatible` | Custom audio transcriptions endpoint |
| Cleanup | `ollama` | Ollama chat |
| Cleanup | `openai` | OpenAI Chat Completions |
| Cleanup | `openai-compatible` | Custom Chat Completions endpoint |
| Cleanup | `anthropic` | Anthropic Messages |
| Cleanup | `none` | Insert the raw transcript |
| Single-model dictation | `openai` | Chat Completions with audio input and text output |
| Single-model dictation | `openai-compatible` | Compatible audio-input Chat Completions endpoint |

These provider settings work with every desktop adapter. See
[desktop setup](desktop.md) for Linux/X11 and the experimental macOS/Windows ports.

## Desktop credentials

The [desktop app](desktop-app.md) lets you choose providers and save keys in
the OS credential store. A provider profile records `api_key_source = "keyring"`
to use that store; `"environment"` remains the default for existing configurations.
The `api_key_env` field identifies the variable or saved credential, depending
on the selected source. Keys saved for one endpoint origin are not reused for
another origin.

## Local defaults

No provider configuration is required. This makes the defaults explicit:

```toml
[pipeline]
mode = "two-stage"

[transcription]
provider = "openasr"
model = "qwen3-asr-0.6b"

[rewrite]
provider = "ollama"
model = "qwen3:4b-instruct"
```

OpenASR defaults to `http://127.0.0.1:8080/v1/audio/transcriptions`; Ollama
defaults to `http://127.0.0.1:11434/api/chat`.

## One model for transcription and cleanup

An audio-capable model can listen to the recording and return the finished
message in **one request**. Select this pipeline with `mode = "single"`:

```toml
[pipeline]
mode = "single"

[dictation]
provider = "openai"
model = "gpt-audio-1.5"
max_output_tokens = 2048
```

Set `OPENAI_API_KEY` in the launch environment. The OpenAI preset sends the
WAV recording and editing instructions to `https://api.openai.com/v1/chat/completions`
and requests text output. Select a model with audio input and text output;
a text-only model or a dedicated transcription model cannot use this adapter.

An audio-capable compatible service can use the same pipeline. For example,
[Gemini's OpenAI compatibility API](https://ai.google.dev/gemini-api/docs/openai#audio_understanding)
documents this audio message format:

```toml
[pipeline]
mode = "single"

[dictation]
provider = "openai-compatible"
url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
model = "gemini-3.8-flash"
api_key_env = "GEMINI_API_KEY"
max_output_tokens = 2048
```

Set `GEMINI_API_KEY` in the launch environment. Check that the chosen model is
available to your account. A local server can also use `openai-compatible` if
its model and endpoint support audio input in this format.

In single mode:

- **The dictation key** sends instructions to remove filler and false starts while
  preserving meaning, details, uncertainty, and tone.
- **Shift + the dictation key** asks the same model for verbatim transcription.
- Only `[dictation]` is used and checked at startup. The transcription and
  cleanup profiles can stay in the file for switching back.
- Recognition hints from `hotwords.txt` are included unless
  `send_hotwords = false`. The larger master glossary is not sent: there is
  no preliminary transcript for selecting relevant terms.
- There is no independent raw transcript to recover if the request fails.
  Failed, refused, or truncated responses insert nothing.

This removes the second model request. It does not guarantee lower latency or
cost, or better wording. Compare representative recordings before choosing a
default for your setup. The adapters have automated tests with mocked responses;
these examples have not been validated against live provider accounts.

To switch back, set `[pipeline].mode = "two-stage"`. The default pipeline uses
`[transcription]` followed by optional `[rewrite]`. Setting
`[rewrite].provider = "none"` inserts the recognizer's transcript without a
cleanup pass.

## Cloud transcription with optional cleanup

For OpenAI transcription, select a transcription model available to your API
account. For example, the file transcription API supports `whisper-1`:

```toml
[transcription]
provider = "openai"
model = "whisper-1"

[rewrite]
provider = "none"
```

Set `OPENAI_API_KEY` in the environment used to launch Cap To Talk. The key is
read at request time. It is not written into the TOML file. To use a differently
named variable, set `api_key_env = "MY_SPEECH_API_KEY"`.

The OpenAI preset supplies its official transcription or Chat Completions URL
and uses `OPENAI_API_KEY`. Models are explicitly selected; switching provider
does not carry over the local Qwen model name.

To keep cleanup local, use the Ollama configuration above for `[rewrite]`.
For OpenAI cleanup instead:

```toml
[rewrite]
provider = "openai"
model = "YOUR_CHAT_COMPLETIONS_MODEL"
max_output_tokens = 2048
```

Replace the model placeholder with a Chat Completions model your account can
use. This adapter uses `max_completion_tokens`; reasoning tokens count toward
that limit. A response stopped by its token limit falls back to the raw
transcript. No tools or streaming are enabled.

## Local speech recognition with Claude cleanup

Keep `[transcription]` set to OpenASR and configure:

```toml
[rewrite]
provider = "anthropic"
model = "YOUR_CLAUDE_MODEL"
api_key_env = "ANTHROPIC_API_KEY"
max_output_tokens = 2048
```

Replace the model placeholder with a model available to your Anthropic API
account, and set `ANTHROPIC_API_KEY` in the launch environment. This uses the
Messages API at `https://api.anthropic.com/v1/messages`.

Only the transcript, cleanup instructions, and relevant vocabulary are sent to
the cleanup provider. The audio stays with the selected transcription provider.

## Other compatible services and local servers

Use `openai-compatible` when the service implements the corresponding API.
Set a **full endpoint URL**, including the route, and that service's model ID:

```toml
[transcription]
provider = "openai-compatible"
url = "https://speech.example/v1/audio/transcriptions"
model = "YOUR_SPEECH_MODEL"
api_key_env = "SPEECH_PROVIDER_API_KEY"
timeout_seconds = 120

[rewrite]
provider = "openai-compatible"
url = "http://127.0.0.1:1234/v1/chat/completions"
model = "YOUR_LOCAL_MODEL"
timeout_seconds = 120
max_output_tokens = 2048
```

These URLs and model IDs are illustrative. Use the values supplied by your
service. An unauthenticated local server can omit `api_key_env`; a hosted
service should use its own key variable. Compatible endpoints never implicitly
receive `OPENAI_API_KEY`.

The transcription API must accept a multipart WAV file, `model`, and
`response_format=json`, and return a JSON object with a string `text` field.
Recognition vocabulary uses the `prompt` field. Set `send_hotwords = false`
if the selected model does not support prompts or you do not want to send
that vocabulary.

The cleanup API must accept `model`, `messages`, `stream=false`, and
`max_tokens`, and return `choices[0].message.content`. Compatibility varies
by endpoint and model; services with different authentication or request
formats need a separate adapter.

## Settings and overrides

The `[transcription]`, `[rewrite]`, and `[dictation]` sections accept:

- `provider`, `model`, and a full `url`.
- `api_key_env`: the environment variable containing the API key.
- `timeout_seconds`: a positive request timeout, default 120 seconds.
- `health_url`: an optional GET endpoint for a connection check.

Transcription and single-model dictation also accept `send_hotwords` (default
true). Cleanup and single-model dictation accept `max_output_tokens` (default
1024). Increase this limit for longer recordings. Provider token limits, audio
limits, and context limits still apply.

Every provider setting can be overridden using
`CAP_TO_TALK_TRANSCRIPTION_<SETTING>`, `CAP_TO_TALK_REWRITE_<SETTING>`, or
`CAP_TO_TALK_DICTATION_<SETTING>`. Set `CAP_TO_TALK_PIPELINE_MODE` to override
`[pipeline].mode` (`two-stage` or `single`).
For example:

```bash
export CAP_TO_TALK_REWRITE_PROVIDER=none
export CAP_TO_TALK_TRANSCRIPTION_TIMEOUT_SECONDS=60
```

The old `[services]` section and service environment variables continue to
supply local defaults. Explicit new provider settings take precedence over
those legacy settings. New provider environment variables override TOML.

Set API keys in the environment of the actual application process. An export
in a terminal applies to applications started from that terminal; it does not
configure desktop autostart. Do not place literal API keys in this repository
or pass them in endpoint URLs.

## Install and check

The normal installer still prepares the local models. To use existing or cloud
services without downloading OpenASR, Ollama, or their models:

```bash
./install.sh --skip-local-services --no-start
# Edit ~/.config/cap-to-talk/config.toml and configure the launch environment.
cap-to-talk check --services-only
./scripts/start.sh
```

The startup script checks the active pipeline. Missing local services do
not prevent a cloud configuration from starting. In two-stage mode, an
unavailable cleanup provider produces a warning and dictation uses the raw
transcript. In single mode, the dictation provider is required; the other two
providers are not contacted.

OpenAI and Anthropic presets check their model-list endpoints with the selected
credentials. This checks connectivity and authentication, not whether the
selected model can complete a request or the account has sufficient quota.
For a restricted API key without model-list access, set `health_url = ""`.

A custom URL clears the preset health URL. Set a custom `health_url` to check
that service, or leave it empty to check configuration and key presence only.
The diagnostic output states when connectivity was not tested. An
authenticated health URL must have the same scheme, hostname, and port as
the request URL.

## Data handling and failure behavior

Selecting a remote provider sends that stage's data to the configured service.
Transcription receives audio and, when enabled, recognition hints. Cleanup
receives transcript text, instructions, and relevant glossary terms. Single-model
dictation receives the recording, editing instructions, and enabled recognition
hints. Provider billing and data handling apply to those requests.

WAV uploads are prepared in memory and their buffers are closed after success
or failure. API keys are attached
only to the request for their selected provider. Redirects are rejected rather
than forwarding data or credentials elsewhere. The app does not automatically
switch to another provider on failure.

In two-stage mode, transcription errors stop that dictation. Failed, refused,
or truncated cleanup uses the raw transcript. Shift + the dictation key skips cleanup.
Short transcripts of four words or fewer also skip cleanup.

In single mode, a failed, refused, or truncated response stops that dictation
without inserting text. Shift + the dictation key uses verbatim instructions in the
same audio request. No separate transcription or cleanup request is made.

## Adding an integration

Implement the `Transcriber`, `Rewriter`, or `AudioDictation` interface in
`src/cap_to_talk/providers.py`, register it in the corresponding factory and
configuration choices, then add request/response and error-path tests.
Recording and text insertion do not need to change.

API references used for these adapters:

- [OpenAI audio transcriptions](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create)
- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [OpenAI audio input in Chat Completions](https://developers.openai.com/api/docs/guides/audio-chat-completions)
- [Gemini audio input through OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai#audio_understanding)
- [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)
