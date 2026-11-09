"""
================================================================================
STROKE // UNIVERSAL MCP (MODEL CONTEXT PROTOCOL) BRIDGE ENGINE
Connects Stroke AI to Roblox Studio MCP, GitHub MCP, and External MCP Servers.
Enables AI Agents to directly execute Luau in Studio and commit changes to GitHub.
================================================================================
"""

import os
import sys
import shutil
import json
import asyncio
import httpx
from typing import Dict, List, Any, Optional

MCP_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mcp_config.json")
GITHUB_API_BASE = "https://api.github.com"

# Registry of connected MCP servers (loaded dynamically from mcp_config.json)
_MCP_REGISTRY: Dict[str, Dict[str, Any]] = {}


def get_roblox_studio_tools() -> List[Dict[str, Any]]:
    """Official Roblox Studio MCP tool definitions (35 tools across all Studio capabilities)."""
    return [
        # --- Script Management ---
        {
            "name": "execute_luau",
            "description": "Executes live Luau script in Roblox Studio to construct VFX models, configure ParticleEmitters, or update DataModel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "The exact Luau code to execute in Roblox Studio."},
                    "target_parent": {"type": "string", "description": "Target container (e.g. 'ReplicatedStorage.VFX', 'Workspace'). Defaults to 'workspace'."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID when multiple Roblox Studio instances are open."}
                },
                "required": ["code"]
            }
        },
        {
            "name": "studio_execute_luau",
            "description": "Executes live Luau script in Roblox Studio (alias for execute_luau).",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "The exact Luau code to execute in Roblox Studio."},
                    "target_parent": {"type": "string", "description": "Target container (e.g. 'ReplicatedStorage.VFX', 'Workspace'). Defaults to 'ReplicatedStorage.VFX'."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["code"]
            }
        },
        {
            "name": "script_read",
            "description": "Reads the source code of a Script, LocalScript, or ModuleScript in Roblox Studio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_path": {"type": "string", "description": "DataModel path to the script (e.g. 'ReplicatedStorage.Controllers.VFXController')."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["script_path"]
            }
        },
        {
            "name": "multi_edit",
            "description": "Applies multiple atomic edits, replacements, or insertions to scripts in Studio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "script_path": {"type": "string"},
                                "target_content": {"type": "string"},
                                "replacement_content": {"type": "string"}
                            },
                            "required": ["script_path", "target_content", "replacement_content"]
                        },
                        "description": "List of edit operations to execute atomically."
                    },
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["edits"]
            }
        },
        {
            "name": "script_search",
            "description": "Searches for Luau scripts and modules across the active Roblox Studio DataModel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Function name, module name, or keyword to search for."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["query"]
            }
        },
        {
            "name": "studio_search_scripts",
            "description": "Searches for Luau scripts and modules across the active Roblox Studio DataModel (alias for script_search).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Function name, module name, or keyword to search for."}
                },
                "required": ["query"]
            }
        },
        {
            "name": "script_grep",
            "description": "Executes regex search across script contents in the active Roblox Studio project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to match in script code."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["pattern"]
            }
        },
        # --- Asset & Content Generation ---
        {
            "name": "generate_mesh",
            "description": "Generates a 3D mesh model from text prompt via Roblox generation pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed description of the 3D model/mesh to generate."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["prompt"]
            }
        },
        {
            "name": "generate_material",
            "description": "Generates PBR materials and texture maps (color, normal, roughness) for Roblox parts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Description of the material surface (e.g. 'cracked volcanic basalt', 'sci-fi glowing panel')."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["prompt"]
            }
        },
        {
            "name": "generate_procedural_model",
            "description": "Constructs procedural 3D structures (castles, arenas, towers, dungeons) in Studio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Architectural prompt or procedural layout instructions."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["prompt"]
            }
        },
        {
            "name": "generate_texture",
            "description": "Generates 2D texture images for decals, particles, and surfaces.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Texture prompt (e.g. 'purple electrical spark burst', 'fire ring')."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["prompt"]
            }
        },
        {
            "name": "generate_animation",
            "description": "Generates keyframe animation for R15/R6 characters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Animation description (e.g. 'sword slash with jump', 'spell cast stance')."},
                    "rig_type": {"type": "string", "description": "'R15' or 'R6'. Defaults to 'R15'."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["prompt"]
            }
        },
        {
            "name": "generate_scene",
            "description": "Generates complete themed environment scene with lighting and atmosphere in Studio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Theme prompt (e.g. 'cyberpunk alleyway at night', 'cyber matrix arena')."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["prompt"]
            }
        },
        {
            "name": "segment_mesh",
            "description": "Segments a composite mesh into editable parts or sub-components.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mesh_id": {"type": "string", "description": "Mesh asset ID to segment."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["mesh_id"]
            }
        },
        {
            "name": "wait_job_finished",
            "description": "Polls status and waits for an asynchronous asset generation job to complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Generation job ID."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["job_id"]
            }
        },
        {
            "name": "search_asset",
            "description": "Searches the Roblox Creator Store and toolbox for verified models, audio, and meshes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword or asset name."},
                    "category": {"type": "string", "description": "Asset category ('Model', 'MeshPart', 'Audio', 'Decal')."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["query"]
            }
        },
        {
            "name": "insert_asset",
            "description": "Inserts a verified Roblox asset into the Studio DataModel by Asset ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string", "description": "The Roblox asset string or numeric ID (e.g. 'rbxassetid://13780268621')."},
                    "target_folder": {"type": "string", "description": "Target folder (e.g. 'Workspace', 'ReplicatedStorage.VFX'). Defaults to 'Workspace'."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["asset_id"]
            }
        },
        {
            "name": "studio_insert_vfx_asset",
            "description": "Inserts a verified Roblox asset into the Studio DataModel (alias for insert_asset).",
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string", "description": "The Roblox asset string (e.g. 'rbxassetid://13780268621')."},
                    "target_folder": {"type": "string", "description": "Folder to insert into. Defaults to 'ReplicatedStorage.VFX'."}
                },
                "required": ["asset_id"]
            }
        },
        {
            "name": "upload_image",
            "description": "Uploads an image file to Roblox cloud / Studio as an asset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the local image file."},
                    "name": {"type": "string", "description": "Asset display name."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["file_path"]
            }
        },
        {
            "name": "store_image",
            "description": "Stores an image in the local Studio session storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_data": {"type": "string", "description": "Base64 encoded image data."},
                    "name": {"type": "string", "description": "Asset identifier."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["image_data"]
            }
        },
        # --- DataModel Exploration ---
        {
            "name": "search_game_tree",
            "description": "Searches for Instances in the active DataModel by ClassName, Name, or Attribute.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Instance name or search term."},
                    "class_name": {"type": "string", "description": "Optional ClassName filter (e.g. 'ParticleEmitter', 'BasePart', 'Model')."},
                    "root": {"type": "string", "description": "Starting path (default 'Workspace')."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["query"]
            }
        },
        {
            "name": "inspect_instance",
            "description": "Inspects detailed properties, attributes, and tags of a DataModel Instance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_path": {"type": "string", "description": "DataModel path (e.g. 'Workspace.SpawnLocation')."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["instance_path"]
            }
        },
        # --- Playtesting & Simulation ---
        {
            "name": "get_studio_state",
            "description": "Retrieves the current execution state of Roblox Studio ('Edit', 'Play', 'Run', 'Paused').",
            "parameters": {
                "type": "object",
                "properties": {
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                }
            }
        },
        {
            "name": "start_stop_play",
            "description": "Starts, pauses, or stops simulation or playtesting in Studio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["play", "run", "pause", "stop"], "description": "Simulation action."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["action"]
            }
        },
        {
            "name": "get_console_output",
            "description": "Reads output log lines and error diagnostics from the Roblox Studio command console.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_lines": {"type": "integer", "description": "Maximum number of lines to retrieve (default 30)."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                }
            }
        },
        {
            "name": "studio_get_console",
            "description": "Reads output log lines from the Roblox Studio command console (alias for get_console_output).",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_lines": {"type": "integer", "description": "Maximum number of lines to retrieve (default 30)."}
                }
            }
        },
        # --- Player Input & Automation ---
        {
            "name": "screen_capture",
            "description": "Captures a screenshot of the active 3D Studio viewport.",
            "parameters": {
                "type": "object",
                "properties": {
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                }
            }
        },
        {
            "name": "character_navigation",
            "description": "Moves or navigates the player character to a destination Vector3 in playtest mode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[x, y, z] target world coordinate."
                    },
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["destination"]
            }
        },
        {
            "name": "user_keyboard_input",
            "description": "Simulates keyboard keystroke events in Studio playtest.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key identifier (e.g. 'W', 'Space', 'E')."},
                    "event": {"type": "string", "enum": ["press", "down", "up"], "description": "Key event type."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["key"]
            }
        },
        {
            "name": "user_mouse_input",
            "description": "Simulates mouse click or motion in the 3D viewport.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["click", "down", "up", "move"], "description": "Mouse action."},
                    "x": {"type": "integer", "description": "Screen X coordinate."},
                    "y": {"type": "integer", "description": "Screen Y coordinate."},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["action"]
            }
        },
        {
            "name": "auto_setup_avatar",
            "description": "Sets up standard character avatar rig (R15 or R6) in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rig_type": {"type": "string", "enum": ["R15", "R6"], "description": "Avatar rig type. Defaults to R15."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                }
            }
        },
        # --- Skills & Extensibility ---
        {
            "name": "list_skills",
            "description": "Lists installed custom Studio automation skills.",
            "parameters": {
                "type": "object",
                "properties": {
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                }
            }
        },
        {
            "name": "create_skill",
            "description": "Creates a new custom Studio automation skill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name."},
                    "description": {"type": "string", "description": "Skill description."},
                    "code": {"type": "string", "description": "Luau execution code."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["name", "code"]
            }
        },
        {
            "name": "edit_skill",
            "description": "Edits an existing Studio skill definition.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name."},
                    "code": {"type": "string", "description": "Updated Luau code."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["name", "code"]
            }
        },
        {
            "name": "skill",
            "description": "Invokes an installed Studio skill by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name to invoke."},
                    "parameters": {"type": "object", "description": "Arguments payload."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["name"]
            }
        },
        {
            "name": "subagent",
            "description": "Dispatches an autonomous Studio subagent task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "Subagent instructions."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["instruction"]
            }
        },
        {
            "name": "http_get",
            "description": "Performs an HTTP GET request within Studio's secure sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target URL."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["url"]
            }
        },
        {
            "name": "open_cloud_invoke",
            "description": "Invokes Roblox Open Cloud API operations (DataStores, MessagingService, Assets).",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "description": "Open Cloud API operation."},
                    "payload": {"type": "object", "description": "Operation arguments."},
                    "studio_id": {"type": "string", "description": "Optional studio session ID."}
                },
                "required": ["operation"]
            }
        },
        # --- Multi-Studio Session Management ---
        {
            "name": "list_roblox_studios",
            "description": "Lists all active Roblox Studio instances, returning studio_id, process ID, and place info.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    ]


def get_github_tools() -> List[Dict[str, Any]]:
    """Complete GitHub MCP tool definitions."""
    return [
        {
            "name": "github_list_repos",
            "description": "Lists repositories accessible to the configured GitHub Personal Access Token.",
            "parameters": {
                "type": "object",
                "properties": {
                    "visibility": {"type": "string", "enum": ["all", "public", "private"], "description": "Visibility filter."},
                    "per_page": {"type": "integer", "description": "Number of repositories to return (default 30)."}
                }
            }
        },
        {
            "name": "github_get_file_contents",
            "description": "Reads file contents directly from a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo'."},
                    "path": {"type": "string", "description": "Path to the file."},
                    "ref": {"type": "string", "description": "Optional git branch, tag, or commit SHA."}
                },
                "required": ["repo", "path"]
            }
        },
        {
            "name": "github_commit_file",
            "description": "Creates or updates a file directly in a GitHub repository (requires user confirmation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo'."},
                    "path": {"type": "string", "description": "File path within repository (e.g. 'src/client/VFXController.luau')."},
                    "content": {"type": "string", "description": "Full file content string."},
                    "commit_message": {"type": "string", "description": "Descriptive git commit message."},
                    "branch": {"type": "string", "description": "Target branch."},
                    "confirmed": {"type": "boolean", "description": "Explicit user authorization to write/commit. Must be true to execute."}
                },
                "required": ["repo", "path", "content", "commit_message"]
            }
        },
        {
            "name": "github_list_branches",
            "description": "Lists branches in a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo'."}
                },
                "required": ["repo"]
            }
        },
        {
            "name": "github_create_branch",
            "description": "Creates a new git branch in a repository (requires user confirmation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo'."},
                    "new_branch": {"type": "string", "description": "Name of new branch."},
                    "from_branch": {"type": "string", "description": "Source branch (default 'main')."},
                    "confirmed": {"type": "boolean", "description": "Explicit user authorization."}
                },
                "required": ["repo", "new_branch"]
            }
        },
        {
            "name": "github_list_issues",
            "description": "Lists issues in a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo'."},
                    "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "Issue state filter."}
                },
                "required": ["repo"]
            }
        },
        {
            "name": "github_create_issue",
            "description": "Creates a new issue in a GitHub repository (requires user confirmation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo'."},
                    "title": {"type": "string", "description": "Issue title."},
                    "body": {"type": "string", "description": "Issue description / body."},
                    "confirmed": {"type": "boolean", "description": "Explicit user authorization."}
                },
                "required": ["repo", "title"]
            }
        },
        {
            "name": "github_list_pull_requests",
            "description": "Lists pull requests in a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo'."},
                    "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "PR state filter."}
                },
                "required": ["repo"]
            }
        },
        {
            "name": "github_create_pull_request",
            "description": "Creates a pull request on GitHub (requires user confirmation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo'."},
                    "title": {"type": "string", "description": "Pull request title."},
                    "head": {"type": "string", "description": "Name of the branch containing changes."},
                    "base": {"type": "string", "description": "Name of branch you want to merge into (default: 'main')."},
                    "body": {"type": "string", "description": "PR description."},
                    "confirmed": {"type": "boolean", "description": "Explicit user authorization."}
                },
                "required": ["repo", "title", "head"]
            }
        }
    ]


