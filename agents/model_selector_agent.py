class ModelSelectorAgent:
    """Maps a UI preference token to a concrete Groq model ID."""

    DEFAULT = "accurate"

    def __init__(self):
        self.models = {
            "fast": "llama-3.1-8b-instant",
            "accurate": "llama-3.3-70b-versatile",
        }

    def get_model(self, preference: str = DEFAULT) -> str:
        return self.models.get(preference, self.models[self.DEFAULT])
