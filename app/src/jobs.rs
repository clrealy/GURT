//! running gurt: one job = one gurt command, its output streamed line by line.
//! sudo asks for your password through us: SUDO_ASKPASS is a tiny script that runs `gurt-app --askpass`, which talks to
//! this app over a private unix socket (0600, in a 0700 folder) and waits until you answer in the window.
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::time::Duration;

#[derive(Default)]
pub struct JobState {
    pub lines: Vec<String>,
    pub done: bool,
    pub rc: i32,
    pub ask: Option<String>,        // sudo's prompt, waiting for you
    pub live: String,               // a progress line that's still updating (downloads redraw it with \r)
    answer: Option<Option<String>>, // Some(Some(pw)) = typed, Some(None) = cancel
    pw: Option<String>,             // the password you typed, remembered until the job ends (sudo runs more than once)
    pw_sudo: i64,                   // …and which sudo it was for
    pid: Option<i32>,
}

pub struct Job {
    #[allow(dead_code)]
    pub id: String,
    pub title: String,
    pub st: Mutex<JobState>,
    cv: Condvar,
}

impl Job {
    pub fn snapshot_from(&self, from: usize) -> (Vec<String>, bool, i32, Option<String>) {
        let s = self.st.lock().unwrap();
        (s.lines.get(from..).map(|l| l.to_vec()).unwrap_or_default(), s.done, s.rc, s.ask.clone())
    }
    pub fn lines(&self) -> Vec<String> {
        self.st.lock().unwrap().lines.clone()
    }
    /// what it's doing right now: its newest line (a progress line's newest update, after its last \r)
    pub fn last_line(&self) -> Option<String> {
        let s = self.st.lock().unwrap();
        if !s.live.trim().is_empty() {
            return Some(s.live.trim().to_string());
        }
        s.lines.iter().skip(1).rev().map(|l| l.rsplit('\r').find(|x| !x.trim().is_empty()).unwrap_or("").trim().to_string()).find(|l| !l.is_empty())
    }
    pub fn done(&self) -> bool {
        self.st.lock().unwrap().done
    }
    pub fn ask(&self) -> Option<String> {
        self.st.lock().unwrap().ask.clone()
    }
    /// your answer to sudo's question: Some(password) or None (cancel)
    pub fn answer(&self, pw: Option<String>) {
        let mut s = self.st.lock().unwrap();
        s.answer = Some(pw);
        self.cv.notify_all();
    }
    /// stop it (the whole process group: gurt and whatever it started)
    pub fn cancel(&self) {
        let mut s = self.st.lock().unwrap();
        if s.ask.is_some() {
            s.answer = Some(None);
            self.cv.notify_all();
            return;
        }
        if let (Some(pid), false) = (s.pid, s.done) {
            unsafe { libc::killpg(pid, libc::SIGTERM) };
        }
    }
}

static JOBS: OnceLock<Mutex<HashMap<String, Arc<Job>>>> = OnceLock::new();
static ASKPASS: OnceLock<(PathBuf, PathBuf)> = OnceLock::new(); // (askpass script, socket)
static NEXT: AtomicU64 = AtomicU64::new(1);
pub static REPAINT: OnceLock<Box<dyn Fn() + Send + Sync>> = OnceLock::new();

fn jobs() -> &'static Mutex<HashMap<String, Arc<Job>>> {
    JOBS.get_or_init(|| Mutex::new(HashMap::new()))
}
fn repaint() {
    if let Some(r) = REPAINT.get() {
        r();
    }
}

/// start gurt with these args (and maybe something on its stdin)
pub fn start(args: Vec<String>, stdin: Option<String>) -> Arc<Job> {
    let id = format!("{:x}{:x}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed));
    let title = format!("gurt {}", args.iter().filter(|a| *a != "-y").cloned().collect::<Vec<_>>().join(" "));
    let job = Arc::new(Job { id: id.clone(), title: title.clone(), st: Mutex::new(JobState::default()), cv: Condvar::new() });
    jobs().lock().unwrap().insert(id.clone(), job.clone());
    job.st.lock().unwrap().lines.push(format!("$ {title}"));
    let j = job.clone();
    std::thread::spawn(move || {
        let mut cmd = Command::new(crate::data::gurt());
        cmd.args(&args)
            .env("GURT_GUI", "1")
            .env("NO_COLOR", "1")
            .env("GURT_APP_JOB", &id)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .stdin(if stdin.is_some() { Stdio::piped() } else { Stdio::null() })
            ; // setsid below: its own session + process group, no controlling tty → sudo uses askpass
        if let Some((script, sock)) = ASKPASS.get() {
            cmd.env("SUDO_ASKPASS", script).env("GURT_APP_SOCK", sock);
        }
        unsafe {
            cmd.pre_exec(|| {
                libc::setsid();
                Ok(())
            });
        }
        match cmd.spawn() {
            Ok(mut child) => {
                j.st.lock().unwrap().pid = Some(child.id() as i32);
                if let (Some(text), Some(mut w)) = (stdin, child.stdin.take()) {
                    let _ = w.write_all(text.as_bytes());
                }
                pump(&j, &mut child);
                let rc = child.wait().ok().and_then(|s| s.code()).unwrap_or(1);
                let mut s = j.st.lock().unwrap();
                s.rc = rc;
                s.done = true;
                s.pw = None; // forget the password the moment the job's over
            }
            Err(e) => {
                let mut s = j.st.lock().unwrap();
                s.lines.push(format!("==> nah: couldn't start gurt ({e})"));
                s.rc = 127;
                s.done = true;
            }
        }
        repaint();
    });
    job
}

/// stdout + stderr, merged, a line at a time
fn pump(j: &Arc<Job>, child: &mut Child) {
    let out = child.stdout.take();
    let err = child.stderr.take();
    let j2 = j.clone();
    let t = std::thread::spawn(move || {
        if let Some(e) = err {
            read_lines(e, &j2);
        }
    });
    if let Some(o) = out {
        read_lines(o, j);
    }
    let _ = t.join();
}
/// a line ends at \n. a progress bar redraws itself with \r: its newest look is `live` until the line ends
fn read_lines(mut r: impl Read, j: &Arc<Job>) {
    let (mut cur, mut last_cr, mut chunk) = (Vec::new(), Vec::new(), [0u8; 4096]);
    loop {
        let n = match r.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(n) => n,
        };
        for &b in &chunk[..n] {
            match b {
                b'\n' => {
                    let line = if cur.is_empty() { std::mem::take(&mut last_cr) } else { std::mem::take(&mut cur) };
                    let mut s = j.st.lock().unwrap();
                    s.lines.push(crate::data::strip_ansi(&String::from_utf8_lossy(&line)));
                    s.live.clear();
                    last_cr.clear();
                }
                b'\r' => {
                    if !cur.is_empty() {
                        j.st.lock().unwrap().live = crate::data::strip_ansi(&String::from_utf8_lossy(&cur));
                        last_cr = std::mem::take(&mut cur);
                    }
                }
                _ => cur.push(b),
            }
        }
        repaint();
    }
    if !cur.is_empty() {
        j.st.lock().unwrap().lines.push(crate::data::strip_ansi(&String::from_utf8_lossy(&cur)));
    }
    j.st.lock().unwrap().live.clear();
}