def tools_search(query: str, category: Optional[str] = None) -> Dict[str, Any]:
    """
    Dynamic Tool Discovery / Two-Tier Catalog Search.
    Discovers tools matching a query across Studio, GitHub, and custom MCP servers.
    """
    all_tools = get_roblox_studio_tools() + get_github_tools()
    try:
        from mcp_client import global_mcp_registry
        for t in global_mcp_registry.list_all_tools():
            all_tools.append({
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"]
            })
    except Exception:
        pass

    q = query.lower().strip()
    matches = []
    for t in all_tools:
        name = t["name"].lower()
        desc = t.get("description", "").lower()
        if q in name or q in desc or not q:
            matches.append(t)

    return {
        "status": "success",
        "query": query,
        "count": len(matches),
        "match_count": len(matches),
        "matches": matches[:10],
        "tools": matches[:10]
    }


def list_roblox_studios_sync() -> Dict[str, Any]:
    """Inspects operating system processes for active Roblox Studio instances."""
    import subprocess
    studios = []
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(["ps", "-ax", "-o", "pid,command"], stderr=subprocess.DEVNULL, timeout=2.0).decode("utf-8")
            for line in out.splitlines():
                if "RobloxStudio" in line and not "grep" in line:
                    parts = line.strip().split(None, 1)
                    if len(parts) >= 2:
                        pid = parts[0]
                        studios.append({
                            "studio_id": f"studio-{pid}",
                            "pid": int(pid),
                            "name": "Roblox Studio (macOS)",
                            "command": parts[1][:120]
                        })
        elif sys.platform == "win32":
            out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq RobloxStudioBeta.exe"], stderr=subprocess.DEVNULL, timeout=2.0).decode("utf-8")
            if "RobloxStudioBeta.exe" in out:
                studios.append({
                    "studio_id": "studio-primary",
                    "name": "Roblox Studio (Windows)",
                    "status": "running"
                })
    except Exception:
        pass

    if studios:
        return {
            "status": "success",
            "connected": True,
            "count": len(studios),
            "total_active": len(studios),
            "studios": studios,
            "message": f"Detected {len(studios)} active Roblox Studio instance(s).",
            "summary": f"Detected {len(studios)} active Roblox Studio instance(s)."
        }
    return {
        "status": "offline",
        "connected": False,
        "count": 0,
        "total_active": 0,
        "studios": [],
        "message": "No running Roblox Studio instances detected on this machine.",
        "summary": "No running Roblox Studio instances detected on this machine."
    }



