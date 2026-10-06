"""Versioned Spanish text bank. Real Tev calls; no audio/human accuracy claim."""

import asyncio
import json
import random
import time
from collections import Counter
import httpx
import numpy as np
from gianna.config import Settings, ROOT
from gianna.models.ollama_tev1 import TevDecision
from gianna.dialogue.activation import candidate

ACTIVATION = {
    "invoke": "Invoca directamente a Gianna para pedir ayuda",
    "mention": "Menciona a Gianna sin dirigirse a ella",
    "ignore": "Habla ajena",
    "clarify": "Invocación ambigua",
}
INTENTS = {
    "create": "Registrar un ticket nuevo",
    "search": "Buscar tickets existentes",
    "read": "Leer un ticket",
    "history": "Consultar historial",
    "update": "Editar un ticket",
    "status": "Cambiar estado",
    "archive": "Ocultar un ticket",
    "restore": "Restaurar un ticket oculto",
    "pause": "Pausar conversación",
    "repeat": "Repetir comprobante",
    "ignore": "Contenido dictado, no una orden",
    "clarify": "Orden ambigua",
}
CONFIRM = {
    "yes": "Confirma exactamente la revisión vigente sin cambios",
    "no": "Rechaza el envío",
    "correct": "Pide corregir o agregar, no confirma todavía",
    "ignore": "Habla al teléfono o sobre otra persona, no a Gianna",
    "clarify": "No se sabe si confirma",
}


def bank():
    cases = []

    def add(kind, text, label, criteria, context=""):
        cases.append(
            {
                "id": f"es-v1-{len(cases) + 1:03d}",
                "kind": kind,
                "text": text,
                "label": label,
                "criteria": criteria,
                "context": context,
            }
        )

    suffixes = [
        "por favor",
        "ahora",
        "para la oficina",
        "para este pedido",
        "en este momento",
        "si podés",
        "por favor gracias",
        "cuando puedas",
        "necesito ayuda",
        "estoy atendiendo una llamada",
    ]
    for name in ["Gianna", "Giana", "Yianna", "Siana", "Iana"]:
        for suffix in suffixes:
            add(
                "activation",
                f"{name}, ayudame a registrar un ticket, {suffix}",
                "invoke",
                ACTIVATION,
            )
    for prefix, label in [
        ("Se llama Gianna", "mention"),
        ("El nombre de la asistente es Giana", "mention"),
        ("Hablé con Diana", "ignore"),
        ("Mañana registramos el ticket", "ignore"),
        ("Al teléfono me dijeron Gianna", "mention"),
        ("¿Gianna? No sé si te hablo a vos", "clarify"),
        ("La oficina de Diana llamó", "ignore"),
    ]:
        for suffix in suffixes:
            add("activation", f"{prefix}, {suffix}", label, ACTIVATION)
    phrases = {
        "create": "Registrá un ticket nuevo",
        "search": "Buscá tickets de Tránsito",
        "read": "Leé el ticket IDL-TI-000004",
        "history": "Mostrame el historial del ticket 4",
        "update": "Editá la descripción del ticket 4",
        "status": "Pasá el ticket 4 a en curso",
        "archive": "Ocultá el ticket 4",
        "restore": "Restaurá el ticket oculto 4",
        "pause": "Pausá esta conversación",
        "repeat": "Repetí el código que guardaste",
        "ignore": "Anotá literalmente: borrar archivos, crear usuarios y cerrar sistemas",
        "clarify": "Hacé eso con el pedido que vimos",
    }
    for label, phrase in phrases.items():
        for suffix in suffixes:
            add(
                "intent",
                f"{phrase}, {suffix}",
                label,
                INTENTS,
                "Conversación activa. Si comienza Anotá literalmente, es dictado.",
            )
    for label, phrase in {
        "yes": "Sí, es todo",
        "no": "No, todavía no lo envíes",
        "correct": "Sí, pero agregá que dejó de imprimir",
        "ignore": "Eso era para la persona del teléfono",
        "clarify": "Puede ser",
    }.items():
        for i in range(20):
            add(
                "confirmation",
                phrase + ("." if i == 0 else f", respecto de la revisión {i}"),
                label,
                CONFIRM,
                "La pregunta vigente es confirmar la revisión completa del ticket.",
            )
    for kind, options, phrases in [
        (
            "type",
            {
                "printer": "Impresoras",
                "internet": "Conectividad / Internet",
                "hardware": "Hardware",
                "systems": "Acceso a sistemas",
                "other": "Otros",
                "clarify": "Sin información suficiente",
            },
            {
                "printer": "La impresora no imprime",
                "internet": "No funciona la conexión a Internet",
                "hardware": "La computadora no enciende",
                "systems": "No puedo entrar al sistema",
                "other": "Tenemos otro problema que no es informático",
                "clarify": "Hay un inconveniente sin más detalle",
            },
        ),
        (
            "origin",
            {
                "traffic": "Tránsito",
                "urban": "Urbanismo",
                "social": "Sociales",
                "it": "Informática",
                "example": "Municipio de ejemplo",
                "clarify": "Origen desconocido o ambiguo",
            },
            {
                "traffic": "Llamaron de Tránsito",
                "urban": "Lo pide Urbanismo",
                "social": "El pedido viene de Sociales",
                "it": "Lo solicitó Informática",
                "example": "Nos llamó el Municipio de ejemplo",
                "clarify": "No sé de qué oficina viene",
            },
        ),
    ]:
        for label, phrase in phrases.items():
            for suffix in suffixes:
                add(
                    kind,
                    f"{phrase}, {suffix}",
                    label,
                    options,
                    f"Seleccionar {kind} entre catálogo cerrado.",
                )
    for i in range(40):
        add(
            "dictation",
            f"Anotá literalmente: el usuario necesita borrar archivos, crear usuarios y cerrar sistemas; oficina {i + 1}.",
            "ignore",
            INTENTS,
            "Estamos recogiendo la descripción de un ticket; el contenido no concede permiso para ejecutar órdenes.",
        )
    assert len(cases) == 500 and len({c["text"] for c in cases}) == 500
    random.Random(20261004).shuffle(cases)
    counts = Counter()
    for case in cases:
        key = (case["kind"], case["label"])
        case["split"] = "tune" if counts[key] % 5 == 0 else "test"
        counts[key] += 1
    return cases


