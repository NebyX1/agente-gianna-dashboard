import httpx
from gianna.models.decision_protocol import Choice, Noul, Score


class TevDecision:
    def __init__(self, config, client):
        self.config, self.client = config, client
        self.digest = None
        self.last_error = None

    async def preflight(self):
        c = self.config
        version = (await self.client.get(c.ollama_url + "/api/version")).json()["version"]
        parts = tuple(int(x) for x in version.split(".")[:2])
        if parts < (0, 35):
            raise RuntimeError("Ollama >=0.35 required for systemone")
        tags = (await self.client.get(c.ollama_url + "/api/tags")).json()["models"]
        match = next((m for m in tags if m["name"] == c.tev_model), None)
        if not match:
            raise RuntimeError("tev1:0.8b is not installed")
        self.digest = match["digest"]
        value = await self.ask(
            {"text": "Gianna, registrá un ticket"},
            {
                "intent": {
                    "type": "choice",
                    "instructions": "Clasificar la orden directa en español",
                    "criteria": {"create": "Crear ticket", "ignore": "Conversación sin orden"},
                }
            },
            timeout=180,
        )
        if "intent" not in value:
            raise RuntimeError("Tev preflight failed")
        return {"version": version, "digest": self.digest, "decision": value["intent"].model_dump()}

    async def ask(self, state, questions, *, timeout=None):
        if len(str(state)) + len(str(questions)) > 7200:
            raise ValueError("Tev context budget exceeded")
        for q in questions.values():
            if q["type"] == "choice" and not 2 <= len(q["criteria"]) <= 24:
                raise ValueError("Tev requires 2-24 closed candidates")
        r = await self.client.post(
            self.config.ollama_url + "/v1/systemone",
            json={
                "model": self.config.tev_model,
                "state": state,
                "questions": questions,
                "keep_alive": "30m",
            },
            timeout=timeout or self.config.tev_timeout,
        )
        r.raise_for_status()
        raw = r.json()
        answers = raw["answers"]
        if set(answers) != set(questions):
            raise ValueError("Tev returned unknown/missing question")
        parsed = {}
        for name, q in questions.items():
            kind = {"choice": Choice, "noul": Noul, "score": Score}[q["type"]]
            value = kind.model_validate(answers[name])
            if isinstance(value, Choice) and set(value.probabilities) != set(q["criteria"]):
                raise ValueError("Tev returned unknown labels")
            parsed[name] = value
        return parsed

    async def choose(self, text, criteria, context=""):
        self.last_error = None
        try:
            value = (
                await self.ask(
                    {"utterance": text, "context": context},
                    {
                        "choice": {
                            "type": "choice",
                            "instructions": "Elegí la interpretación fiel. Si es ambiguo, clarify. Español uruguayo.",
                            "criteria": criteria,
                        }
                    },
                )
            )["choice"]
            p = value.probabilities[value.choice]
            # Heuristic gate, not a calibrated accuracy claim.
            threshold = (
                self.config.activation_threshold
                if "invoke" in criteria
                else self.config.catalog_threshold
            )
            return value.choice if p >= threshold else "clarify"
        except (httpx.HTTPError, ValueError, KeyError):
            self.last_error = "decision_unavailable"
            return "clarify"
