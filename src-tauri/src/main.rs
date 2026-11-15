#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn AttachConsole(process_id: u32) -> i32;
}

fn run_cli(args: impl Iterator<Item = std::ffi::OsString>) -> std::io::Result<i32> {
    #[cfg(windows)]
    unsafe {
        AttachConsole(u32::MAX);
    }
    let executable = std::env::current_exe()?;
    let sidecar = executable.with_file_name(format!("dayz-backend{}", std::env::consts::EXE_SUFFIX));
    let mut args = args.peekable();
    let mut command = std::process::Command::new(sidecar);
    if args.peek().is_none() {
        command.arg("--help");
    }
    let result = command.args(args).status()?;
    Ok(result.code().unwrap_or(1))
}

fn main() {
    let mut args = std::env::args_os().skip(1);
    if let Some(first) = args.next() {
        let result = if first == "--cli" {
            run_cli(args)
        } else {
            run_cli(std::iter::once(first).chain(args))
        };
        match result {
            Ok(code) => std::process::exit(code),
            Err(error) => {
                eprintln!("Could not start the DayZ command line: {error}");
                std::process::exit(1);
            }
        }
    }
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("Could not start DayZ Mod Studio");
}
