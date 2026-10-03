import asyncio
import contextlib
from datetime import datetime

from fastapi import WebSocket
from google import genai
from google.genai import types

import config
import prompts
import tools


def build_live_config(now: datetime) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=prompts.build_system_instruction(now))]
        ),
        tools=[types.Tool(function_declarations=tools.TOOL_DECLARATIONS)],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=config.GEMINI_VOICE
                )
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )


class LiveSession:
    def __init__(self, ws: WebSocket, trigger: str):
        self.ws = ws
        self.trigger = trigger
        self.session = None
        self.stack = None
        self.tasks = []
        self.awaiting_confirmation = False
        self.first_audio_sent = False
        self.last_state = None
        self.closed = False

    async def _start(self):
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.stack = contextlib.AsyncExitStack()
        self.session = await asyncio.wait_for(
            self.stack.enter_async_context(
                client.aio.live.connect(
                    model=config.GEMINI_LIVE_MODEL,
                    config=build_live_config(datetime.now()),
                )
            ),
            timeout=config.CONNECT_TIMEOUT_S,
        )
        await self._send_state("listening")
        await self.session.send_realtime_input(
            text=(
                prompts.GREETING_PRESENCE
                if self.trigger == "presence"
                else prompts.GREETING_BUTTON
            )
        )
        self.tasks = [
            asyncio.create_task(self._uplink()),
            asyncio.create_task(self._downlink()),
        ]