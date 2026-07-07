"""
Development launcher for the BARAKUDA AFM ROI Explorer.

This script starts a minimal PyQt6 application and shows the standalone
AfmRoiExplorer widget. It is intended for local development/QA only.

Usage:
    C:/Users/jirik/anaconda3/envs/barakuda/python.exe scripts/dev_afm_roi_explorer.py

No segmentation, porosity, pore metrics, or roughness is computed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repository root importable when running from scripts/.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PyQt6.QtWidgets import QApplication

from barakuda.devices.afm.ui.roi_explorer import AfmRoiExplorer


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("BARAKUDA AFM ROI Explorer (dev)")

    window = AfmRoiExplorer()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
