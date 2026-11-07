"""
================================================================================
STROKE // ELEMENTAL WORLDS VFX DATABASE ENGINE
Indexes and queries the 4.4 MB raw VFX dump and 14,666 JSON instances
from AyanshShrivastava/elemental-worlds repository.
================================================================================
"""

import os
import re
import json
import secrets
import random
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
VFX_JSON_PATH = os.path.join(DATA_DIR, "vfx_data.json")
VFX_DUMP_PATH = os.path.join(DATA_DIR, "vfx_dump.txt")
VFX_MANIFEST_PATH = os.path.join(DATA_DIR, "VFX_ASSET_MANIFEST.md")

# Cached in-memory index
_VFX_CACHE: Dict[str, Any] = {
    "models": {},
    "instances_count": 0,
    "textures_count": 0,
    "raw_dump_text": None,
    "initialized": False
}


def load_vfx_database():
    """Initializes in-memory index of Elemental Worlds VFX dataset."""
    if _VFX_CACHE["initialized"]:
        return _VFX_CACHE

    if not os.path.exists(VFX_JSON_PATH):
        print(f"[STROKE VFX WARNING] {VFX_JSON_PATH} not found locally.", flush=True)
        return _VFX_CACHE

    try:
        with open(VFX_JSON_PATH, "r", encoding="utf-8") as f:
            items = json.load(f)

        _VFX_CACHE["instances_count"] = len(items)

        current_model = None
        for item in items:
            cname = item.get("className")
            if cname == "Model":
                name = item.get("name", "Unnamed")
                current_model = name
                if name not in _VFX_CACHE["models"]:
                    _VFX_CACHE["models"][name] = {
                        "name": name,
                        "particle_emitters": [],
                        "beams": [],
                        "parts": [],
                        "attachments": [],
                        "textures": set()
                    }
            elif current_model and current_model in _VFX_CACHE["models"]:
                m = _VFX_CACHE["models"][current_model]
                props = item.get("properties", {})
                tex = props.get("Texture")
                if tex:
                    m["textures"].add(tex)

                if cname == "ParticleEmitter":
                    m["particle_emitters"].append(item)
                elif cname == "Beam":
                    m["beams"].append(item)
                elif cname == "Part":
                    m["parts"].append(item)
                elif cname == "Attachment":
                    m["attachments"].append(item)

        # Count distinct textures
        all_textures = set()
        for m in _VFX_CACHE["models"].values():
            all_textures.update(m["textures"])
        _VFX_CACHE["textures_count"] = len(all_textures)

    except Exception as exc:
        print(f"[STROKE VFX ERROR] Failed to parse vfx_data.json: {exc}", flush=True)

    # Read raw text dump for snippet extraction
    if os.path.exists(VFX_DUMP_PATH):
        try:
            with open(VFX_DUMP_PATH, "r", encoding="utf-8") as f:
                _VFX_CACHE["raw_dump_text"] = f.read()
        except Exception as exc:
            print(f"[STROKE VFX ERROR] Failed to read vfx_dump.txt: {exc}", flush=True)

    _VFX_CACHE["initialized"] = True
    print(f"[STROKE VFX] Indexed {len(_VFX_CACHE['models'])} models, {_VFX_CACHE['instances_count']} instances, {_VFX_CACHE['textures_count']} textures from Elemental Worlds database.", flush=True)
    return _VFX_CACHE


# Canonical 5x Elemental Worlds VFX Presets for Injection Matrix
VFX_5X_PRESETS = [
    {
        "slot": 1,
        "vfx_name": "Hollow Purple (Void Singularity)",
        "element": "Void",
        "model_name": "Hollow purple",
        "primary_asset": "rbxassetid://13780268621",
        "particle_count": 12,
        "beam_count": 5,
        "color_hex": "#c15eff",
        "category": "Epic Ultimate VFX",
        "description": "Spatial convergence matrix with Grid4x4 flipbook particle emitters and curved neon beams."
    },
    {
        "slot": 2,
        "vfx_name": "Sukuna Cleave & Dismantle",
        "element": "Slash",
        "model_name": "Sukuna",
        "primary_asset": "rbxassetid://18462751521",
        "particle_count": 16,
        "beam_count": 56,
        "color_hex": "#ff3344",
        "category": "High-Velocity Domain Slash",
        "description": "Multi-angle perpendicular slicing bursts with 360-degree spread and high drag acceleration."
    },
    {
        "slot": 3,
        "vfx_name": "Flames of Fury / Infernal Judgement",
        "element": "Fire",
        "model_name": "Fireball",
        "primary_asset": "rbxassetid://9114223170",
        "particle_count": 42,
        "beam_count": 8,
        "color_hex": "#ff6600",
        "category": "Elemental Blazing Explosion",
        "description": "Blazing flame aura, trail streaks, and spherical heat shockwaves bounded by point light arrays."
    },
    {
        "slot": 4,
        "vfx_name": "Vortex of Destruction / Aqua Punches",
        "element": "Aqua",
        "model_name": "Aura_WaterBubbleTrio",
        "primary_asset": "rbxassetid://4991873131",
        "particle_count": 38,
        "beam_count": 14,
        "color_hex": "#00d4ff",
        "category": "Hydrokinetic Torrent Burst",
        "description": "Triple-vortex water bubble streams with mist textures and expanding hydro shockwaves."
    },
    {
        "slot": 5,
        "vfx_name": "Spatial Distortion / 404 Glitch Core",
        "element": "Error",
        "model_name": "Aura_TimeKillingA",
        "primary_asset": "rbxassetid://3270017",
        "particle_count": 29,
        "beam_count": 18,
        "color_hex": "#00ff66",
        "category": "Matrix Time & Glitch Rift",
        "description": "Dial torus mesh geometry paired with procedural glitch particles and chromatic rift frames."
    }
]


