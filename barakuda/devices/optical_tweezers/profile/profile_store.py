import json
from pathlib import Path
from typing import Dict, List, Any

PROFILE_DIR = Path(__file__).parent.parent.parent.parent.parent / "profiles" / "ot"

def ensure_profile_dir() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

def list_profiles() -> List[str]:
    ensure_profile_dir()
    profiles = []
    for p in PROFILE_DIR.glob("*.json"):
        profiles.append(p.stem)
    return sorted(profiles)

def load_profile(name: str) -> Dict[str, Any]:
    ensure_profile_dir()
    p = PROFILE_DIR / f"{name}.json"
    if not p.exists():
        return {}
    
    with open(p, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_profile(name: str, data: Dict[str, Any]) -> None:
    ensure_profile_dir()
    p = PROFILE_DIR / f"{name}.json"
    
    # Ensure minimal schema defaults
    if "profile_name" not in data:
        data["profile_name"] = name
    if "device_id" not in data:
        data["device_id"] = "optical_tweezers"
    if "version" not in data:
        data["version"] = 1
    if "defaults" not in data:
        data["defaults"] = {"tracking": {}, "postprocess": {}, "scale": {}, "frame_range": {}, "export": {}}
    if "per_file" not in data:
        data["per_file"] = {}

    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