def get_generic_tools(server_id: str, name: str) -> List[Dict[str, Any]]:
    clean_id = server_id.strip().lower().replace(" ", "_")
    return [
        {
            "name": f"mcp_{clean_id}_execute",
            "description": f"Executes an action or RPC query on connected MCP server '{name}'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action or command name."},
                    "payload": {"type": "object", "description": "JSON arguments payload."}
                },
                "required": ["action"]
            }
        }
    ]


def register_configured_server(server_id: str, s_cfg: Dict[str, Any]):
    """Registers a single server entry from standard mcpServers configuration."""
    clean_id = server_id.strip()
    key_lower = clean_id.lower()

    command = s_cfg.get("command")
    args = s_cfg.get("args", [])
    env = s_cfg.get("env", {})
    url = s_cfg.get("url") or s_cfg.get("endpoint")
    desc = s_cfg.get("description", f"MCP Server '{clean_id}'")

    # Select tools based on server identity and command
    if "roblox" in key_lower or "studio" in key_lower or (command and "studiomcp" in str(command).lower()):
        tools = get_roblox_studio_tools()
        server_name = "Roblox Studio MCP"
    elif "github" in key_lower:
        tools = get_github_tools()
        server_name = "GitHub MCP"
    else:
        tools = s_cfg.get("tools") or get_generic_tools(clean_id, clean_id.title())
        server_name = clean_id.replace("_", " ").title()

    # Determine command or URL health
    is_connected = False
    status_label = "standby"
    status_text = "Standby"

    if command:
        cmd_path = os.path.expanduser(str(command))
        cmd_name = os.path.basename(cmd_path)
        if os.path.exists(cmd_path) or shutil.which(cmd_path):
            is_connected = True
            status_label = "ready"
            status_text = f"Command Active ({cmd_name})"
        else:
            is_connected = False
            status_label = "standby"
            status_text = f"Binary not found: {cmd_name}"
    elif url:
        status_text = f"Endpoint configured ({url})"
        status_label = "standby"
    else:
        is_connected = True
        status_label = "ready"
        status_text = "Ready"

    _MCP_REGISTRY[clean_id] = {
        "name": server_name,
        "description": desc,
        "command": command,
        "args": args,
        "env": env,
        "url": url,
        "connected": is_connected,
        "status": status_label,
        "status_text": status_text,
        "tools": tools
    }