def extract_raw_snippet_for_model(model_name: str, max_lines: int = 12) -> str:
    """Finds raw text lines for a model from vfx_dump.txt."""
    dump = _VFX_CACHE.get("raw_dump_text")
    if not dump:
        return f"[Model] {model_name} (Loaded from Elemental Worlds database)"

    # Look for model declaration in dump text
    pattern = rf"(\[Model\]\s+{re.escape(model_name)}[\s\S]{{1,2000}}?)(?=\n\[(?:Model|Part|Folder)\]|\Z)"
    match = re.search(pattern, dump, re.IGNORECASE)
    if match:
        lines = match.group(1).strip().splitlines()
        return "\n".join(lines[:max_lines])
    
    # Fallback to searching model name
    idx = dump.find(model_name)
    if idx != -1:
        chunk = dump[max(0, idx - 40): idx + 800]
        lines = chunk.strip().splitlines()
        return "\n".join(lines[:max_lines])

    return f"[Model] {model_name} (Active in database)"


def generate_vfx_5x_records() -> List[Dict[str, Any]]:
    """
    Constructs the 5 high-density database records directly mapped to the
    Elemental Worlds VFX database, fulfilling the exact Firestore specification:
    - record_id: STRK-BAT-001..005
    - metric_load: float between 85.5 and 100.0
    - status: 'optimized'
    - integrity_hash: unique 8-byte hex
    - created_at: UTC timestamp
    + Authentic VFX fields (vfx_name, element, asset_id, particle_count, raw_snippet)
    """
    load_vfx_database()
    records = []

    for idx, preset in enumerate(VFX_5X_PRESETS, start=1):
        record_id = f"STRK-BAT-{idx:03d}"
        metric_load = round(random.uniform(85.5, 100.0), 3)
        integrity_hash = secrets.token_hex(8)
        raw_snippet = extract_raw_snippet_for_model(preset["model_name"])

        records.append({
            "record_id": record_id,
            "metric_load": metric_load,
            "status": "optimized",
            "integrity_hash": integrity_hash,
            "vfx_name": preset["vfx_name"],
            "element": preset["element"],
            "model_name": preset["model_name"],
            "primary_asset": preset["primary_asset"],
            "particle_count": preset["particle_count"],
            "beam_count": preset["beam_count"],
            "color_hex": preset["color_hex"],
            "category": preset["category"],
            "description": preset["description"],
            "raw_snippet": raw_snippet,
            "source_repo": "AyanshShrivastava/elemental-worlds",
            "created_at": datetime.now(timezone.utc)
        })

    return records


def search_vfx_database(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Performs full-text search across all models and particle emitters
    in the Elemental Worlds VFX database.
    """
    cache = load_vfx_database()
    models = cache.get("models", {})
    q = query.strip().lower()

    results = []
    for name, m in models.items():
        name_lower = name.lower()
        matched = False
        match_reason = ""

        if q in name_lower:
            matched = True
            match_reason = f"Model name match: '{name}'"
        else:
            # Check particle emitter names
            for pe in m["particle_emitters"]:
                pename = pe.get("name", "").lower()
                if q in pename:
                    matched = True
                    match_reason = f"ParticleEmitter match: '{pe.get('name')}' in {name}"
                    break

        if matched:
            pe_count = len(m["particle_emitters"])
            beam_count = len(m["beams"])
            sample_tex = list(m["textures"])[:3]
            snippet = extract_raw_snippet_for_model(name, max_lines=8)

            results.append({
                "model_name": name,
                "match_reason": match_reason,
                "particle_emitters_count": pe_count,
                "beams_count": beam_count,
                "parts_count": len(m["parts"]),
                "textures": sample_tex,
                "snippet": snippet
            })

            if len(results) >= max_results:
                break

    return results


def get_vfx_database_stats() -> Dict[str, Any]:
    """Returns top-level metrics of the Elemental Worlds VFX database."""
    cache = load_vfx_database()
    models = cache.get("models", {})

    top_models = sorted(
        [
            {
                "name": name,
                "particles": len(m["particle_emitters"]),
                "beams": len(m["beams"]),
                "parts": len(m["parts"]),
                "textures_count": len(m["textures"])
            }
            for name, m in models.items()
        ],
        key=lambda x: x["particles"] + x["beams"],
        reverse=True
    )[:10]

    return {
        "source": "AyanshShrivastava/elemental-worlds",
        "total_models": len(models),
        "total_instances": cache.get("instances_count", 0),
        "total_distinct_textures": cache.get("textures_count", 0),
        "top_high_density_models": top_models,
        "supported_elements": ["Fire", "Aqua", "Earth", "Light", "Wind", "Error", "Time", "Void", "Slash"]
    }
