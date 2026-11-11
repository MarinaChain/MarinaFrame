//! Linux-only kernel boundary. No model code is loaded in this process.
use serde::Deserialize;
use std::collections::BTreeSet;
use std::ffi::CString;
use std::fs::{self, File};
use std::io::{self, Read};
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Command;

const SETUP_LIMIT: u64 = 1024 * 1024;
const MINIMUM_ABI: i32 = 3;
const ACCESS_EXECUTE: u64 = 1;
const ACCESS_WRITE_FILE: u64 = 1 << 1;
const ACCESS_READ_FILE: u64 = 1 << 2;
const ACCESS_READ_DIR: u64 = 1 << 3;
const ACCESS_TRUNCATE: u64 = 1 << 14;
const ACCESS_IOCTL_DEV: u64 = 1 << 15;
const READ: u64 = ACCESS_READ_FILE | ACCESS_READ_DIR;
// No device/socket/FIFO creation. Ordinary file/directory creation, unlink,
// rename and hard links remain limited to the one writable tree.
const WORK: u64 = READ
    | ACCESS_WRITE_FILE
    | (1 << 4)
    | (1 << 5)
    | (1 << 7)
    | (1 << 8)
    | (1 << 13)
    | ACCESS_TRUNCATE;
const LL_CREATE: libc::c_long = 444;
const LL_ADD: libc::c_long = 445;
const LL_RESTRICT: libc::c_long = 446;

#[derive(Deserialize)]
struct Config {
    task: PathBuf,
    work: PathBuf,
    runtime_paths: Vec<PathBuf>,
    executable: PathBuf,
    limits: Limits,
    parent_pid: libc::pid_t,
    #[serde(default = "minimum_abi")]
    minimum_landlock_abi: i32,
}
fn minimum_abi() -> i32 {
    MINIMUM_ABI
}

#[derive(Deserialize)]
struct Limits {
    cpu_seconds: u64,
    memory_bytes: u64,
    file_bytes: u64,
    open_files: u64,
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}
fn checked(result: libc::c_long, operation: &str) -> io::Result<libc::c_long> {
    if result < 0 {
        Err(io::Error::new(
            io::Error::last_os_error().kind(),
            format!("{operation}: {}", io::Error::last_os_error()),
        ))
    } else {
        Ok(result)
    }
}
fn canonical(path: &Path) -> io::Result<PathBuf> {
    if !path.is_absolute() {
        return Err(invalid("sandbox paths must be absolute"));
    }
    fs::canonicalize(path)
}
fn broad(path: &Path) -> bool {
    broad_with_account(path, real_home)
}

fn broad_with_account(path: &Path, account_home: impl FnOnce() -> Option<PathBuf>) -> bool {
    matches!(
        path.to_str(),
        Some(
            "/" | "/home"
                | "/root"
                | "/Users"
                | "/usr"
                | "/usr/local"
                | "/etc"
                | "/var"
                | "/tmp"
                | "/proc"
                | "/sys"
                | "/dev"
        )
    ) || matches!(
        path.to_str(),
        Some("/opt" | "/mnt" | "/srv" | "/run" | "/var/tmp" | "/dev/shm")
    ) || path.parent() == Some(Path::new("/home"))
        || account_home().is_some_and(|home| home.starts_with(path))
}

fn real_home() -> Option<PathBuf> {
    // HOME is deliberately task/work by launch time. Query the account database
    // before Landlock is installed; do not use that overwritten environment.
    let account = unsafe { libc::getpwuid(libc::getuid()) };
    if account.is_null() {
        return None;
    }
    let directory = unsafe { (*account).pw_dir };
    if directory.is_null() {
        return None;
    }
    let bytes = unsafe { std::ffi::CStr::from_ptr(directory) }.to_bytes();
    Some(PathBuf::from(std::ffi::OsStr::from_bytes(bytes)))
}

