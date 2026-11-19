#!/usr/bin/env python
"""Temporary standalone Gemini terminal chat test. Not part of iFive."""
import os
import sys
from google import genai

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set in environment.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    model = "gemini-3.5-flash-lite"

    print(f"Gemini Terminal Chat (model: {model})")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user.lower() in {"exit", "quit"}:
            break
        if not user:
            continue

        try:
            resp = client.models.generate_content(model=model, contents=user)
            print(f"Gemini: {resp.text}\n")
        except Exception as e:
            print(f"Error: {type(e).__name__} - Request failed\n")

if __name__ == "__main__":
    main()