"""Build the macOS app icon from the checked-in source artwork."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "app-icon-source.png"
OUTPUT = ROOT / "NarrativeWorkbench.app" / "Contents" / "Resources" / "AppIcon.icns"


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"Icon source not found: {SOURCE}")
    if not OUTPUT.parent.is_dir():
        raise SystemExit(
            "NarrativeWorkbench.app is missing. Build the local app wrapper first."
        )

    with Image.open(SOURCE) as source:
        artwork = source.convert("RGBA")
        if artwork.width != artwork.height:
            raise SystemExit(
                f"Icon source must be square, got {artwork.width}x{artwork.height}."
            )
        artwork.resize((1024, 1024), Image.Resampling.LANCZOS).save(
            OUTPUT, format="ICNS"
        )

    print(f"AppIcon.icns written from {SOURCE}")


if __name__ == "__main__":
    main()
