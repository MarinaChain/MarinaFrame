#![cfg(target_os = "linux")]

use serde_json::json;
use std::fs;
use std::process::{Command, Output};

fn probe(script: &str, override_config: serde_json::Value) -> Output {
    let root = tempfile::tempdir().unwrap();
    let task = root.path().join("task");
    let work = task.join("work");
    fs::create_dir_all(&work).unwrap();
    fs::write(task.join("input"), "declared").unwrap();
    fs::write(root.path().join("private"), "private").unwrap();
    // Trusted test fixture plants the link before restrictions; models cannot
    // create symlinks for later host artifact consumers to follow.
    std::os::unix::fs::symlink(root.path().join("private"), work.join("link")).unwrap();
    // System Python has a fixed runtime; end-to-end Python tests exercise the
    // configured CAD interpreter and its discovered runtime paths separately.
    let python = "/usr/bin/python3";
    let executable = fs::canonicalize(python).unwrap();
    let mut config = json!({"task": task, "work": work, "executable": executable,
        "runtime_paths": ["/usr/lib", "/lib", "/usr/local/lib", "/etc/ld.so.cache", "/dev/null", "/dev/urandom"],
        "limits": {"cpu_seconds": 1, "memory_bytes": 268435456, "file_bytes": 1048576, "open_files": 32},
        "parent_pid": std::process::id()});
    for (key, value) in override_config.as_object().unwrap() {
        config[key] = value.clone();
    }
    let path = root.path().join("config.json");
    fs::write(&path, serde_json::to_vec(&config).unwrap()).unwrap();
    Command::new(env!("CARGO_BIN_EXE_marinaframe-sandbox"))
        .args([
            "--config",
            path.to_str().unwrap(),
            "--",
            executable.to_str().unwrap(),
            "-I",
            "-c",
            script,
        ])
        .env("PROBE_OUTSIDE", root.path().join("private"))
        .env("HOME", &work) // production overwrites HOME; account-home guard must still work
        .output()
        .unwrap()
}

