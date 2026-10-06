# Referencias verificadas y licencias

Consultadas el 4/10/2026 y revisadas para el harness conversacional el 5/10/2026. Los clones locales de lectura en .references/ no fueron desplegados ni modificados. Los patrones se adaptaron a un harness acotado; no se importaron internals de Hermes.

| Repositorio | Commit leído | Contraste |
|---|---|---|
| [Gianna Turismo](https://github.com/NebyX1/giana-turismo) | `2de40aef8ffc6be16dc9b1da749da99c0267872c` | HEAD coincide con snapshot solicitado |
| [Hermes Agent](https://github.com/nousresearch/hermes-agent) | `667b232535c343aaa78c2eba14aa5cf1e13decd8` | Desde `7565f6477c211c315110fc12173e500f013366fc`:250 archivos,+5456/−2023 líneas |

Gianna: .env.example, voice/requirements.txt, runtime_config, manifiesto Whisper y configuración Daniela; STT/pipeline/agent/bot; denoise/input_quality/runtime/trace; hooks/store/AppShell/voiceMessages; launchers y prepare_whisper_turbo/whisper_cuda_smoke; turnos, interrupciones y tests/audio_noise/test_rejected_turn. Se leyeron módulos pequeños completos y secciones pertinentes de módulos grandes: no se afirma auditoría integral del repositorio. La referencia permite STT de más proveedores en otros modos; esta entrega instala únicamente los motores cerrados de la solicitud. Su calidad original permite logprob pobre con habla larga; aquí se exige evidencia más estricta. La configuración activa exige DeepSeek Cloud para conversación; Qwen/Tev quedan como modos históricos explícitos, sin fallback desde Cloud.

Hermes: pyproject/LICENSE, registro/discovery/ToolEntry/model_tools, interrupt_control, session_persistence y context_compressor; browser provider y políticas de foco desktop, pruebas de concurrent_interrupt/close_interrupted_tool_sequence. Se examinó registro versionado, dispatch asíncrono, final claim sin await, persistencia/dedup y política de plugins. La disponibilidad con período de gracia de Hermes no se usa como autoridad para escribir tickets. La compresión no toca IDs, payload, confirmaciones o receipts del WAL. Python operativo3.14 de la referencia queda separado de este3.12.

En la revisión del 5/10 se contrastaron [semantic_router.py](https://github.com/NebyX1/giana-turismo/blob/2de40aef8ffc6be16dc9b1da749da99c0267872c/backend/app/semantic_router.py), [conversation_memory.py](https://github.com/NebyX1/giana-turismo/blob/2de40aef8ffc6be16dc9b1da749da99c0267872c/backend/app/conversation_memory.py), main.py y persona.py, además de voice/pipeline.py y el controlador de generaciones. Se adaptaron sus llamadas nativas a herramientas y el uso de mensajes reales previos. El clasificador de etiquetas y respuestas fijas anterior no representaba ese flujo. El nuevo bucle conserva las barreras de revisión/operaciones de tickets, sin importar turismo, RAG ni sus herramientas externas.

Fuentes primarias del protocolo y patrones:

- Protocolo activo: [tool calling](https://docs.ollama.com/capabilities/tool-calling) y [API chat](https://docs.ollama.com/api/chat), con tools, mensajes assistant/tool y tool_name. DeepSeek recibe historial acotado y resultados autorizados por HTTPS directo; no usa el daemon local ni format no soportado por Cloud.

- Regresión histórica del intérprete local (fuera del flujo activo): [Qwen3 4B en Ollama](https://ollama.com/library/qwen3:4b), [salidas estructuradas](https://docs.ollama.com/capabilities/structured-outputs), [control de thinking](https://docs.ollama.com/capabilities/thinking). Se probó inferencia local con JSON validado y `think=false`; el digest probado es `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.

- [Tev1 en Ollama](https://ollama.com/library/tev1:0.8b), [protocolo de decisiones](https://ollama.com/blog/ollama-now-supports-jev-style-decision-models), [model card experimental](https://huggingface.co/togethercomputer/Tev1-0.8B-experimental), [código Tev1](https://github.com/togethercomputer/tev1).
- [Contrato oficial SystemOne](https://docs.ollama.com/api/systemone): se usa `/v1/systemone` con choice/noul/score validados, sin reemplazarlo por un chat que simule decisiones.
- [Ollama Cloud](https://docs.ollama.com/cloud), [API chat/schema](https://docs.ollama.com/api/chat).
- [Pipecat interrupciones](https://docs.pipecat.ai/pipecat/fundamentals/interruptions), [idle](https://docs.pipecat.ai/pipecat/fundamentals/detecting-user-idle), [function calling](https://docs.pipecat.ai/pipecat/learn/function-calling).
- [SmallWebRTC del cliente](https://docs.pipecat.ai/api-reference/client/js/transports/small-webrtc): permite entregar un gestor de medios mediante `mediaManager`; esta entrega usa uno nativo para evitar una dependencia del CDN del gestor predeterminado.
- [Playwright locators](https://playwright.dev/python/docs/locators), [persistent browser context](https://playwright.dev/python/docs/api/class-browsertype), [API testing](https://playwright.dev/docs/api-testing).
- [Managed agents](https://www.anthropic.com/engineering/managed-agents), [advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use), [MCP tools2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools). Patrones de referencia; no se usan servicios Anthropic ni se atribuyen sus latencias a este equipo.
- Etapa1: [civic-flow-frontend](https://github.com/IntendenciaDeLavalleja/civic-flow-frontend), [plan2026-vizualizer](https://github.com/IntendenciaDeLavalleja/plan2026-vizualizer), [plan2026-backend](https://github.com/IntendenciaDeLavalleja/plan2026-backend). El contrato real integrado es el Flask local, no esos proyectos anteriores.

Licencias registradas por separado:

| Artefacto | Evidencia |
|---|---|
| Piper runtime1.4.2 | GPL-3.0-or-later en metadata instalada; no confundir piper_version de la voz |
| Daniela high | [MODEL_CARD revisionado](https://huggingface.co/rhasspy/piper-voices/blob/c10ece1aade47bb51c153c893d14e5bf8e5b7117/es/es_AR/daniela/high/MODEL_CARD): dataset [OpenSLR61](https://www.openslr.org/61/) CC-BY-SA4.0, entrenamiento larcanio; tagMIT del repositorio no prueba licencia independiente de esos pesos |
| Whisper/CT2/faster-whisper | MIT; revisión CT2 `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` de dropbox-dash/faster-whisper-large-v3-turbo |
| Pipecat/SmartTurn | BSD-2-Clause en distribución/model card [SmartTurnv3](https://huggingface.co/pipecat-ai/smart-turn-v3) |
| Tev1 código / base / pesos | CódigoMIT; base Qwen3.5 Apache2.0; ficha de pesos experimentales indica licencia aún en definición. No inferir permiso de redistribuir pesos desde licencia del código/base |
| Hermes | MIT, Copyright2025 Nous Research; patrones independientes, no runtime incorporado |

`contracts/model-manifest.lock.json` contiene tamaños/hashes **calculados sobre los archivos realmente descargados** y fuentes/revisiones. `uv.lock`/package-lock registran paquetes; doctor y evidencia registran versiones/dispositivo/Chromium/Ollama. Pesos y claves no se incluyen en Git ni se redistribuyen con la entrega.
