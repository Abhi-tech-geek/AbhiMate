import os
import json
from typing import Optional
from groq import Groq, AuthenticationError, APIConnectionError, APIError, RateLimitError
from dotenv import load_dotenv

# override=True so editing .env and triggering a Flask reload actually picks up
# the new value (rather than silently keeping the first-loaded key).
load_dotenv(override=True)


class LLMConfigError(Exception):
    """Raised when the LLM is unreachable or misconfigured.

    The Flask route layer maps this to a friendly 502/401 with actionable text
    so the UI can show a clean toast instead of dumping a Python dict.
    """

    def __init__(self, message: str, hint: str = "", http_status: int = 502):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.http_status = http_status


def _wrap_groq_error(e: Exception) -> LLMConfigError:
    """Translate vendor errors into one user-facing exception with a hint."""
    if isinstance(e, AuthenticationError):
        return LLMConfigError(
            "Groq API key is invalid or expired.",
            hint=("Generate a fresh key at https://console.groq.com/keys, then "
                  "paste it into the .env file as GROQ_API_KEY=<key> and restart the server."),
            http_status=401,
        )
    if isinstance(e, RateLimitError):
        return LLMConfigError(
            "Groq rate limit hit. Try again in a minute.",
            hint="Free tier limits reset quickly; if you hit this often, switch to a paid plan.",
            http_status=429,
        )
    if isinstance(e, APIConnectionError):
        return LLMConfigError(
            "Could not reach Groq.",
            hint="Check your internet connection or any firewall blocking api.groq.com.",
            http_status=502,
        )
    if isinstance(e, APIError):
        return LLMConfigError(
            f"Groq returned an error: {str(e)[:200]}",
            http_status=502,
        )
    return LLMConfigError(f"LLM error: {type(e).__name__}: {str(e)[:200]}", http_status=502)


class LLMNode:
    """Unified LLM Node for querying Groq with structured JSON support."""

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key or api_key == "your_api_key_here":
            raise ValueError("GROQ_API_KEY is not set properly. Please update the .env file.")

        self.client = Groq(api_key=api_key)
        self.model = model

    def query_json(self, system_message: str, user_prompt: str, model=None, retries: int = 2) -> dict:
        """JSON-mode call with automatic retry on Groq's json_validate_failed.

        Groq occasionally rejects its own output when the LLM emits malformed
        JSON inside response_format=json_object. A retry with the same prompt
        usually succeeds (the next sampling produces valid JSON). We retry up
        to ``retries`` times before surfacing the error.
        """
        attempt = 0
        last_err = None
        while attempt <= retries:
            attempt += 1
            try:
                response = self.client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=model or self.model,
                    temperature=0.3,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                if not content:
                    return {}
                parsed = json.loads(content)
                # response_format=json_object SHOULD guarantee a dict, but
                # we defend in depth — wrap arrays so callers never see one.
                if isinstance(parsed, list):
                    return {"items": parsed}
                if not isinstance(parsed, dict):
                    raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
                return parsed
            except json.JSONDecodeError as e:
                last_err = ValueError(f"Failed to parse JSON response: {str(e)}")
                # JSON parse fails aren't retryable from our side — model already finished.
                raise last_err
            except (AuthenticationError, APIConnectionError) as e:
                # Hard auth/network fails: don't retry, raise immediately.
                raise _wrap_groq_error(e) from e
            except RateLimitError as e:
                raise _wrap_groq_error(e) from e
            except APIError as e:
                # Detect "json_validate_failed" — retryable.
                msg = str(e).lower()
                last_err = e
                if attempt <= retries and ("json_validate_failed" in msg or "failed to generate json" in msg):
                    continue
                raise _wrap_groq_error(e) from e
        if last_err:
            raise _wrap_groq_error(last_err) from last_err
        raise LLMConfigError("LLM exhausted retries", http_status=502)

    def query_text(self, system_message: str, user_prompt: str, model=None) -> str:
        try:
            response = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_prompt},
                ],
                model=model or self.model,
                temperature=0.7,
            )
        except (AuthenticationError, RateLimitError, APIConnectionError, APIError) as e:
            raise _wrap_groq_error(e) from e

        content = response.choices[0].message.content
        return content if content else ""

    # ---- Vision (multimodal) ----

    def query_vision_json(
        self,
        system_message: str,
        user_prompt: str,
        image_b64: str,
        mime_type: str = "image/png",
        model: Optional[str] = None,
        retries: int = 1,
    ) -> dict:
        """Multimodal Groq call — base64 image is encoded as a data URI in an
        image_url content part. Same JSON-shape defenses as ``query_json``.

        ``model`` defaults to ``$ABHIMATE_VISION_MODEL`` or
        ``llama-3.2-90b-vision-preview``. Falls back to the smaller 11B variant
        on a 404 (Groq has rotated which previews are hosted in the past).
        """
        if not image_b64:
            raise ValueError("query_vision_json: image_b64 is required")

        vision_default = os.environ.get(
            "ABHIMATE_VISION_MODEL", "llama-3.2-90b-vision-preview"
        )
        candidates = []
        seen = set()
        for m in (model, vision_default, "llama-3.2-11b-vision-preview"):
            if m and m not in seen:
                candidates.append(m)
                seen.add(m)

        data_url = f"data:{mime_type};base64,{image_b64}"
        last_err = None
        for chosen in candidates:
            attempt = 0
            while attempt <= retries:
                attempt += 1
                try:
                    response = self.client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_message},
                            {"role": "user", "content": [
                                {"type": "text", "text": user_prompt},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ]},
                        ],
                        model=chosen,
                        temperature=0.3,
                        response_format={"type": "json_object"},
                    )
                    content = response.choices[0].message.content
                    if not content:
                        return {}
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        return {"items": parsed}
                    if not isinstance(parsed, dict):
                        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
                    return parsed
                except json.JSONDecodeError as e:
                    raise ValueError(f"Vision call returned bad JSON: {e}")
                except (AuthenticationError, APIConnectionError) as e:
                    raise _wrap_groq_error(e) from e
                except RateLimitError as e:
                    raise _wrap_groq_error(e) from e
                except APIError as e:
                    last_err = e
                    msg = str(e).lower()
                    # 404 on this preview model → try next candidate
                    if "model" in msg and ("decommissioned" in msg or "not found"
                                            in msg or "does not exist" in msg):
                        break  # break inner loop, try next candidate
                    if "json_validate_failed" in msg or "failed to generate json" in msg:
                        if attempt <= retries:
                            continue
                    raise _wrap_groq_error(e) from e
        # All candidates failed.
        if last_err:
            raise _wrap_groq_error(last_err) from last_err
        raise LLMConfigError("No vision model accepted the request.", http_status=502)

    # ---- Health probe ----

    def ping(self) -> dict:
        """Tiny round-trip check. Returns {ok, model, error?, hint?}."""
        try:
            self.client.chat.completions.create(
                messages=[{"role": "user", "content": "ping"}],
                model=self.model,
                max_tokens=1,
                temperature=0,
            )
            return {"ok": True, "model": self.model}
        except (AuthenticationError, RateLimitError, APIConnectionError, APIError) as e:
            wrapped = _wrap_groq_error(e)
            return {
                "ok": False,
                "model": self.model,
                "error": wrapped.message,
                "hint": wrapped.hint,
                "kind": type(e).__name__,
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "model": self.model, "error": str(e), "kind": type(e).__name__}