// ── 🔑 the password bridge ──
pub fn setup_askpass() {
    let base = std::env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from).filter(|p| p.is_dir()).unwrap_or_else(std::env::temp_dir);
    let dir = base.join(format!("gurt-app-{}", std::process::id()));
    let _ = std::fs::create_dir_all(&dir);
    let _ = std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700));
    let sock = dir.join("askpass.sock");
    let _ = std::fs::remove_file(&sock);
    let Ok(listener) = UnixListener::bind(&sock) else { return };
    let _ = std::fs::set_permissions(&sock, std::fs::Permissions::from_mode(0o600));
    let me = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("gurt-app"));
    let script = dir.join("askpass");
    let q = |p: &std::path::Path| format!("'{}'", p.display().to_string().replace('\'', "'\\''"));
    let _ = std::fs::write(&script, format!("#!/bin/sh\nexec {} --askpass \"$@\"\n", q(&me)));
    let _ = std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o700));
    let _ = ASKPASS.set((script, sock));
    std::thread::spawn(move || {
        for s in listener.incoming().flatten() {
            std::thread::spawn(move || serve_ask(s));
        }
    });
}
pub fn cleanup_askpass() {
    if let Some((script, _)) = ASKPASS.get() {
        if let Some(d) = script.parent() {
            let _ = std::fs::remove_dir_all(d);
        }
    }
}

/// one sudo asking: "job \t sudo's pid \t prompt\n" → "ok \t password\n" or "cancel\n"
fn serve_ask(mut s: UnixStream) {
    let mut line = String::new();
    if BufReader::new(&s).read_line(&mut line).is_err() {
        return;
    }
    let mut parts = line.trim_end_matches('\n').splitn(3, '\t');
    let (id, sudo, prompt) = (parts.next().unwrap_or(""), parts.next().unwrap_or("0").parse::<i64>().unwrap_or(0), parts.next().unwrap_or("password").to_string());
    let Some(job) = jobs().lock().unwrap().get(id).cloned() else {
        let _ = s.write_all(b"cancel\n");
        return;
    };
    let mut st = job.st.lock().unwrap();
    if let Some(pw) = st.pw.clone() {
        if sudo != st.pw_sudo {
            st.pw_sudo = sudo; // a new sudo in the same job: hand it the password you already typed
            drop(st);
            let _ = s.write_all(format!("ok\t{pw}\n").as_bytes());
            return;
        }
    }
    st.pw = None; // the same sudo asking again = that password was wrong, so ask you
    st.answer = None;
    st.ask = Some(prompt.trim().to_string());
    drop(st);
    repaint();
    let st = job.st.lock().unwrap();
    let (mut st, _) = job.cv.wait_timeout_while(st, Duration::from_secs(600), |st| st.answer.is_none()).unwrap();
    let ans = st.answer.take().flatten();
    st.ask = None;
    if let Some(pw) = &ans {
        if !st.done {
            st.pw = Some(pw.clone());
            st.pw_sudo = sudo;
        }
    }
    drop(st);
    repaint();
    let _ = match ans {
        Some(pw) => s.write_all(format!("ok\t{pw}\n").as_bytes()),
        None => s.write_all(b"cancel\n"),
    };
}

/// `gurt-app --askpass <prompt>`: what sudo runs. asks the app, prints the password for sudo
pub fn askpass_main(prompt: String) -> i32 {
    let (Ok(sock), Ok(job)) = (std::env::var("GURT_APP_SOCK"), std::env::var("GURT_APP_JOB")) else { return 1 };
    let Ok(mut s) = UnixStream::connect(sock) else { return 1 };
    let ppid = unsafe { libc::getppid() };
    let prompt = if prompt.trim().is_empty() { "password".to_string() } else { prompt.replace(['\t', '\n'], " ") };
    if s.write_all(format!("{job}\t{ppid}\t{prompt}\n").as_bytes()).is_err() {
        return 1;
    }
    let mut ans = String::new();
    let _ = s.read_to_string(&mut ans);
    match ans.trim_end_matches('\n').split_once('\t') {
        Some(("ok", pw)) => {
            println!("{pw}");
            0
        }
        _ => 1,
    }
}