fn success(script: &str) {
    let output = probe(script, json!({}));
    assert!(
        output.status.success(),
        "status {:?}, stdout {}, stderr {}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("REACHED"));
}

#[test]
fn permitted_reads_and_work_writes() {
    success("from pathlib import Path; print('REACHED', flush=True); assert Path('../input').read_text() == 'declared'; Path('result').write_text('ok')");
}

#[test]
fn outside_and_input_writes_and_symlink_escape_are_denied() {
    success("import os\nfrom pathlib import Path\nprint('REACHED', flush=True)\nfor p in [Path(os.environ['PROBE_OUTSIDE']), Path('../input')]:\n try: p.write_text('bad')\n except PermissionError: pass\n else: raise AssertionError('write escaped')\ntry: os.symlink(os.environ['PROBE_OUTSIDE'], 'new-link')\nexcept PermissionError: pass\nelse: raise AssertionError('model symlink allowed')\ntry: Path('link').write_text('bad')\nexcept PermissionError: pass\nelse: raise AssertionError('symlink escaped')");
}

#[test]
fn private_file_read_is_denied() {
    success("import os; print('REACHED', flush=True)\ntry: open(os.environ['PROBE_OUTSIDE']).read()\nexcept PermissionError: pass\nelse: raise AssertionError('read escaped')");
}

#[test]
fn network_and_process_escape_are_denied() {
    success("import os, socket\nprint('REACHED', flush=True)\nfor operation in [lambda: socket.socket(), os.fork, os.setsid, lambda: os.setpgid(0,0), lambda: os.execv('/usr/bin/true', ['true'])]:\n try: operation()\n except PermissionError: pass\n else: raise AssertionError('operation escaped')");
}

#[test]
fn memory_and_file_limits_are_enforced() {
    success("print('REACHED', flush=True)\ntry: value = bytearray(512*1024*1024)\nexcept MemoryError: pass\nelse: raise AssertionError('memory unlimited')\nimport signal\nsignal.signal(signal.SIGXFSZ, signal.SIG_IGN)\ntry:\n with open('large','wb') as f: f.write(b'x'*(2*1024*1024))\nexcept OSError: pass\nelse: raise AssertionError('file unlimited')");
}

#[test]
fn cpu_limit_is_enforced() {
    use std::os::unix::process::ExitStatusExt;
    let output = probe("print('REACHED', flush=True)\nwhile True: pass", json!({}));
    assert!(String::from_utf8_lossy(&output.stdout).contains("REACHED"));
    assert!(matches!(
        output.status.signal(),
        Some(libc::SIGXCPU | libc::SIGKILL)
    ));
}

#[test]
fn unsupported_and_broad_configurations_fail_before_payload() {
    for config in [
        json!({"minimum_landlock_abi": 999}),
        json!({"runtime_paths": ["/"]}),
        json!({"runtime_paths": [std::env::var_os("HOME").unwrap()]}),
        json!({"task": "/opt", "work": "/opt/work"}),
    ] {
        let output = probe("print('PAYLOAD')", config);
        assert_eq!(output.status.code(), Some(125));
        assert!(!String::from_utf8_lossy(&output.stdout).contains("PAYLOAD"));
        assert!(String::from_utf8_lossy(&output.stderr).contains("sandbox setup failed"));
    }
}

#[test]
fn inherited_host_descriptor_is_closed() {
    use std::os::fd::AsRawFd;
    use std::os::unix::process::CommandExt;
    let root = tempfile::tempdir().unwrap();
    let file = fs::File::open("/etc/passwd").unwrap();
    let fd = file.as_raw_fd();
    // A separate probe confirms the launcher's descriptor sweep, independent of
    // Python's supervisor (which also sets close_fds).
    let task = root.path().join("task");
    fs::create_dir_all(task.join("work")).unwrap();
    let config = json!({"task": task, "work": task.join("work"), "executable": "/usr/bin/python3",
        "runtime_paths": ["/usr/lib", "/lib", "/dev/null"], "parent_pid": std::process::id(),
        "limits": {"cpu_seconds": 1, "memory_bytes": 268435456, "file_bytes": 1048576, "open_files": 32}});
    let path = root.path().join("config.json");
    fs::write(&path, serde_json::to_vec(&config).unwrap()).unwrap();
    let script = format!("import os\nprint('REACHED', flush=True)\ntry: os.fstat({fd})\nexcept OSError: pass\nelse: raise AssertionError('descriptor leaked')");
    let mut command = Command::new(env!("CARGO_BIN_EXE_marinaframe-sandbox"));
    command.args([
        "--config",
        path.to_str().unwrap(),
        "--",
        "/usr/bin/python3",
        "-I",
        "-c",
        &script,
    ]);
    unsafe {
        command.pre_exec(move || {
            if libc::fcntl(fd, libc::F_SETFD, 0) < 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let output = command.output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn direct_bind_and_connect_syscalls_are_denied() {
    // No socket is needed: seccomp must return EPERM before fd validation.
    success("import ctypes, errno, os\nlibc=ctypes.CDLL(None, use_errno=True)\nprint('REACHED', flush=True)\nfor op in [libc.bind, libc.connect]:\n assert op(-1, None, 0) == -1\n assert ctypes.get_errno() == errno.EPERM");
}

#[test]
fn cross_process_resource_and_scheduler_syscalls_are_denied() {
    for number in [libc::SYS_prlimit64, libc::SYS_sched_setattr] {
        // Invalid arguments cannot mutate any process. EPERM must come from
        // seccomp before the kernel checks those arguments.
        success(&format!("import ctypes,errno\nlibc=ctypes.CDLL(None,use_errno=True)\nprint('REACHED',flush=True)\nassert libc.syscall(ctypes.c_long({number}), -1, None, 0, 0) == -1\nassert ctypes.get_errno() == errno.EPERM"));
    }
}

#[test]
fn asynchronous_signal_ownership_is_denied() {
    // Use this sandbox's own PID, never a controller/runner PID. Even if the
    // guard regresses, the probe cannot signal the host test runner.
    success("import os,fcntl,signal,ctypes,errno\nprint('REACHED',flush=True)\nr,w=os.pipe()\nlibc=ctypes.CDLL(None,use_errno=True)\nfor cmd,arg in [(fcntl.F_SETOWN,os.getpid()),(fcntl.F_SETOWN,-os.getpid()),(10,signal.SIGKILL),(15,0)]:\n try: fcntl.fcntl(r,cmd,arg)\n except OSError as e: assert e.errno==errno.EPERM\n else: raise AssertionError('async signal command allowed')\nfor request in [0x8901,0x8902]:\n target=ctypes.c_int(os.getpid())\n assert libc.ioctl(r,ctypes.c_ulong(request),ctypes.byref(target))==-1\n assert ctypes.get_errno()==errno.EPERM\nfcntl.fcntl(r,fcntl.F_SETFL,os.O_ASYNC|os.O_NONBLOCK)\nos.write(w,b'x')\nassert os.read(r,1)==b'x'");
}

#[test]
fn host_ipc_and_cross_process_calls_are_denied() {
    for number in [
        libc::SYS_shmget,
        libc::SYS_shmat,
        libc::SYS_shmctl,
        libc::SYS_shmdt,
        libc::SYS_msgget,
        libc::SYS_msgsnd,
        libc::SYS_msgrcv,
        libc::SYS_msgctl,
        libc::SYS_semget,
        libc::SYS_semop,
        libc::SYS_semtimedop,
        libc::SYS_semctl,
        libc::SYS_mq_open,
        libc::SYS_mq_unlink,
        libc::SYS_mq_timedsend,
        libc::SYS_mq_timedreceive,
        libc::SYS_mq_notify,
        libc::SYS_mq_getsetattr,
        libc::SYS_ioprio_set,
        libc::SYS_move_pages,
        libc::SYS_migrate_pages,
        libc::SYS_kcmp,
        libc::SYS_personality,
    ] {
        success(&format!("import ctypes,errno\nlibc=ctypes.CDLL(None,use_errno=True)\nprint('REACHED',flush=True)\nassert libc.syscall(ctypes.c_long({number}),-1,0,0,0,0,0)==-1\nassert ctypes.get_errno()==errno.EPERM"));
    }
}

#[test]
fn syslog_size_query_is_denied_before_kernel_argument_checks() {
    // SIZE_BUFFER (10) is not gated by dmesg_restrict. Invalid action -1
    // checks capability first and can falsely pass without our filter.
    success(&format!("import ctypes,errno\nlibc=ctypes.CDLL(None,use_errno=True)\nprint('REACHED',flush=True)\nassert libc.syscall(ctypes.c_long({}),10,None,0)==-1\nassert ctypes.get_errno()==errno.EPERM", libc::SYS_syslog));
}

#[test]
fn child_can_attest_kernel_controls_but_not_read_host_proc() {
    success("from pathlib import Path\nprint('REACHED',flush=True)\ns=Path('/proc/self/status').read_text()\nf=dict(line.split(':',1) for line in s.splitlines() if ':' in line)\nassert f['Seccomp'].strip()=='2'\nassert f['NoNewPrivs'].strip()=='1'\ntry: Path('/proc/1/status').read_text()\nexcept PermissionError: pass\nelse: raise AssertionError('host proc readable')");
}

#[test]
fn unlisted_harmless_syscall_is_denied_by_default() {
    // getcpu succeeds without special privileges and was permitted by the old
    // deny-list. No host security setting should produce a false-positive EPERM.
    success(&format!("import ctypes,errno\nlibc=ctypes.CDLL(None,use_errno=True)\nprint('REACHED',flush=True)\nassert libc.syscall(ctypes.c_long({}),None,None,None)==-1\nassert ctypes.get_errno()==errno.EPERM", libc::SYS_getcpu));
}

#[test]
fn descriptor_limit_is_enforced() {
    success("import errno\nprint('REACHED', flush=True)\nfiles=[]\ntry:\n for i in range(64): files.append(open('file-'+str(i), 'w'))\nexcept OSError as e: assert e.errno == errno.EMFILE\nelse: raise AssertionError('descriptors unlimited')");
}

#[test]
fn home_read_is_denied() {
    let home = std::env::var_os("HOME").expect("Linux CI needs a home directory");
    let private = tempfile::NamedTempFile::new_in(home).unwrap();
    let script = format!("print('REACHED', flush=True)\ntry: open({:?}).read()\nexcept PermissionError: pass\nelse: raise AssertionError('home readable')", private.path().to_str().unwrap());
    success(&script);
}
