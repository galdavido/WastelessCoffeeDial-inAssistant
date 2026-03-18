from importlib import import_module
from typing import Any


def require_genai() -> tuple[Any, Any]:
    try:
        genai = import_module("google.genai")
        types = import_module("google.genai.types")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The google-genai package is required for AI features. Install dependencies from requirements.txt."
        ) from exc

    return genai, types


def require_pillow_image() -> Any:
    try:
        image_module = import_module("PIL.Image")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The Pillow package is required for image analysis. Install dependencies from requirements.txt."
        ) from exc

    return image_module


def load_dotenv_if_available() -> None:
    try:
        dotenv = import_module("dotenv")
    except ModuleNotFoundError:
        return

    dotenv.load_dotenv()
