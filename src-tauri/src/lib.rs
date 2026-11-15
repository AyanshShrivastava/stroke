// ==============================================================================
// ARCHITECTURE CONSOLIDATION NOTICE:
// Per docs/ARCHITECTURE.md Section 2.3 & 2.4:
// PyWebView via desktop.py is the single authoritative desktop host.
// The authoritative terminal execution engine is terminal_service.py in Python.
// Tauri and this Rust terminal module are RETIRED and NON-PRODUCTION.
// The Rust terminal has been removed from active release, build, and invoke paths.
// ==============================================================================

pub mod terminal;

use std::sync::Arc;
use tauri::State;
use terminal::TerminalManager;

pub struct AppState {
    pub terminal_manager: Arc<TerminalManager>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let current_dir = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    let terminal_manager = Arc::new(TerminalManager::new(current_dir));

    tauri::Builder::default()
        .manage(AppState { terminal_manager })
        // Active invoke handler: Rust terminal removed from invoke path as non-production
        .invoke_handler(tauri::generate_handler![])
        .run(tauri::generate_context!())
        .expect("error while running stroke tauri desktop application");
}
