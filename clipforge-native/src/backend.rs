use rand::Rng;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::io::AsRawHandle;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

pub struct BackendHandle {
    pub base_url: String,
    pub ws_url: String,
    pub token: String,
    pub repo_root: PathBuf,
    child: Option<Child>,
    #[cfg(windows)]
    job_handle: isize,
}

impl BackendHandle {
    /// Launch a private, headless ClipForge backend bound to loopback with a pre-shared cryptographic token.
    pub fn spawn_or_connect() -> Result<Self, String> {
        // Optional external attach mode via CLIPFORGE_CONNECT_URL + CLIPFORGE_CONNECT_TOKEN
        if let (Ok(url), Ok(tok)) = (
            std::env::var("CLIPFORGE_CONNECT_URL"),
            std::env::var("CLIPFORGE_CONNECT_TOKEN"),
        ) {
            let clean = url.trim().trim_end_matches('/').to_string();
            let ws = clean
                .replacen("http://", "ws://", 1)
                .replacen("https://", "wss://", 1)
                + "/ws";
            return Ok(Self {
                base_url: clean,
                ws_url: ws,
                token: tok.trim().to_string(),
                repo_root: resolve_repo_root(),
                child: None,
                #[cfg(windows)]
                job_handle: 0,
            });
        }

        let repo_root = resolve_repo_root();
        let port = pick_free_loopback_port()?;
        let token = generate_session_token();
        let (mut cmd, label) = build_backend_command(&repo_root, port, &token)?;

        cmd.stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        #[cfg(windows)]
        {
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("Failed to spawn ClipForge backend ({label}): {e}"))?;

        #[cfg(windows)]
        let job_handle = attach_kill_on_close_job(&child);

        let base_url = format!("http://127.0.0.1:{port}");
        let ws_url = format!("ws://127.0.0.1:{port}/ws");

        // Wait up to 25s for FastAPI /api/health to respond
        let client = reqwest::blocking::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(2))
            .build()
            .map_err(|e| e.to_string())?;
        let deadline = Instant::now() + Duration::from_secs(25);
        let mut healthy = false;
        while Instant::now() < deadline {
            if let Ok(Some(exit)) = child.try_wait() {
                return Err(format!(
                    "ClipForge backend ({label}) exited early with status {exit}."
                ));
            }
            if let Ok(resp) = client.get(format!("{base_url}/api/health")).send() {
                if resp.status().is_success() {
                    healthy = true;
                    break;
                }
            }
            std::thread::sleep(Duration::from_millis(160));
        }

        if !healthy {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!(
                "ClipForge backend ({label}) did not become healthy on {base_url} within 25s."
            ));
        }

        Ok(Self {
            base_url,
            ws_url,
            token,
            repo_root,
            child: Some(child),
            #[cfg(windows)]
            job_handle,
        })
    }
}

impl Drop for BackendHandle {
    fn drop(&mut self) {
        if let Some(ref mut child) = self.child {
            let _ = child.kill();
            let _ = child.wait();
        }
        #[cfg(windows)]
        if self.job_handle != 0 {
            unsafe {
                windows_sys::Win32::Foundation::CloseHandle(self.job_handle as _);
            }
        }
    }
}

fn pick_free_loopback_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| format!("Failed to allocate ephemeral loopback port: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("Failed to read bound port: {e}"))?
        .port();
    Ok(port)
}

fn generate_session_token() -> String {
    const HEX: &[u8] = b"0123456789abcdef";
    let mut rng = rand::thread_rng();
    let mut out = String::with_capacity(48);
    for _ in 0..48 {
        out.push(HEX[rng.gen_range(0..16)] as char);
    }
    out
}

pub fn resolve_repo_root() -> PathBuf {
    let mut seeds: Vec<PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            seeds.push(dir.to_path_buf());
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        seeds.push(cwd);
    }
    for seed in &seeds {
        let mut cur = seed.clone();
        for _ in 0..5 {
            if cur.join("pyproject.toml").exists() && cur.join("clipforge").is_dir() {
                return cur;
            }
            if let Some(p) = cur.parent() {
                cur = p.to_path_buf();
            } else {
                break;
            }
        }
    }
    seeds.into_iter().next().unwrap_or_else(|| PathBuf::from("."))
}

fn build_backend_command(repo_root: &Path, port: u16, token: &str) -> Result<(Command, String), String> {
    let port_str = port.to_string();

    // 1. Prefer repo .venv Python (fastest startup, zero PyInstaller unpack delay, always up-to-date)
    #[cfg(windows)]
    let venv_py = repo_root.join(".venv").join("Scripts").join("python.exe");
    #[cfg(not(windows))]
    let venv_py = repo_root.join(".venv").join("bin").join("python");

    let main_py = repo_root.join("main.py");
    if venv_py.exists() && main_py.exists() {
        let mut cmd = Command::new(&venv_py);
        cmd.arg(&main_py)
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(&port_str)
            .arg("--no-browser")
            .current_dir(repo_root)
            .env("CLIPFORGE_SESSION_TOKEN", token)
            .env("PYTHONUTF8", "1");
        return Ok((cmd, venv_py.display().to_string()));
    }

    // 2. Next check standalone compiled backend executable next to us or in dist/ClipForge/
    let mut exe_candidates: Vec<PathBuf> = Vec::new();
    if let Ok(me) = std::env::current_exe() {
        if let Some(dir) = me.parent() {
            #[cfg(windows)]
            {
                exe_candidates.push(dir.join("ClipForgeBackend.exe"));
                exe_candidates.push(dir.join("ClipForge.exe"));
            }
            #[cfg(not(windows))]
            {
                exe_candidates.push(dir.join("ClipForgeBackend"));
                exe_candidates.push(dir.join("ClipForge"));
            }
        }
    }
    #[cfg(windows)]
    exe_candidates.push(repo_root.join("dist").join("ClipForge").join("ClipForge.exe"));
    #[cfg(not(windows))]
    exe_candidates.push(repo_root.join("dist").join("ClipForge").join("ClipForge"));

    let me_canon = std::env::current_exe().ok().and_then(|p| p.canonicalize().ok());
    for cand in exe_candidates {
        if !cand.exists() {
            continue;
        }
        if let (Some(ref me), Ok(cc)) = (&me_canon, cand.canonicalize()) {
            if me == &cc {
                continue;
            }
        }
        let mut cmd = Command::new(&cand);
        cmd.arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(&port_str)
            .arg("--no-browser")
            .current_dir(repo_root)
            .env("CLIPFORGE_SESSION_TOKEN", token);
        return Ok((cmd, cand.display().to_string()));
    }

    // 3. Fallback to system python + main.py
    if main_py.exists() {
        let py_bin = if cfg!(windows) { "python" } else { "python3" };
        let mut cmd = Command::new(py_bin);
        cmd.arg(&main_py)
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(&port_str)
            .arg("--no-browser")
            .current_dir(repo_root)
            .env("CLIPFORGE_SESSION_TOKEN", token)
            .env("PYTHONUTF8", "1");
        return Ok((cmd, format!("{py_bin} main.py")));
    }

    Err(format!(
        "Could not locate ClipForge backend (.venv or dist/ClipForge) under {}",
        repo_root.display()
    ))
}

#[cfg(windows)]
fn attach_kill_on_close_job(child: &Child) -> isize {
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return 0;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok != 0 {
            AssignProcessToJobObject(job, child.as_raw_handle() as _);
        }
        job as isize
    }
}