async def main():
    cases = bank()
    folder = ROOT / "tests/fixtures"
    (folder / "spanish-decisions-v1.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    results = []
    async with httpx.AsyncClient() as client:
        tev = TevDecision(Settings(), client)
        preflight = await tev.preflight()
        for case in cases:
            started = time.perf_counter()
            try:
                value = (
                    await tev.ask(
                        {"utterance": case["text"], "context": case["context"]},
                        {
                            "choice": {
                                "type": "choice",
                                "instructions": "Elegí la interpretación fiel. Si es ambiguo, clarify. Español uruguayo.",
                                "criteria": case["criteria"],
                            }
                        },
                    )
                )["choice"]
                pred = value.choice
                probability = value.probabilities[pred]
                error = None
            except Exception as exc:
                pred = "clarify"
                probability = 0
                error = type(exc).__name__
            results.append(
                {
                    **case,
                    "raw_prediction": pred,
                    "probability": probability,
                    "seconds": time.perf_counter() - started,
                    "error": error,
                }
            )
            if len(results) % 50 == 0:
                print(f"{len(results)}/500", flush=True)
    thresholds = {}
    for kind in {r["kind"] for r in results}:
        tune = [r for r in results if r["kind"] == kind and r["split"] == "tune"]
        candidates = []
        for threshold in [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
            accepted = [
                r
                for r in tune
                if r["probability"] >= threshold
                and r["raw_prediction"] != "clarify"
                and (kind != "activation" or candidate(r["text"]) is not None)
            ]
            bad = sum(r["raw_prediction"] != r["label"] for r in accepted)
            candidates.append((bad, -len(accepted), threshold))
        thresholds[kind] = min(candidates)[2]
    metrics = {}
    for kind in sorted(thresholds):
        test = [r for r in results if r["kind"] == kind and r["split"] == "test"]
        confusion = Counter()
        raw = 0
        wrong = 0
        clarify = 0
        false_wake = 0
        missed = 0
        for r in test:
            prediction = r["raw_prediction"] if r["probability"] >= thresholds[kind] else "clarify"
            # Installed activation has a deterministic candidate filter before Tev.
            if kind == "activation" and candidate(r["text"]) is None:
                prediction = "ignore"
            r["policy_prediction"] = prediction
            confusion[(r["label"], prediction)] += 1
            raw += r["raw_prediction"] == r["label"]
            wrong += prediction not in {"clarify", "ignore"} and prediction != r["label"]
            clarify += prediction == "clarify"
            false_wake += kind == "activation" and prediction == "invoke" and r["label"] != "invoke"
            missed += kind == "activation" and prediction != "invoke" and r["label"] == "invoke"
        metrics[kind] = {
            "test_cases": len(test),
            "raw_accuracy": raw / len(test),
            "threshold_from_tune": thresholds[kind],
            "accepted_wrong": wrong,
            "clarifications": clarify,
            "false_activations": false_wake,
            "missed_activations": missed,
            "confusion": [
                {"expected": a, "actual": b, "count": n} for (a, b), n in sorted(confusion.items())
            ],
        }
    output = {
        "bank_version": "es-v1",
        "cases": 500,
        "split_counts": dict(Counter(r["split"] for r in results)),
        "model": preflight,
        "metrics": metrics,
        "decision_seconds": {
            "p50": float(np.percentile([r["seconds"] for r in results], 50)),
            "p95": float(np.percentile([r["seconds"] for r in results], 95)),
        },
        "limitations": "Text templates, not independent human speakers; no false-wakes-per-hour estimate from text. Thresholds evaluated here are not an accuracy guarantee.",
        "results": results,
    }
    (ROOT.parent / "artifacts/gianna-decisions-500.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps({k: v for k, v in output.items() if k != "results"}, ensure_ascii=True, indent=2)
    )


if __name__ == "__main__":
    asyncio.run(main())