def find_roblox_studio_mcp_path() -> Optional[str]:
    """Auto-discovers the native Roblox Studio MCP proxy binary on macOS and Windows."""
    candidates = [
        os.path.expanduser("~/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP"),
        "/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP",
        os.path.expanduser("~/AppData/Local/Roblox/StudioMCP.exe"),
        shutil.which("StudioMCP")
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None


def load_persisted_mcp_config():
    """Loads MCP servers from data/mcp_config.json and auto-discovers native StudioMCP."""
    _MCP_REGISTRY.clear()
    if os.path.exists(MCP_CONFIG_PATH):
        try:
            with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("mcpServers", data if isinstance(data, dict) else {})
            if isinstance(servers, dict) and servers:
                for s_id, s_cfg in servers.items():
                    if isinstance(s_cfg, dict):
                        register_configured_server(s_id, s_cfg)
        except Exception as e:
            print(f"[STROKE MCP] Note loading mcp_config.json: {e}", flush=True)

    # Auto-discover StudioMCP if not configured or points to nonexistent placeholder
    has_valid_studio = False
    for k, s in _MCP_REGISTRY.items():
        if "studio" in k.lower():
            cmd = s.get("command")
            if cmd and os.path.exists(os.path.expanduser(str(cmd))):
                has_valid_studio = True
                break

    if not has_valid_studio:
        studio_bin = find_roblox_studio_mcp_path()
        if studio_bin:
            register_configured_server("Roblox_Studio", {
                "command": studio_bin,
                "description": "Native Roblox Studio Model Context Protocol Bridge"
            })
            try:
                os.makedirs(os.path.dirname(MCP_CONFIG_PATH), exist_ok=True)
                current_cfg = {}
                if os.path.exists(MCP_CONFIG_PATH):
                    try:
                        with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
                            current_cfg = json.load(f).get("mcpServers", {})
                    except Exception:
                        current_cfg = {}
                current_cfg["Roblox_Studio"] = {
                    "command": studio_bin,
                    "description": "Native Roblox Studio Model Context Protocol Bridge"
                }
                with open(MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump({"mcpServers": current_cfg}, f, indent=2)
            except Exception:
                pass


# Initialize on import
load_persisted_mcp_config()


async def check_server_health(url: str, timeout: float = 0.5) -> bool:
    """Probes if an HTTP MCP server endpoint is actively listening."""
    if not url or not url.startswith("http"):
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return resp.status_code < 500
    except Exception:
        return False


def get_all_mcp_servers() -> Dict[str, Any]:
    """Returns static status and tool manifests of configured MCP servers."""
    servers_summary = {}
    for key, s in _MCP_REGISTRY.items():
        servers_summary[key] = {
            "name": s["name"],
            "description": s["description"],
            "command": s.get("command"),
            "url": s.get("url"),
            "connected": s.get("connected", False),
            "status": s.get("status", "standby"),
            "status_text": s.get("status_text", ""),
            "tool_count": len(s.get("tools", [])),
            "tools": s.get("tools", [])
        }
    return servers_summary


async def get_all_mcp_servers_with_health() -> Dict[str, Any]:
    """Returns real-time connection status of all configured MCP servers."""
    servers_summary = {}
    for key, s in _MCP_REGISTRY.items():
        url = s.get("url")
        command = s.get("command")
        is_live = s.get("connected", False)
        status_label = s.get("status", "standby")
        status_text = s.get("status_text", "")

        if command:
            cmd_path = os.path.expanduser(str(command))
            if os.path.exists(cmd_path) or shutil.which(cmd_path):
                is_live = True
                status_label = "ready"
                status_text = f"Command Ready: {os.path.basename(cmd_path)}"
            else:
                is_live = False
                status_label = "standby"
                status_text = f"File not found: {os.path.basename(cmd_path)}"
        elif url:
            if url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
                is_live = await check_server_health(url)
                status_label = "online" if is_live else "standby"
                status_text = "Online" if is_live else f"Standby on {url}"

        servers_summary[key] = {
            "name": s["name"],
            "description": s["description"],
            "command": command,
            "url": url,
            "connected": is_live,
            "status": status_label,
            "status_text": status_text,
            "tool_count": len(s.get("tools", [])),
            "tools": s.get("tools", [])
        }
    return servers_summary



def register_custom_mcp_server(
    server_id: str,
    name: str,
    description: str,
    url: str,
    tools: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Registers or updates an external/custom MCP server connection.
    Enables Stroke to connect to any local or remote MCP server.
    """
    clean_id = server_id.strip().lower().replace(" ", "_")
    if not tools:
        # Default standard execution tool for this server
        tools = [
            {
                "name": f"mcp_{clean_id}_execute",
                "description": f"Executes an action or RPC query on connected MCP server '{name}'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Action or command name."},
                        "payload": {"type": "object", "description": "JSON arguments payload."}
                    },
                    "required": ["action"]
                }
            }
        ]

    _MCP_REGISTRY[clean_id] = {
        "name": name,
        "description": description,
        "url": url,
        "connected": True,
        "is_custom": True,
        "tools": tools
    }
    print(f"[STROKE MCP] Custom MCP server '{name}' registered at {url} with {len(tools)} tools.", flush=True)
    return _MCP_REGISTRY[clean_id]


def remove_custom_mcp_server(server_id: str) -> bool:
    """Disconnects and removes a custom MCP server."""
    clean_id = server_id.strip().lower()
    if clean_id in _MCP_REGISTRY:
        del _MCP_REGISTRY[clean_id]
        print(f"[STROKE MCP] Custom MCP server '{clean_id}' disconnected.", flush=True)
        return True
    return False


MCP_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mcp_config.json")


def get_mcp_config_json() -> Dict[str, Any]:
    """Returns current MCP servers as a standard mcpServers JSON configuration dict."""
    if os.path.exists(MCP_CONFIG_PATH):
        try:
            with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "mcpServers" in data and isinstance(data["mcpServers"], dict):
                return data
        except Exception:
            pass

    servers_dict = {}
    for key, s in _MCP_REGISTRY.items():
        entry = {}
        if s.get("command"):
            entry["command"] = s["command"]
            if s.get("args"):
                entry["args"] = s["args"]
            if s.get("env"):
                entry["env"] = s["env"]
        if s.get("url"):
            entry["url"] = s["url"]
        if s.get("description"):
            entry["description"] = s["description"]
        servers_dict[key] = entry
    return {"mcpServers": servers_dict}


def apply_mcp_config_json(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses a standard Model Context Protocol (MCP) JSON configuration block:
      {
        "mcpServers": {
          "Roblox_Studio": {
            "command": "/path/to/StudioMCP"
          },
          "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "..." }
          }
        }
      }
    """
    servers_section = config.get("mcpServers", config)
    if not isinstance(servers_section, dict):
        raise ValueError("Invalid configuration: 'mcpServers' must be a JSON object mapping server names to server configs.")

    # Clear previous registry and register newly configured servers
    _MCP_REGISTRY.clear()
    connected = []
    for s_name, s_cfg in servers_section.items():
        if isinstance(s_cfg, dict):
            register_configured_server(s_name, s_cfg)
            connected.append(s_name)

    # Persist directly to data/mcp_config.json
    try:
        os.makedirs(os.path.dirname(MCP_CONFIG_PATH), exist_ok=True)
        with open(MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": servers_section}, f, indent=2)
    except Exception as exc:
        print(f"[STROKE MCP] Error persisting config: {exc}", flush=True)

    return {
        "status": "success",
        "message": f"Successfully applied configuration for {len(connected)} MCP servers.",
        "connected_servers": connected,
        "config": get_mcp_config_json()
    }


get_mcp_servers_info = get_all_mcp_servers


def get_all_mcp_ai_tool_schemas() -> List[Dict[str, Any]]:
    """Transforms registered MCP tools into standard function schemas for the AI."""
    ai_tools = []
    has_studio = any("studio" in s.lower() for s in _MCP_REGISTRY.keys())
    if not has_studio:
        for t in get_roblox_studio_tools():
            ai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"]
                }
            })

    has_github = any("github" in s.lower() for s in _MCP_REGISTRY.keys())
    if not has_github:
        for t in get_github_tools():
            ai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"]
                }
            })

    for s in _MCP_REGISTRY.values():
        for t in s.get("tools", []):
            ai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"]
                }
            })
    return ai_tools