impl Config {
    fn validate(&mut self, executable: &Path) -> io::Result<()> {
        self.task = canonical(&self.task)?;
        self.work = canonical(&self.work)?;
        self.executable = canonical(&self.executable)?;
        if !self.task.is_dir()
            || !self.work.is_dir()
            || self.work != self.task.join("work")
            || broad(&self.task)
            || broad(&self.work)
            || self.executable != canonical(executable)?
            || !self.executable.is_file()
        {
            return Err(invalid("invalid task/work/interpreter boundary"));
        }
        if self.runtime_paths.len() > 128
            || self.parent_pid <= 1
            || self.limits.cpu_seconds == 0
            || self.limits.memory_bytes == 0
            || self.limits.file_bytes == 0
            || self.limits.open_files < 16
            || self.limits.open_files > 65536
        {
            return Err(invalid("invalid runtime paths or model resource limits"));
        }
        let mut paths = BTreeSet::new();
        for path in &self.runtime_paths {
            let path = canonical(path)?;
            if broad(&path)
                || self.work.starts_with(&path)
                || path.starts_with(&self.task)
                || path.starts_with("/proc")
                || path.starts_with("/sys")
            {
                return Err(invalid("runtime access is too broad or overlaps task"));
            }
            paths.insert(path);
        }
        self.runtime_paths = paths.into_iter().collect();
        Ok(())
    }
}

fn set_limit(resource: libc::__rlimit_resource_t, value: u64, hard: u64) -> io::Result<()> {
    let limit = libc::rlimit {
        rlim_cur: value as libc::rlim_t,
        rlim_max: hard as libc::rlim_t,
    };
    checked(
        unsafe { libc::setrlimit(resource, &limit) } as _,
        "setrlimit",
    )?;
    Ok(())
}
fn resource_limits(limits: &Limits) -> io::Result<()> {
    set_limit(
        libc::RLIMIT_CPU,
        limits.cpu_seconds,
        limits
            .cpu_seconds
            .checked_add(1)
            .ok_or_else(|| invalid("CPU limit overflow"))?,
    )?;
    for (kind, value) in [
        (libc::RLIMIT_AS, limits.memory_bytes),
        (libc::RLIMIT_FSIZE, limits.file_bytes),
        (libc::RLIMIT_NOFILE, limits.open_files),
        (libc::RLIMIT_NPROC, 0),
        (libc::RLIMIT_CORE, 0),
    ] {
        set_limit(kind, value, value)?;
    }
    Ok(())
}

#[repr(C)]
struct Ruleset {
    handled_access_fs: u64,
    handled_access_net: u64,
    scoped: u64,
}
// Kernel UAPI uses a packed structure: parent_fd starts at byte 8 and total
// size is 12, not the default Rust ABI's padded 16 bytes.
#[repr(C, packed)]
struct PathRule {
    allowed_access: u64,
    parent_fd: i32,
}

fn add_path(ruleset: &OwnedFd, path: &Path, rights: u64) -> io::Result<()> {
    let name = CString::new(path.as_os_str().as_bytes()).map_err(|_| invalid("NUL in path"))?;
    let fd = checked(
        unsafe { libc::open(name.as_ptr(), libc::O_PATH | libc::O_CLOEXEC) } as _,
        "open Landlock path",
    )?;
    let descriptor = unsafe { OwnedFd::from_raw_fd(fd as i32) };
    let rights = if path.is_dir() {
        rights
    } else {
        rights & !ACCESS_READ_DIR
    };
    let rule = PathRule {
        allowed_access: rights,
        parent_fd: descriptor.as_raw_fd(),
    };
    checked(
        unsafe { libc::syscall(LL_ADD, ruleset.as_raw_fd(), 1, &rule as *const PathRule, 0) },
        "landlock_add_rule",
    )?;
    Ok(())
}

