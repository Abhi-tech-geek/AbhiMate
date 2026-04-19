class ModelSelectorAgent:
    def __init__(self):
        # We define Groq models mapped by capabilities
        self.models = {
            "fast": "llama3-8b-8192",         # Fast reasoning
            "accurate": "llama3-70b-8192"     # Deep reasoning
        }

    def get_model(self, preference: str = "accurate") -> str:
        """Returns the appropriate Groq model ID based on proxy preference."""
        return self.models.get(preference, self.models["accurate"])