def select_active_tools_for_query(prompt: str, history: Optional[List[Dict[str, str]]] = None, max_tools: int = 8) -> List[Dict[str, Any]]:
    """
    Two-Tier Dynamic Tool Selection for Llama 3.2 1B.
    Selects 6 to 8 relevant tool schemas per turn to avoid starving the 1B context window,
    while tools_search allows on-demand discovery of any other tool.
    """
    p_lower = prompt.lower()
    if history:
        for m in history[-2:]:
            p_lower += " " + str(m.get("content", "")).lower()

    selected_names = {"terminal_run", "terminal_read_output", "web_search", "tools_search"}

    is_roblox = any(k in p_lower for k in ["roblox", "studio", "luau", "vfx", "particle", "part", "cframe", "hitbox", "tween", "model", "mesh", "script"])
    is_github = any(k in p_lower for k in ["git", "github", "commit", "pull request", "branch", "repo", "issue", "pr"])
    is_vfx = any(k in p_lower for k in ["vfx", "particle", "lightning", "fire", "spark", "explosion", "aura", "spell"])
    is_file = any(k in p_lower for k in ["file", "directory", "folder", "read", "write", "patch", "search_files"])

    if is_roblox:
        selected_names.update(["execute_luau", "studio_execute_luau", "script_search", "insert_asset", "list_roblox_studios", "inspect_instance"])
    if is_vfx:
        selected_names.update(["search_vfx_database", "generate_material", "insert_asset"])
    if is_github:
        selected_names.update(["github_commit_file", "github_get_file_contents", "github_create_pull_request", "github_list_repos"])
    if is_file:
        selected_names.update(["read_file", "list_directory", "create_file", "edit_file"])

    all_schemas = get_all_mcp_ai_tool_schemas()
    has_tools_search = any(s.get("function", {}).get("name") == "tools_search" for s in all_schemas)
    if not has_tools_search:
        all_schemas.append({
            "type": "function",
            "function": {
                "name": "tools_search",
                "description": "Searches for available tools by query or category and returns their exact schemas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keyword to search tools for."}
                    },
                    "required": ["query"]
                }
            }
        })

    filtered = []
    for s in all_schemas:
        fn_name = s.get("function", {}).get("name", "")
        if fn_name in selected_names:
            filtered.append(s)
            if len(filtered) >= max_tools:
                break

    return filtered if filtered else all_schemas[:max_tools]



