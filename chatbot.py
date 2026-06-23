"""AI chatbot using DeepSeek API with fetched options data as context."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


def _build_context(df: Any, ticker: str) -> str:
    """Build a compact text summary of the fetched data for the AI prompt."""
    if df is None or df.empty:
        return f"No data available for {ticker}."

    lines = [f"Options data for {ticker}:"]
    lines.append(f"Total contracts: {len(df)}")
    lines.append(f"Expiration dates: {df['expiration'].nunique()}")

    # Top calls and puts by OI (up to 10 each)
    for opt_type, label in [("call", "CALLS"), ("put", "PUTS")]:
        subset = df[df["optionType"] == opt_type].nlargest(10, "openInterest")
        if not subset.empty:
            lines.append(f"\nTop 10 {label} by Open Interest:")
            for _, r in subset.iterrows():
                iv = f"{r['impliedVolatility']*100:.1f}%" if pd_notna(r.get("impliedVolatility")) else "N/A"
                delta = f"Δ={r['delta']:.3f}" if pd_notna(r.get("delta")) else ""
                lines.append(
                    f"  {r['contractSymbol']} | Strike={r['strike']} | Expiry={r['expiration']} | "
                    f"OI={int(r['openInterest'])} | IV={iv} | Bid={r.get('bid','?')} | "
                    f"Ask={r.get('ask','?')} | Last={r.get('lastPrice','?')} {delta}"
                )

    return "\n".join(lines)


def pd_notna(val: Any) -> bool:
    try:
        import pandas as pd
        return pd.notna(val)
    except Exception:
        return val is not None


def ask_deepseek(
    question: str,
    df: Any,
    ticker: str,
    api_key: str,
    model: str = "deepseek-chat",
) -> str:
    """Ask DeepSeek a question about the fetched options data.

    Args:
        question: User's natural language question.
        df: The fetched options DataFrame (current context).
        ticker: The stock ticker.
        api_key: DeepSeek API key.
        model: Model name (deepseek-chat or deepseek-reasoner).

    Returns:
        AI response string.
    """
    if not api_key:
        return "Please enter a DeepSeek API key in Settings."

    context = _build_context(df, ticker)

    system_prompt = (
        "You are an options trading analyst. Answer questions ONLY based on the options data "
        "provided below. If the data doesn't contain enough information to answer, say so. "
        "Do NOT use outside knowledge or make up data. "
        "Be concise. Use bullet points when listing multiple items. "
        "Explain IV, Greeks, and strategies in simple terms when relevant."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context data:\n\n{context}\n\nQuestion: {question}"},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.HTTPError as e:
        logger.error("DeepSeek API error: %s", e)
        if r.status_code == 401:
            return "Invalid API key. Check your DeepSeek API key in Settings."
        return f"API error ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        logger.error("DeepSeek request failed: %s", e)
        return f"Request failed: {e}"
