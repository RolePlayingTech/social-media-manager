"""
Social Media Manager - AI Client
Generates comment replies using Claude, GPT, or Gemini.
"""

import httpx
import logging

logger = logging.getLogger("ai_client")

TONE_PRESETS = {
    "friendly": "Odpowiadaj przyjaźnie i ciepło, z entuzjazmem. Bądź pozytywny i zachęcający.",
    "professional": "Odpowiadaj profesjonalnie i merytorycznie. Bądź rzeczowy, ale uprzejmy.",
    "casual": "Odpowiadaj luźno i nieformalnie, jak do znajomego. Używaj potocznego języka.",
    "humorous": "Odpowiadaj z humorem i lekkością, ale bez przesady. Bądź dowcipny, ale z szacunkiem.",
    "educational": "Odpowiadaj merytorycznie i edukacyjnie, rozwijając temat. Dziel się dodatkową wiedzą.",
}


def get_tone_instructions(tone_preset: str, custom_tone: str = "") -> str:
    if tone_preset == "custom" and custom_tone:
        return custom_tone
    return TONE_PRESETS.get(tone_preset, TONE_PRESETS["friendly"])


def build_system_prompt(tone: str, video_title: str, video_description: str) -> str:
    return f"""Jesteś social media managerem odpowiadającym na komentarze pod filmami.

Zasady:
- Odpowiadaj W TYM SAMYM JĘZYKU co komentarz
- Pisz krótko (1-3 zdania), naturalnie, jak człowiek
- NIE używaj emoji nadmiarowo (max 1 jeśli pasuje)
- NIE zaczynaj od "Dziękujemy za komentarz" ani podobnych szablonów
- Odnoś się do treści komentarza, a nie do filmu ogólnie
- Jeśli komentarz jest krytyczny, reaguj spokojnie i merytorycznie
- Jeśli komentarz jest pytaniem, odpowiedz na pytanie

Ton odpowiedzi: {tone}

Kontekst filmu:
Tytuł: {video_title}
Opis: {video_description[:500] if video_description else '(brak opisu)'}"""


def generate_reply(provider: str, api_key: str, model: str,
                   video_title: str, video_description: str,
                   comment_text: str, commenter_name: str,
                   tone: str) -> str:
    """Generate a reply to a comment using the configured AI provider."""

    system_prompt = build_system_prompt(tone, video_title, video_description)
    user_prompt = f"Komentarz od {commenter_name}:\n\"{comment_text}\"\n\nNapisz odpowiedź:"

    if provider == "anthropic":
        return _call_anthropic(api_key, model, system_prompt, user_prompt)
    elif provider == "openai":
        return _call_openai(api_key, model, system_prompt, user_prompt)
    elif provider == "google":
        return _call_google(api_key, model, system_prompt, user_prompt)
    else:
        raise ValueError(f"Unknown AI provider: {provider}")


def _call_anthropic(api_key: str, model: str, system: str, user: str) -> str:
    with httpx.Client(timeout=60) as client:
        resp = client.post("https://api.anthropic.com/v1/messages", headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, json={
            "model": model,
            "max_tokens": 300,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        })
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Anthropic: {data['error'].get('message', data['error'])}")
        return data["content"][0]["text"].strip()


def _call_openai(api_key: str, model: str, system: str, user: str) -> str:
    with httpx.Client(timeout=60) as client:
        resp = client.post("https://api.openai.com/v1/chat/completions", headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }, json={
            "model": model,
            "max_tokens": 300,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        })
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"OpenAI: {data['error'].get('message', data['error'])}")
        return data["choices"][0]["message"]["content"].strip()


def _call_google(api_key: str, model: str, system: str, user: str) -> str:
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {"maxOutputTokens": 300},
            },
        )
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Google: {data['error'].get('message', data['error'])}")
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


# Available models per provider
MODELS = {
    "anthropic": [
        {"id": "claude-sonnet-4-5-20250514", "name": "Claude Sonnet 4.5"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
    ],
    "google": [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
    ],
}
