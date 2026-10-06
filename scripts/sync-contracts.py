import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for app in ("frontend", "visualizer"):
    target = root / app / "contracts"
    target.mkdir(exist_ok=True)
    shutil.copyfile(root / "backend/contracts/openapi.json", target / "openapi.json")
print(
    "Snapshots locales del contrato sincronizados. Ejecutá npm run contract:update en cada SPA."
)
