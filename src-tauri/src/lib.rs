pub mod terminal;

use std::sync::Arc;
use tauri::State;
use terminal::{CommandOutputResult, SessionStatus, TerminalManager};

pub struct AppState {
    pub terminal_manager: Arc<TerminalManager>,
}

#[tauri::command]
pub async fn create_terminal(
    state: State<'_, AppState>,
    workspace_path: Option<String>,
) -> Result<serde_json::Value, String> {
    state.terminal_manager.create_terminal(workspace_path)
}

#[tauri::command]
pub async fn run_command(
    state: State<'_, AppState>,
    session_id: String,
    command: String,
    args: Option<Vec<String>>,
    timeout_sec: Option<u64>,
) -> Result<CommandOutputResult, String> {
    state
        .terminal_manager
        .run_command(&session_id, &command, args.unwrap_or_default(), timeout_sec)
        .await
}

#[tauri::command]
pub async fn read_terminal_output(
    state: State<'_, AppState>,
    session_id: String,
    tail_lines: Option<usize>,
) -> Result<serde_json::Value, String> {
    state.terminal_manager.read_output(&session_id, tail_lines)
}

#[tauri::command]
pub async fn get_terminal_status(
    state: State<'_, AppState>,
    session_id: String,
) -> Result<SessionStatus, String> {
    state.terminal_manager.get_status(&session_id)
}

#[tauri::command]
pub async fn list_terminals(state: State<'_, AppState>) -> Result<Vec<SessionStatus>, String> {
    Ok(state.terminal_manager.list_terminals())
}

#[tauri::command]
pub async fn stop_terminal(
    state: State<'_, AppState>,
    session_id: String,
) -> Result<serde_json::Value, String> {
    state.terminal_manager.stop_terminal(&session_id)
}

#[tauri::command]
pub async fn respond_to_approval(
    state: State<'_, AppState>,
    approval_id: String,
    approved: bool,
) -> Result<CommandOutputResult, String> {
    state
        .terminal_manager
        .respond_to_approval(&approval_id, approved)
        .await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let current_dir = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    let terminal_manager = Arc::new(TerminalManager::new(current_dir));

    tauri::Builder::default()
        .manage(AppState { terminal_manager })
        .invoke_handler(tauri::generate_handler![
            create_terminal,
            run_command,
            read_terminal_output,
            get_terminal_status,
            list_terminals,
            stop_terminal,
            respond_to_approval
        ])
        .run(tauri::generate_context!())
        .expect("error while running stroke tauri desktop application");
}
