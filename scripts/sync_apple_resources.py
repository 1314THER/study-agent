"""Bundle the same licensed math/geometry renderer used by the web app."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "apple/StudyCoach/Sources/StudyCore/Resources/Web"


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in ("geometry.js", "geometry.css"):
        shutil.copyfile(ROOT / "frontend" / name, TARGET / name)
    for name in ("katex", "jsxgraph-1.11.1", "three-0.180.0"):
        source = ROOT / "frontend/vendor" / name
        if not source.is_dir():
            raise SystemExit(f"Missing vendored renderer: {source}")
        shutil.copytree(source, TARGET / "vendor" / name, dirs_exist_ok=True)


if __name__ == "__main__":
    main()
