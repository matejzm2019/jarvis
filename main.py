"""Jarvis text, voice, and Windows tray entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from assistant.orchestrator import JarvisOrchestrator
from config import load_config
from llm.ollama_client import ModelUnavailableError, OllamaClient, OllamaError
from utils.logging_setup import setup_logging
from utils.validation import validate_runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jarvis local Windows assistant")
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Validate config, Ollama, and gemma64")
    mode.add_argument("--text", action="store_true", help="Run the text chat loop")
    mode.add_argument("--voice", action="store_true", help="Run Phase 2 push-to-talk voice mode")
    mode.add_argument("--tray", action="store_true", help="Run Phase 3 Windows tray mode")
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    setup_logging(config.logging)
    for warning in validate_runtime(config):
        print(f"Warning: {warning}")
    async with OllamaClient(config.ollama) as client:
        try:
            health = await client.health_check()
        except ModelUnavailableError as exc:
            print(f"Error: {exc}\nSuggested command: ollama list", file=sys.stderr)
            return 2
        except OllamaError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 3
        print(f"Ollama {health['version']} ready; model {health['model']} is available.")
        if args.check:
            return 0
        if args.tray:
            from assistant.desktop_runtime import DesktopAssistantRuntime

            await DesktopAssistantRuntime(config, client, Path(args.config)).run_forever()
            return 0
        assistant = JarvisOrchestrator(config, client)
        if args.voice:
            from assistant.voice_runtime import VoiceAssistantRuntime

            await VoiceAssistantRuntime(config, assistant).run_forever()
            return 0
        print("Jarvis text mode. Type /quit to exit, /clear to clear active history.")
        while True:
            try:
                text = await asyncio.to_thread(input, "You: ")
                if text.strip().casefold() in {"/quit", "/exit"}:
                    return 0
                if text.strip().casefold() == "/clear":
                    assistant.conversation.clear()
                    print("Jarvis: Conversation history cleared.")
                    continue
                answer = await assistant.ask(text)
                if answer:
                    print(f"Jarvis: {answer}")
            except (EOFError, KeyboardInterrupt):
                return 0
            except OllamaError as exc:
                print(f"Jarvis: Local Ollama error: {exc}", file=sys.stderr)


def cli() -> None:
    """Synchronous console-script wrapper."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")
    try:
        raise SystemExit(asyncio.run(run()))
    except KeyboardInterrupt:
        raise SystemExit(0) from None


if __name__ == "__main__":
    cli()
