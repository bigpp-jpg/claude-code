#!/usr/bin/env python3
"""
socionics_debate.py — runs the Verification Debate Protocol (master_scoring_prompt.md §6)
against a piece of user text via real, separate Anthropic API calls.

This is a thin runner: all the actual typing rules, guardrails, and the
three-role debate format live in master_scoring_prompt.md. This script just
sends it as a cached system prompt and drives the Typist -> Skeptic ->
Synthesizer sequence, printing each stage as it arrives.

Setup:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...

Usage:
    python3 socionics_debate.py path/to/questionnaire.txt
    python3 socionics_debate.py --text "paste text inline"
    cat questionnaire.txt | python3 socionics_debate.py
    python3 socionics_debate.py questionnaire.txt --model claude-opus-5 --out result.json
"""

import argparse
import json
import sys
from pathlib import Path

import anthropic

DEFAULT_MODEL = "claude-sonnet-5"  # override with --model if you want Opus-tier judgment
MASTER_PROMPT_PATH = Path(__file__).parent / "master_scoring_prompt.md"

STAGE_PROMPTS = {
    "typist": (
        "Run the Verification Debate Protocol (Section 6 of the system prompt) "
        "on the text below. Produce ONLY the Typist stage: a typing per Sections "
        "1-5, with per-element evidence quotes and the specific Model A block "
        "assignment you used.\n\n"
        "--- USER TEXT ---\n{text}\n--- END USER TEXT ---"
    ),
    "skeptic": (
        "Now produce ONLY the Skeptic stage. Do not re-type. Attack the Typist's "
        "output above, addressing all four required checks from Section 6 "
        "explicitly: (a) self-aggrandizing bias, (b) register confusion, "
        "(c) Model A structural violation, (d) evidence cherry-picking."
    ),
    "synthesizer": (
        "Now produce ONLY the Synthesizer stage. Resolve each Skeptic point "
        "individually (uphold / revise / insufficient_evidence) and output the "
        "revision-delta JSON specified in Section 6 — not a fresh JSON block "
        "from scratch."
    ),
}


def load_master_prompt() -> str:
    if not MASTER_PROMPT_PATH.exists():
        sys.exit(f"master_scoring_prompt.md not found at {MASTER_PROMPT_PATH}")
    return MASTER_PROMPT_PATH.read_text(encoding="utf-8")


def print_usage(label: str, usage) -> None:
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    fresh = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    print(
        f"    [usage] {label}: cache_read={read} cache_write={created} "
        f"fresh_input={fresh} output={out}",
        file=sys.stderr,
    )


def run_debate(text: str, model: str) -> dict:
    client = anthropic.Anthropic()  # resolves ANTHROPIC_API_KEY from the environment
    master_prompt = load_master_prompt()

    system = [
        {
            "type": "text",
            "text": master_prompt,
            "cache_control": {"type": "ephemeral"},  # 5-min TTL; reused by every call below
        }
    ]

    messages: list[dict] = []
    transcript: dict[str, str] = {}

    def call(stage: str, user_text: str, temperature: float) -> str:
        messages.append({"role": "user", "content": user_text})
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
            temperature=temperature,
        )
        reply = next((b.text for b in response.content if b.type == "text"), "")
        messages.append({"role": "assistant", "content": reply})
        print_usage(stage, response.usage)
        return reply

    print("=" * 20, "THE TYPIST", "=" * 20)
    typist_out = call("typist", STAGE_PROMPTS["typist"].format(text=text), temperature=0.2)
    print(typist_out, "\n")
    transcript["typist"] = typist_out

    print("=" * 20, "THE SKEPTIC", "=" * 20)
    skeptic_out = call("skeptic", STAGE_PROMPTS["skeptic"], temperature=1.0)  # high temp, per the original design
    print(skeptic_out, "\n")
    transcript["skeptic"] = skeptic_out

    print("=" * 18, "THE SYNTHESIZER", "=" * 18)
    synth_out = call("synthesizer", STAGE_PROMPTS["synthesizer"], temperature=0.2)
    print(synth_out, "\n")
    transcript["synthesizer"] = synth_out

    return transcript


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", help="Path to a text file with the questionnaire/user text")
    parser.add_argument("--text", help="Inline text instead of a file")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--out", help="Optional path to write the full transcript as JSON")
    args = parser.parse_args()

    if args.text:
        text = args.text
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        parser.error("Provide a file path, --text, or pipe text via stdin.")

    transcript = run_debate(text, args.model)

    if args.out:
        Path(args.out).write_text(json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Full transcript written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