async def execute_studio_mcp_command(
    cmd_path: str,
    tool_name: str,
    code: str = "",
    target_parent: str = "workspace"
) -> Dict[str, Any]:
    """Communicates directly with Roblox Studio MCP binary via JSON-RPC stdio protocol."""
    cmd_expanded = os.path.expanduser(str(cmd_path)) if cmd_path else ""
    if not (cmd_expanded and (os.path.exists(cmd_expanded) or shutil.which(cmd_expanded))):
        if not cmd_path:
            discovered = find_roblox_studio_mcp_path()
            if discovered:
                cmd_expanded = discovered
        if not cmd_expanded or not (os.path.exists(cmd_expanded) or shutil.which(cmd_expanded)):
            return {
                "status": "offline",
                "connected": False,
                "source": "roblox_studio_mcp_bridge",
                "message": f"Roblox Studio MCP binary not found. Luau code synthesized for {target_parent} but not executed in Studio.",
                "target": target_parent,
                "lines_executed": 0,
                "code_snippet": code[:400] + ("..." if len(code) > 400 else "")
            }

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd_expanded,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        init_msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "stroke", "version": "1.0"}}})
        notif_msg = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        list_studios_msg = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_roblox_studios", "arguments": {}}})

        handshake_payload = init_msg + "\n" + notif_msg + "\n" + list_studios_msg + "\n"
        proc.stdin.write(handshake_payload.encode("utf-8"))
        await proc.stdin.drain()

        studio_id = ""
        place_name = "Studio"
        for _ in range(5):
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=3.0)
            if not line:
                break
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                if data.get("id") == 2:
                    content_list = data.get("result", {}).get("content", [])
                    if content_list:
                        raw_studios = json.loads(content_list[0].get("text", "{}"))
                        studios = raw_studios.get("studios", [])
                        if studios:
                            studio_id = studios[0].get("id", "")
                            place_name = studios[0].get("name", "Studio")
                    break
            except Exception:
                pass

        if not studio_id:
            return {
                "status": "offline",
                "connected": False,
                "source": "roblox_studio_mcp_bridge",
                "message": "Roblox Studio session is offline: MCP binary is present, but no active Roblox Studio place is open. Open a place in Roblox Studio to execute code live.",
                "target": target_parent,
                "lines_executed": 0,
                "code_snippet": code[:400] + ("..." if len(code) > 400 else "")
            }

        if tool_name in ("studio_execute_luau", "execute_luau"):
            exec_call = json.dumps({
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "execute_luau",
                    "arguments": {
                        "code": code,
                        "datamodel_type": "Edit",
                        "studio_id": studio_id
                    }
                }
            })
            proc.stdin.write((exec_call + "\n").encode("utf-8"))
            await proc.stdin.drain()

            exec_result = None
            for _ in range(10):
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
                if not line:
                    break
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue
                try:
                    data = json.loads(line_str)
                    if data.get("id") == 10:
                        exec_result = data
                        break
                except Exception:
                    pass

            if exec_result:
                is_err = exec_result.get("result", {}).get("isError", False)
                content = exec_result.get("result", {}).get("content", [])
                out_text = content[0].get("text", "") if content else "Execution completed in Roblox Studio."
                return {
                    "status": "error" if is_err else "success",
                    "connected": True,
                    "source": "roblox_studio_mcp_live",
                    "message": out_text,
                    "output": out_text,
                    "place_name": place_name,
                    "studio_id": studio_id,
                    "target": target_parent,
                    "lines_executed": len(code.splitlines()) if not is_err else 0,
                    "code_snippet": code[:400] + ("..." if len(code) > 400 else "")
                }
    except Exception as exc:
        print(f"[STROKE STUDIO MCP EXECUTION ERROR] {exc}", flush=True)
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass

    return {
        "status": "offline",
        "connected": False,
        "source": "roblox_studio_mcp_bridge",
        "message": f"Roblox Studio session not connected. Luau code synthesized for {target_parent} but not executed in Studio.",
        "target": target_parent,
        "lines_executed": 0,
        "code_snippet": code[:400] + ("..." if len(code) > 400 else "")
    }


