"""Test-only WAV source. Every command still crosses WebRTC and the real STT."""

import asyncio
import base64
import json
from gianna.dialogue.state_machine import State

MICROPHONE = """(() => {
 const ctx = new AudioContext({sampleRate:48000});
 const dest=ctx.createMediaStreamDestination();
 const silence=ctx.createConstantSource();silence.offset.value=0;silence.connect(dest);silence.start();
 navigator.mediaDevices.getUserMedia=async constraints=>{await ctx.resume();return dest.stream;};
 window.__fixtureMicrophone={feed:async b64=>{
  await ctx.resume();const bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
  const buffer=await ctx.decodeAudioData(bytes.buffer);
  const source=ctx.createBufferSource();source.buffer=buffer;source.connect(dest);
  await new Promise(resolve=>{source.onended=resolve;source.start();});
 }};
})();"""


async def phrase(console, client, text):
    for _ in range(50):
        response = await client.post(
            "http://127.0.0.1:5002/",
            json={"text": text, "speed": 0.8, "sample_rate": 48000},
            timeout=30,
        )
        if response.status_code != 429:
            break
        await asyncio.sleep(0.2)
    response.raise_for_status()
    await console.evaluate(
        "b64=>window.__fixtureMicrophone.feed(b64)", base64.b64encode(response.content).decode()
    )
    await asyncio.sleep(5)


async def confirm_by_audio(console, client, runtime, *, utterances=None):
    """Answer an actual clarification, never convert a doubtful transcript into yes."""
    payload = dict(runtime.supervisor.draft.payload)
    draft_id = runtime.supervisor.draft.id
    prior_operations = {row["operation_id"] for row in runtime.db.operations()}
    for text in utterances or ("Sí, confirmo.", "Sí, eso es todo.", "Confirmo."):
        assert runtime.supervisor.state == State.WAITING_CONFIRMATION
        assert runtime.supervisor.draft.payload == payload
        # Hear the reviewed operation before answering; other test turns cover barge-in.
        utterance = runtime.supervisor.last_speech["utterance_id"]
        for _ in range(400):
            if any(
                json.loads(row[0]).get("utterance_id") == utterance
                for row in runtime.db.connection.execute(
                    "SELECT data FROM events WHERE kind='playback_complete'"
                )
            ):
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("Actual client playback did not complete")
        await phrase(console, client, text)
        for _ in range(100):
            if runtime.supervisor.last_receipt:
                receipt_id = runtime.supervisor.last_receipt.get("operation_id")
                if any(
                    row["operation_id"] == receipt_id
                    and row["draft_id"] == draft_id
                    and row["status"] == "succeeded"
                    for row in runtime.db.operations()
                ):
                    return
            if runtime.supervisor.state == State.WAITING_CONFIRMATION:
                break
            await asyncio.sleep(0.1)
        assert all(row["operation_id"] in prior_operations for row in runtime.db.operations()), (
            "An unconfirmed or unknown operation cannot be resent"
        )
    raise AssertionError("Three real spoken confirmations were not understood")
