"""Command-line entry point: analyse one coffee-bag image and print a recipe."""

from __future__ import annotations

import argparse
import os

from ai.rag import get_best_grind_setting
from ai.vision import analyze_coffee_bag

_DEFAULT_IMAGE = os.path.join("data", "test_bag.jpg")


def run(image_path: str) -> int:
    print("\n" + "=" * 50)
    print("WASTELESS COFFEE DIAL-IN ASSISTANT (WCDA)")
    print("=" * 50)

    if not os.path.exists(image_path):
        print(f"Error: image not found: {image_path}")
        return 1

    print(f"Step 1: analysing image ({image_path})...")
    coffee_data = analyze_coffee_bag(image_path)
    if not coffee_data:
        print("Error: failed to extract data from the image.")
        return 1

    print("\nExtracted coffee data:")
    for key, value in coffee_data.items():
        print(f"  - {key.capitalize()}: {value}")

    print("\nStep 2: searching your previous logs for a recommendation...")
    recommendation = get_best_grind_setting(coffee_data)

    print("\n" + "=" * 50)
    print("RECOMMENDATION")
    print("=" * 50)
    print(recommendation)
    print("=" * 50 + "\n")
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="wcda",
        description="Analyse a coffee-bag photo and print a starting espresso recipe.",
    )
    parser.add_argument(
        "image",
        nargs="?",
        default=_DEFAULT_IMAGE,
        help=f"path to the coffee-bag image (default: {_DEFAULT_IMAGE})",
    )
    args = parser.parse_args()
    raise SystemExit(run(args.image))


if __name__ == "__main__":
    cli()