async def execute_mcp_tool(tool_name: str, args: Dict[str, Any], user_github_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes a tool on the designated MCP server and returns the result.
    """
    print(f"[STROKE MCP] Dispatching tool '{tool_name}' with args: {list(args.keys())}", flush=True)

    # --------------------------------------------------------------------------
    # ROBLOX STUDIO MCP TOOLS
    # --------------------------------------------------------------------------
    if tool_name in ("studio_execute_luau", "execute_luau"):
        code = args.get("code", "")
        target = args.get("target_parent", "workspace")

        # Dynamically locate Roblox Studio MCP server from registry
        studio_srv = next((s for k, s in _MCP_REGISTRY.items() if "roblox" in k.lower() or "studio" in k.lower() or "studiomcp" in str(s.get("command", "")).lower()), None)
        cmd = studio_srv.get("command") if studio_srv else None
        url = studio_srv.get("url") if studio_srv else None

        if cmd:
            return await execute_studio_mcp_command(str(cmd), "execute_luau", code, target)

        if url:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    res = await client.post(f"{url}/execute", json={"code": code, "target": target})
                    if res.status_code == 200:
                        return {
                            "status": "success",
                            "connected": True,
                            "source": "roblox_studio_mcp_live",
                            "output": res.json().get("result", "Execution succeeded in active Roblox Studio session."),
                            "target": target,
                            "lines_executed": len(code.splitlines())
                        }
            except Exception:
                pass

        return {
            "status": "offline",
            "connected": False,
            "source": "roblox_studio_mcp_bridge",
            "message": f"Roblox Studio session is offline: not connected. Luau code synthesized for {target} but not executed in Studio.",
            "target": target,
            "lines_executed": 0,
            "code_snippet": code[:400] + ("..." if len(code) > 400 else "")
        }

    elif tool_name == "studio_search_scripts":
        q = args.get("query", "")
        studio_srv = next((s for k, s in _MCP_REGISTRY.items() if "roblox" in k.lower() or "studio" in k.lower() or "studiomcp" in str(s.get("command", "")).lower()), None)
        url = studio_srv.get("url") if studio_srv else None
        if url:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.post(f"{url}/search_scripts", json={"query": q})
                    if res.status_code == 200:
                        return {
                            "status": "success",
                            "connected": True,
                            "source": "roblox_studio_mcp_live",
                            "query": q,
                            "matches": res.json().get("matches", [])
                        }
            except Exception:
                pass

        return {
            "status": "offline",
            "connected": False,
            "source": "roblox_studio_mcp",
            "query": q,
            "matches": [],
            "message": "Roblox Studio MCP bridge is offline. Connect Studio plugin or MCP companion to search live scripts."
        }

    elif tool_name == "studio_insert_vfx_asset":
        asset_id = args.get("asset_id", "")
        folder = args.get("target_folder", "ReplicatedStorage.VFX")
        studio_srv = next((s for k, s in _MCP_REGISTRY.items() if "roblox" in k.lower() or "studio" in k.lower() or "studiomcp" in str(s.get("command", "")).lower()), None)
        url = studio_srv.get("url") if studio_srv else None
        if url:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.post(f"{url}/insert_asset", json={"asset_id": asset_id, "target_folder": folder})
                    if res.status_code == 200:
                        return {
                            "status": "success",
                            "connected": True,
                            "source": "roblox_studio_mcp_live",
                            "asset_id": asset_id,
                            "target_folder": folder,
                            "message": f"Asset {asset_id} instantiated into {folder}."
                        }
            except Exception:
                pass

        return {
            "status": "offline",
            "connected": False,
            "source": "roblox_studio_mcp",
            "asset_id": asset_id,
            "target_folder": folder,
            "message": f"Roblox Studio session is offline: unable to instantiate asset {asset_id} into {folder}."
        }

    elif tool_name == "studio_get_console":
        max_lines = args.get("max_lines", 30)
        studio_srv = next((s for k, s in _MCP_REGISTRY.items() if "roblox" in k.lower() or "studio" in k.lower() or "studiomcp" in str(s.get("command", "")).lower()), None)
        url = studio_srv.get("url") if studio_srv else None
        if url:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.post(f"{url}/get_console", json={"max_lines": max_lines})
                    if res.status_code == 200:
                        return {
                            "status": "success",
                            "connected": True,
                            "source": "roblox_studio_mcp_live",
                            "lines": res.json().get("lines", [])
                        }
            except Exception:
                pass

        return {
            "status": "offline",
            "connected": False,
            "source": "roblox_studio_mcp",
            "lines": [],
            "message": "Roblox Studio session is offline: cannot fetch live Studio output logs."
        }

    # --------------------------------------------------------------------------
    # MULTI-STUDIO & ROBLOX STUDIO TOOLS
    # --------------------------------------------------------------------------
    elif tool_name == "list_roblox_studios":
        return list_roblox_studios_sync()

    elif tool_name in [t["name"] for t in get_roblox_studio_tools()]:
        studio_srv = next((s for k, s in _MCP_REGISTRY.items() if "roblox" in k.lower() or "studio" in k.lower() or "studiomcp" in str(s.get("command", "")).lower()), None)
        url = studio_srv.get("url") if studio_srv else None
        if url:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.post(f"{url}/{tool_name}", json=args)
                    if res.status_code == 200:
                        return {"status": "success", "connected": True, "source": "roblox_studio_mcp_live", "result": res.json()}
            except Exception:
                pass
        return {
            "status": "offline",
            "connected": False,
            "source": "roblox_studio_mcp",
            "tool": tool_name,
            "message": f"Roblox Studio session is offline: unable to execute '{tool_name}'."
        }

    # --------------------------------------------------------------------------
    # GITHUB MCP TOOLS (Integrated with github_service.py)
    # --------------------------------------------------------------------------
    elif tool_name.startswith("github_"):
        import github_service
        token = user_github_token or github_service.get_stored_github_token()

        if tool_name == "github_commit_file":
            repo = args.get("repo") or args.get("repository") or "AyanshShrivastava/stroke"
            path = args.get("path") or args.get("file_path") or args.get("filepath") or ""
            content = args.get("content") or args.get("code") or ""
            msg = args.get("commit_message") or args.get("message") or args.get("msg") or "update via Stroke AI"
            branch = args.get("branch")

            if not args.get("confirmed", False):
                return {
                    "status": "requires_confirmation",
                    "tool": "github_commit_file",
                    "repo": repo,
                    "path": path,
                    "commit_message": msg,
                    "message": f"Confirmation Required: External GitHub write requested to repository '{repo}' for path '{path}'. Please confirm execution before proceeding.",
                    "requires_confirmation": True
                }

            if not token:
                return {
                    "status": "error",
                    "source": "github_mcp",
                    "repo": repo,
                    "path": path,
                    "message": "GITHUB_TOKEN is not configured. Please supply a valid GitHub Personal Access Token in environment or profile."
                }

            return await github_service.commit_file(repo, path, content, msg, branch=branch, confirmed=True)

        elif tool_name == "github_create_pull_request":
            repo = args.get("repo") or args.get("repository") or "AyanshShrivastava/stroke"
            title = args.get("title", "")
            head = args.get("head", "")
            base = args.get("base", "main")
            body = args.get("body", "")

            if not args.get("confirmed", False):
                return {
                    "status": "requires_confirmation",
                    "tool": "github_create_pull_request",
                    "repo": repo,
                    "title": title,
                    "head": head,
                    "base": base,
                    "message": f"Confirmation Required: Open Pull Request '{title}' ({head} -> {base}) in repository '{repo}'?",
                    "requires_confirmation": True
                }

            if not token:
                return {
                    "status": "error",
                    "source": "github_mcp",
                    "repo": repo,
                    "message": "GITHUB_TOKEN is not configured. Provide token to create PR via API."
                }

            return await github_service.create_pull_request(repo, title, head, base=base, body=body, confirmed=True)

        elif tool_name == "github_list_repos":
            return await github_service.list_repositories(
                visibility=args.get("visibility", "all"),
                per_page=int(args.get("per_page", 30))
            )

        elif tool_name == "github_get_file_contents":
            repo = args.get("repo") or args.get("repository") or "AyanshShrivastava/stroke"
            path = args.get("path") or args.get("file_path") or ""
            return await github_service.get_file_contents(repo, path, ref=args.get("ref"))

        elif tool_name == "github_list_branches":
            repo = args.get("repo") or args.get("repository") or "AyanshShrivastava/stroke"
            return await github_service.list_branches(repo)

        elif tool_name == "github_create_branch":
            repo = args.get("repo") or args.get("repository") or "AyanshShrivastava/stroke"
            new_b = args.get("new_branch", "")
            from_b = args.get("from_branch", "main")
            return await github_service.create_branch(repo, new_b, from_branch=from_b, confirmed=args.get("confirmed", False))

        elif tool_name == "github_list_issues":
            repo = args.get("repo") or args.get("repository") or "AyanshShrivastava/stroke"
            return await github_service.list_issues(repo, state=args.get("state", "open"))

        elif tool_name == "github_create_issue":
            repo = args.get("repo") or args.get("repository") or "AyanshShrivastava/stroke"
            title = args.get("title", "")
            body = args.get("body", "")
            return await github_service.create_issue(repo, title, body=body, confirmed=args.get("confirmed", False))

        elif tool_name == "github_list_pull_requests":
            repo = args.get("repo") or args.get("repository") or "AyanshShrivastava/stroke"
            return await github_service.list_pull_requests(repo, state=args.get("state", "open"))

    # --------------------------------------------------------------------------
    # DYNAMIC TOOL DISCOVERY TOOL
    # --------------------------------------------------------------------------
    elif tool_name == "tools_search":
        return tools_search(args.get("query", ""), category=args.get("category"))

    # --------------------------------------------------------------------------
    # CUSTOM MCP SERVERS DISPATCH (Via McpClient & McpServerRegistry)
    # --------------------------------------------------------------------------
    try:
        from mcp_client import global_mcp_registry
        if "__" in tool_name or tool_name in [t["name"] for t in global_mcp_registry.list_all_tools()]:
            res = await global_mcp_registry.dispatch_tool(tool_name, args)
            return res
    except Exception:
        pass

    for s_id, server in _MCP_REGISTRY.items():
        if any(t["name"] == tool_name for t in server.get("tools", [])):
            url = server.get("url")
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(f"{url}/execute", json={"tool": tool_name, "arguments": args})
                    if resp.status_code == 200:
                        return {"status": "success", "source": f"mcp_{s_id}", "result": resp.json()}
                    else:
                        return {
                            "status": "error",
                            "source": f"mcp_{s_id}",
                            "server": server.get("name"),
                            "status_code": resp.status_code,
                            "message": f"Custom MCP server '{server.get('name')}' returned HTTP {resp.status_code}."
                        }
            except Exception as exc:
                return {
                    "status": "error",
                    "source": f"mcp_{s_id}",
                    "server": server.get("name"),
                    "tool_executed": tool_name,
                    "message": f"Failed to connect to custom MCP server at '{url}': {str(exc)}",
                    "args_received": args
                }

    return {"status": "unknown_tool", "tool_name": tool_name}