fn filesystem(config: &Config) -> io::Result<()> {
    let abi = checked(
        unsafe { libc::syscall(LL_CREATE, std::ptr::null::<u8>(), 0, 1) },
        "Landlock ABI query",
    )? as i32;
    if abi < MINIMUM_ABI.max(config.minimum_landlock_abi) {
        return Err(invalid(
            "Landlock ABI >=3 is required (including truncate protection)",
        ));
    }
    let handled = if abi >= 5 {
        (1u64 << 16) - 1
    } else {
        (1u64 << 15) - 1
    };
    let attr = Ruleset {
        handled_access_fs: handled,
        handled_access_net: 0, // seccomp denies every network family
        // ABI 6 scopes signals and abstract UNIX sockets to this domain.
        scoped: if abi >= 6 { (1 << 0) | (1 << 1) } else { 0 },
    };
    // Older kernels reject structure extensions they do not understand.
    let attribute_size = if abi >= 6 {
        std::mem::size_of::<Ruleset>()
    } else {
        8
    };
    let fd = checked(
        unsafe { libc::syscall(LL_CREATE, &attr as *const Ruleset, attribute_size, 0) },
        "landlock_create_ruleset",
    )?;
    let ruleset = unsafe { OwnedFd::from_raw_fd(fd as i32) };
    for path in &config.runtime_paths {
        let extra = if path == Path::new("/dev/null") {
            ACCESS_WRITE_FILE | (handled & ACCESS_IOCTL_DEV)
        } else {
            0
        };
        add_path(&ruleset, path, READ | extra)?;
    }
    // The Python child checks these two kernel fields before model imports.
    // This proc inode survives exec; no other process or procfs subtree is granted.
    add_path(&ruleset, Path::new("/proc/self/status"), ACCESS_READ_FILE)?;
    add_path(&ruleset, &config.task, READ)?;
    add_path(&ruleset, &config.work, WORK)?;
    add_path(
        &ruleset,
        &config.executable,
        ACCESS_READ_FILE | ACCESS_EXECUTE,
    )?;
    // execve also opens the ELF interpreter. Grant execute only to the system
    // loaders, not every executable in a runtime/library tree.
    for loader in ["/lib64/ld-linux-x86-64.so.2", "/lib/ld-linux-aarch64.so.1"] {
        let path = Path::new(loader);
        if path.exists() {
            add_path(
                &ruleset,
                &fs::canonicalize(path)?,
                ACCESS_READ_FILE | ACCESS_EXECUTE,
            )?;
        }
    }
    checked(
        unsafe { libc::syscall(LL_RESTRICT, ruleset.as_raw_fd(), 0) },
        "landlock_restrict_self",
    )?;
    Ok(())
}

const LD_ABS: u16 = 0x20;
const JMP_EQ: u16 = 0x15;
const RET: u16 = 0x06;
const KILL: u32 = 0x80000000;
const ALLOW: u32 = 0x7fff0000;
const DENY: u32 = 0x00050000 | libc::EPERM as u32;
fn instruction(code: u16, jt: u8, jf: u8, k: u32) -> libc::sock_filter {
    libc::sock_filter { code, jt, jf, k }
}

fn deny_commands(filter: &mut Vec<libc::sock_filter>, syscall: libc::c_long, commands: &[u32]) {
    // seccomp_data.args[1] starts at byte 24 (64-bit args, little-endian
    // x86_64/aarch64). The kernel consumes the low command word as an int.
    // Non-matching syscalls skip the whole block; matching ones reload nr.
    let block_length = 2 * commands.len() + 2;
    filter.push(instruction(JMP_EQ, 0, block_length as u8, syscall as u32));
    filter.push(instruction(LD_ABS, 0, 0, 24));
    for command in commands {
        filter.push(instruction(JMP_EQ, 0, 1, *command));
        filter.push(instruction(RET, 0, 0, DENY));
    }
    filter.push(instruction(LD_ABS, 0, 0, 0));
}

