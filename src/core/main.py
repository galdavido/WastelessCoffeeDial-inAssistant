import os
import sys
from ai.vision import analyze_coffee_bag
from ai.rag import get_best_grind_setting


def main(image_path: str) -> None:
    print("\n" + "=" * 50)
    print("☕ WASTELESS COFFEE DIAL-IN ASSISTANT (WCDA)")
    print("=" * 50)
    print(f"📸 Step 1: Processing image ({image_path})...")

    # 1. Analyze image with Gemini Vision API
    coffee_data = analyze_coffee_bag(image_path)

    if not coffee_data:
        print("❌ Error: Failed to extract data from the image.")
        return

    print("\n✅ Coffee data successfully extracted from the packaging:")
    for key, value in coffee_data.items():
        print(f"  - {key.capitalize()}: {value}")

    # 2. RAG search in the database based on extracted JSON
    print("\n🧠 Step 2: AI Barista searching your previous logs...")
    recommendation = get_best_grind_setting(coffee_data)

    # Print final result
    print("\n" + "=" * 50)
    print("💡 FINAL RECOMMENDATION FOR THE COFFEE:")
    print("=" * 50)
    print(recommendation)
    print("=" * 50 + "\n")


if __name__ == "__main__":
    # If a filename is provided at runtime, use it, otherwise default to "test_bag.jpg".
    target_image = "test_bag.jpg"

    if len(sys.argv) > 1:
        target_image = sys.argv[1]

    if not os.path.exists(target_image):
        print(f"❌ Error: The '{target_image}' file is not found in the folder!")
        print("Tip: Drop an image into the folder and name it test_bag.jpg!")
    else:
        main(target_image)
