// bash.exe shim for Claude Code's Bash tool on Windows (CLAUDE_CODE_GIT_BASH_PATH).
//
// Claude Code starts every Bash tool call as `bash -c -l "<cmd>"`. The login profile
// (Git for Windows' /etc/profile + profile.d) forks about 14 times before the command
// runs; on a machine where process creation is slow that is 5-14 s per tool call.
// This shim execs the real Git Bash with --noprofile --norc, adds the PATH entries
// /etc/profile would have added, hands bash the shim's own std handles explicitly
// (Claude Code spawns the shell detached, so plain handle inheritance loses stdout),
// and puts bash in a kill-on-close job object so a killed shim never leaves a shell behind.
//
// Build:  build.cmd  (uses the .NET Framework csc that ships with Windows; C# 5 syntax only)
// Wire:   settings.json env  "CLAUDE_CODE_GIT_BASH_PATH": "<this dir>\\bash.exe"   (new sessions only)
// Git:    BASH_NOPROFILE_GIT=<Git for Windows root> overrides the default C:\Program Files\Git
// Debug:  BASH_SHIM_DEBUG=<logfile>, or a log path in debug.on next to the exe, logs argv + exit code.
using System;
using System.Runtime.InteropServices;
using System.Text;

class BashShim {
    const uint CREATE_SUSPENDED = 0x4, CREATE_NO_WINDOW = 0x08000000, INFINITE = 0xFFFFFFFF, HANDLE_FLAG_INHERIT = 1;
    const int STARTF_USESTDHANDLES = 0x100;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct STARTUPINFO { public int cb; public string lpReserved, lpDesktop, lpTitle; public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags; public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError; }
    [StructLayout(LayoutKind.Sequential)] struct PROCESS_INFORMATION { public IntPtr hProcess, hThread; public int dwProcessId, dwThreadId; }
    [StructLayout(LayoutKind.Sequential)] struct JOBOBJECT_BASIC_LIMIT_INFORMATION { public long PerProcessUserTimeLimit, PerJobUserTimeLimit; public uint LimitFlags; public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize; public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass, SchedulingClass; }
    [StructLayout(LayoutKind.Sequential)] struct IO_COUNTERS { public ulong a, b, c, d, e, f; }
    [StructLayout(LayoutKind.Sequential)] struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION { public JOBOBJECT_BASIC_LIMIT_INFORMATION Basic; public IO_COUNTERS Io; public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed; }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool CreateProcessW(string app, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit, uint flags, IntPtr env, string cwd, ref STARTUPINFO si, out PROCESS_INFORMATION pi);
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr GetStdHandle(int n);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetHandleInformation(IntPtr h, uint mask, uint flags);
    [DllImport("kernel32.dll", SetLastError = true)] static extern uint WaitForSingleObject(IntPtr h, uint ms);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool GetExitCodeProcess(IntPtr h, out uint code);
    [DllImport("kernel32.dll", SetLastError = true)] static extern uint ResumeThread(IntPtr h);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll")] static extern IntPtr GetConsoleWindow();
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr CreateJobObject(IntPtr a, string name);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetInformationJobObject(IntPtr job, int cls, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, int len);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    // Windows CommandLineToArgv quoting; Git Bash parses its command line the same way.
    static string Quote(string s) {
        if (s.Length > 0 && s.IndexOfAny(new[] { ' ', '\t', '\n', '\v', '"' }) < 0) return s;
        var sb = new StringBuilder("\""); int bs = 0;
        foreach (char c in s) {
            if (c == '\\') { bs++; continue; }
            if (c == '"') { sb.Append('\\', bs * 2 + 1).Append('"'); bs = 0; continue; }
            sb.Append('\\', bs).Append(c); bs = 0;
        }
        return sb.Append('\\', bs * 2).Append('"').ToString();
    }

    static IntPtr Inheritable(int n) {
        IntPtr h = GetStdHandle(n);
        if (h != IntPtr.Zero && h != new IntPtr(-1)) SetHandleInformation(h, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        return h;
    }

    static int Main(string[] args) {
        string git = Environment.GetEnvironmentVariable("BASH_NOPROFILE_GIT");
        if (string.IsNullOrEmpty(git)) git = @"C:\Program Files\Git";
        string exe = git + @"\bin\bash.exe";
        var cmd = new StringBuilder(Quote(exe)).Append(" --noprofile --norc");
        foreach (var a in args) cmd.Append(' ').Append(Quote(a));

        // What /etc/profile would have put first on PATH (MSYS converts these to /usr/bin etc.).
        string path = Environment.GetEnvironmentVariable("PATH") ?? "";
        Environment.SetEnvironmentVariable("PATH", git + @"\usr\local\bin;" + git + @"\usr\bin;" + git + @"\bin;" + git + @"\mingw64\bin;" + path);
        if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("LANG"))) Environment.SetEnvironmentVariable("LANG", "en_US.UTF-8");
        if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("MSYSTEM"))) Environment.SetEnvironmentVariable("MSYSTEM", "MINGW64");

        var si = new STARTUPINFO(); si.cb = Marshal.SizeOf(si);
        si.dwFlags = STARTF_USESTDHANDLES;
        si.hStdInput = Inheritable(-10); si.hStdOutput = Inheritable(-11); si.hStdError = Inheritable(-12);
        uint flags = CREATE_SUSPENDED | (GetConsoleWindow() == IntPtr.Zero ? CREATE_NO_WINDOW : 0);

        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job != IntPtr.Zero) {
            var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION(); info.Basic.LimitFlags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            SetInformationJobObject(job, 9, ref info, Marshal.SizeOf(info)); // JobObjectExtendedLimitInformation
        }

        PROCESS_INFORMATION pi;
        if (!CreateProcessW(exe, cmd, IntPtr.Zero, IntPtr.Zero, true, flags, IntPtr.Zero, null, ref si, out pi)) {
            Console.Error.WriteLine("bash shim: CreateProcess failed for " + exe + ", error " + Marshal.GetLastWin32Error());
            return 127;
        }
        if (job != IntPtr.Zero) AssignProcessToJobObject(job, pi.hProcess);
        ResumeThread(pi.hThread);
        WaitForSingleObject(pi.hProcess, INFINITE);
        uint code; if (!GetExitCodeProcess(pi.hProcess, out code)) code = 1;
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);

        string dbg = Environment.GetEnvironmentVariable("BASH_SHIM_DEBUG");
        try {
            string marker = System.IO.Path.Combine(System.IO.Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location), "debug.on");
            if (string.IsNullOrEmpty(dbg) && System.IO.File.Exists(marker)) dbg = System.IO.File.ReadAllText(marker).Trim();
            if (!string.IsNullOrEmpty(dbg)) {
                var sb = new StringBuilder();
                sb.Append("---- ").Append(DateTime.Now.ToString("HH:mm:ss.fff")).Append(" exit=").Append(code).Append(" console=").Append(GetConsoleWindow() != IntPtr.Zero).Append('\n');
                for (int i = 0; i < args.Length; i++) sb.Append("argv[").Append(i).Append("]=").Append(args[i].Length > 600 ? args[i].Substring(0, 600) + "...(" + args[i].Length + ")" : args[i]).Append('\n');
                System.IO.File.AppendAllText(dbg, sb.ToString());
            }
        } catch { }
        return (int)code;
    }
}