fn syscalls() -> io::Result<()> {
    #[cfg(target_arch = "x86_64")]
    let arch = 0xc000003e;
    #[cfg(target_arch = "aarch64")]
    let arch = 0xc00000b7;
    #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
    return Err(invalid("unsupported seccomp architecture"));
    #[cfg(any(target_arch = "x86_64", target_arch = "aarch64"))]
    {
        let mut filter = vec![
            instruction(LD_ABS, 0, 0, 4),
            instruction(JMP_EQ, 1, 0, arch),
            instruction(RET, 0, 0, KILL),
            instruction(LD_ABS, 0, 0, 0),
        ];
        // Reject x32 and unknown syscall encodings before the deny list.
        filter.push(instruction(0x35, 0, 1, 0x40000000)); // BPF_JGE
        filter.push(instruction(RET, 0, 0, KILL));
        // Fail closed for newer APIs until their security effects are reviewed
        // (includes cachestat, fchmodat2, new mount and cross-process APIs).
        filter.push(instruction(0x35, 0, 1, 449));
        filter.push(instruction(RET, 0, 0, DENY));
        deny_commands(
            &mut filter,
            libc::SYS_fcntl,
            &[
                libc::F_SETOWN as u32,
                15, /* F_SETOWN_EX */
                10, /* F_SETSIG */
            ],
        );
        deny_commands(
            &mut filter,
            libc::SYS_ioctl,
            &[0x8901 /* FIOSETOWN */, 0x8902 /* SIOCSPGRP */],
        );
        let mut denied = vec![
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
            libc::SYS_syslog,
            libc::SYS_personality,
            libc::SYS_socket,
            libc::SYS_socketpair,
            libc::SYS_connect,
            libc::SYS_bind,
            libc::SYS_listen,
            libc::SYS_accept,
            libc::SYS_accept4,
            libc::SYS_sendto,
            libc::SYS_sendmsg,
            libc::SYS_sendmmsg,
            libc::SYS_recvfrom,
            libc::SYS_recvmsg,
            libc::SYS_recvmmsg,
            libc::SYS_shutdown,
            libc::SYS_clone,
            libc::SYS_setsid,
            libc::SYS_setpgid,
            libc::SYS_unshare,
            libc::SYS_setns,
            libc::SYS_mount,
            libc::SYS_umount2,
            libc::SYS_pivot_root,
            libc::SYS_chroot,
            libc::SYS_ptrace,
            libc::SYS_process_vm_readv,
            libc::SYS_process_vm_writev,
            libc::SYS_kill,
            libc::SYS_tkill,
            libc::SYS_tgkill,
            libc::SYS_rt_sigqueueinfo,
            libc::SYS_rt_tgsigqueueinfo,
            libc::SYS_bpf,
            libc::SYS_perf_event_open,
            libc::SYS_keyctl,
            libc::SYS_add_key,
            libc::SYS_request_key,
            libc::SYS_open_by_handle_at,
            libc::SYS_name_to_handle_at,
            libc::SYS_init_module,
            libc::SYS_finit_module,
            libc::SYS_delete_module,
            libc::SYS_reboot,
            libc::SYS_kexec_load,
            libc::SYS_swapon,
            libc::SYS_swapoff,
            libc::SYS_userfaultfd,
            libc::SYS_setuid,
            libc::SYS_setgid,
            libc::SYS_setreuid,
            libc::SYS_setregid,
            libc::SYS_setresuid,
            libc::SYS_setresgid,
            libc::SYS_setfsuid,
            libc::SYS_setfsgid,
            libc::SYS_setgroups,
            libc::SYS_capset,
            // Landlock does not mediate metadata changes. Deny them globally
            // rather than letting a model chmod/chown unrelated same-uid files.
            libc::SYS_fchmod,
            libc::SYS_fchmodat,
            libc::SYS_fchown,
            libc::SYS_fchownat,
            libc::SYS_setxattr,
            libc::SYS_lsetxattr,
            libc::SYS_fsetxattr,
            libc::SYS_removexattr,
            libc::SYS_lremovexattr,
            libc::SYS_fremovexattr,
            libc::SYS_utimensat,
            libc::SYS_acct,
            libc::SYS_quotactl,
            // prlimit64 accepts another same-uid PID: it must not be usable to
            // change the trusted supervisor's budgets.
            libc::SYS_prlimit64,
            libc::SYS_sched_setaffinity,
            libc::SYS_sched_setparam,
            libc::SYS_sched_setscheduler,
            libc::SYS_sched_setattr,
            libc::SYS_setpriority,
            libc::SYS_prctl,
            libc::SYS_seccomp,
        ];
        #[cfg(target_arch = "x86_64")]
        denied.extend([
            libc::SYS_fork,
            libc::SYS_vfork,
            libc::SYS_iopl,
            libc::SYS_ioperm,
            libc::SYS_chmod,
            libc::SYS_chown,
            libc::SYS_lchown,
            libc::SYS_utime,
            libc::SYS_utimes,
            libc::SYS_futimesat,
        ]);
        // Modern syscall numbers shared by x86_64 and aarch64. Deny APIs that
        // bypass path checks, create processes, or mutate mounts/namespaces.
        denied.extend([
            424, 425, 426, 427, 428, 429, 430, 431, 432, 434, 435, 438, 440, 442, 448,
        ]);
        for number in denied {
            filter.push(instruction(JMP_EQ, 0, 1, number as u32));
            filter.push(instruction(RET, 0, 0, DENY));
        }
        filter.push(instruction(RET, 0, 0, ALLOW));
        let program = libc::sock_fprog {
            len: filter.len() as u16,
            filter: filter.as_mut_ptr(),
        };
        checked(
            unsafe { libc::prctl(libc::PR_SET_SECCOMP, 2, &program as *const libc::sock_fprog) }
                as _,
            "seccomp filter",
        )?;
        Ok(())
    }
}

