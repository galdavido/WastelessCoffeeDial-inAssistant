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


def require_jwt() -> Any:
    """PyJWT, used to verify Apple identity tokens and sign our own sessions.

    Imported lazily like the other heavy dependencies so the DB-free smoke
    tests can import the app without it, and so a missing package gives this
    message rather than an ImportError from three frames down.
    """
    try:
        return import_module("jwt")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The PyJWT package is required for Sign in with Apple. Install dependencies from requirements.txt."
        ) from exc


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