fn close_descriptors() -> io::Result<()> {
    // close_range is available on every kernel new enough for Landlock ABI 3.
    checked(
        unsafe { libc::syscall(libc::SYS_close_range, 3u32, u32::MAX, 0u32) },
        "close inherited descriptors",
    )?;
    let null = File::open("/dev/null")?;
    checked(
        unsafe { libc::dup2(null.as_raw_fd(), 0) } as _,
        "null stdin",
    )?;
    Ok(())
}

pub fn launch() -> io::Result<std::convert::Infallible> {
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    if arguments.len() < 4 || arguments[0] != "--config" || arguments[2] != "--" {
        return Err(invalid(
            "usage: marinaframe-sandbox --config PATH -- INTERPRETER ARGS",
        ));
    }
    let mut bytes = Vec::new();
    File::open(&arguments[1])?
        .take(SETUP_LIMIT + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > SETUP_LIMIT {
        return Err(invalid("sandbox config is too large"));
    }
    let mut config: Config =
        serde_json::from_slice(&bytes).map_err(|error| invalid(&error.to_string()))?;
    config.validate(Path::new(&arguments[3]))?;
    close_descriptors()?;
    // User namespaces are intentionally not entered: their credential changes
    // would break the existing trusted supervisor identity and same-uid stop.
    // A network namespace can add defense when the caller already has the
    // necessary capability. Seccomp remains mandatory whether it succeeds or not.
    unsafe {
        libc::unshare(libc::CLONE_NEWNET);
    }
    checked(
        unsafe { libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL) } as _,
        "parent death signal",
    )?;
    if unsafe { libc::getppid() } != config.parent_pid {
        return Err(invalid("worker parent changed"));
    }
    checked(
        unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) } as _,
        "no_new_privs",
    )?;
    resource_limits(&config.limits)?;
    std::env::set_current_dir(&config.work)?;
    filesystem(&config)?;
    syscalls()?;
    // exec preserves PID, process group, hard limits, Landlock and seccomp.
    Err(Command::new(&arguments[3]).args(&arguments[4..]).exec())
}

#[cfg(test)]
mod home_tests {
    use super::*;

    #[test]
    fn account_lookup_is_required_for_nonstandard_home_and_ancestors() {
        // Fixed /home and /root strings cannot make this test pass. A mutation
        // removing the account-home predicate or lookup fails these assertions.
        let home = PathBuf::from("/data/accounts/person");
        for root in ["/data", "/data/accounts", "/data/accounts/person"] {
            assert!(broad_with_account(Path::new(root), || Some(home.clone())));
            assert!(!broad_with_account(Path::new(root), || None));
        }
        let actual = real_home().expect("Linux test account must resolve via getpwuid");
        assert!(broad(&actual));
    }
}
