#define NOMINMAX
#include <windows.h>
#include <stdint.h>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

static const DWORD kWorkerKilled = 0xE8000001;
static const DWORD kCallerKilled = 0xE8000002;
static const DWORD kCustodianKilled = 0xE8000003;
static const DWORD kRequestMs = 1200;
DWORD gCreateError = 0;
const char* gCreateStage = "none";
ULONGLONG gJobCreateMs = 0, gPipeCreateMs = 0, gCreateProcessMs = 0, gAssignJobMs = 0, gResumeMs = 0;
ULONGLONG gQueryJobMs = 0, gTerminateJobMs = 0, gWaitMs = 0, gCloseHandleMs = 0;
DWORD gCloseCalls = 0, gCloseFailures = 0;

std::wstring ExePath() {
    std::vector<wchar_t> b(32768);
    DWORD n = GetModuleFileNameW(nullptr, b.data(), (DWORD)b.size());
    return n ? std::wstring(b.data(), n) : L"";
}
std::wstring Q(const std::wstring& s) { return L"\"" + s + L"\""; }
std::wstring HArg(HANDLE h) { return std::to_wstring((unsigned long long)(uintptr_t)h); }
HANDLE HParse(const wchar_t* s) { return (HANDLE)(uintptr_t)_wcstoui64(s, nullptr, 10); }
std::string NarrowAscii(const std::wstring& w) { std::string s; for (wchar_t c : w) s.push_back(c >= 0 && c < 128 ? (char)c : '?'); return s; }
void Inherit(HANDLE h, bool yes) { SetHandleInformation(h, HANDLE_FLAG_INHERIT, yes ? HANDLE_FLAG_INHERIT : 0); }
bool Valid(HANDLE h) { DWORD f = 0; return h && h != INVALID_HANDLE_VALUE && GetHandleInformation(h, &f); }
void Close(HANDLE& h) { if (h && h != INVALID_HANDLE_VALUE) { ULONGLONG t = GetTickCount64(); BOOL ok = CloseHandle(h); gCloseHandleMs += GetTickCount64() - t; ++gCloseCalls; if (ok) h = nullptr; else ++gCloseFailures; } }
DWORD WaitTracked(HANDLE h, DWORD ms) { ULONGLONG t = GetTickCount64(); DWORD w = WaitForSingleObject(h, ms); gWaitMs += GetTickCount64() - t; return w; }
BOOL TerminateJobTracked(HANDLE h, DWORD code) { ULONGLONG t = GetTickCount64(); BOOL ok = TerminateJobObject(h, code); gTerminateJobMs += GetTickCount64() - t; return ok; }

bool WriteExact(HANDLE h, const void* p, DWORD n) {
    const char* b = (const char*)p;
    DWORD off = 0;
    while (off < n) { DWORD k = 0; if (!WriteFile(h, b + off, n - off, &k, nullptr) || !k) return false; off += k; }
    return true;
}
bool WriteLine(HANDLE h, const std::string& s) {
    return WriteExact(h, s.data(), (DWORD)s.size()) && WriteExact(h, "\n", 1);
}
bool ReadLineSync(HANDLE h, std::string& s) {
    s.clear();
    for (;;) { char c = 0; DWORD n = 0; if (!ReadFile(h, &c, 1, &n, nullptr) || n != 1) return false;
        if (c == '\n') return true; if (c != '\r') s.push_back(c); if (s.size() > 4096) return false; }
}
bool ReadLineDeadline(HANDLE h, ULONGLONG deadline, std::string& s) {
    s.clear();
    while (GetTickCount64() < deadline) {
        DWORD avail = 0;
        if (!PeekNamedPipe(h, nullptr, 0, nullptr, &avail, nullptr)) return false;
        if (!avail) { Sleep(1); continue; }
        char c = 0; DWORD n = 0;
        if (!ReadFile(h, &c, 1, &n, nullptr) || n != 1) return false;
        if (c == '\n') return true; if (c != '\r') s.push_back(c); if (s.size() > 4096) return false;
    }
    return false;
}
bool PipeWrite(HANDLE h, HANDLE event, OVERLAPPED& ov, const void* data, DWORD size, ULONGLONG deadline) {
    ResetEvent(event); ov = {}; ov.hEvent = event;
    DWORD n = 0; BOOL ok = WriteFile(h, data, size, &n, &ov); DWORD e = ok ? ERROR_SUCCESS : GetLastError();
    if (!ok && e == ERROR_IO_PENDING) {
        DWORD left = deadline > GetTickCount64() ? (DWORD)(deadline - GetTickCount64()) : 0;
        if (WaitForSingleObject(event, left) != WAIT_OBJECT_0) {
            CancelIoEx(h, &ov);
            if (WaitForSingleObject(event, INFINITE) != WAIT_OBJECT_0) return false;
            DWORD ignored = 0; GetOverlappedResult(h, &ov, &ignored, FALSE); return false;
        }
        ok = GetOverlappedResult(h, &ov, &n, FALSE);
    }
    return ok && n == size;
}
bool PipeReadChar(HANDLE h, HANDLE event, OVERLAPPED& ov, char& c, ULONGLONG deadline) {
    ResetEvent(event); ov = {}; ov.hEvent = event;
    DWORD n = 0; BOOL ok = ReadFile(h, &c, 1, &n, &ov); DWORD e = ok ? ERROR_SUCCESS : GetLastError();
    if (!ok && e == ERROR_IO_PENDING) {
        DWORD left = deadline > GetTickCount64() ? (DWORD)(deadline - GetTickCount64()) : 0;
        if (WaitForSingleObject(event, left) != WAIT_OBJECT_0) {
            CancelIoEx(h, &ov);
            if (WaitForSingleObject(event, INFINITE) != WAIT_OBJECT_0) return false;
            DWORD ignored = 0; GetOverlappedResult(h, &ov, &ignored, FALSE); return false;
        }
        ok = GetOverlappedResult(h, &ov, &n, FALSE);
    }
    return ok && n == 1;
}
bool PipeReadLine(HANDLE h, HANDLE event, OVERLAPPED& ov, ULONGLONG deadline, std::string& s) {
    s.clear();
    for (;;) {
        if (GetTickCount64() >= deadline) return false;
        DWORD available = 0;
        if (!PeekNamedPipe(h, nullptr, 0, nullptr, &available, nullptr)) return false;
        if (available == 0) { Sleep(1); continue; }
        char c = 0; if (!PipeReadChar(h, event, ov, c, deadline)) return false;
        if (c == '\n') return true; if (c != '\r') s.push_back(c); if (s.size() > 4096) return false; }
}
bool PipeWriteLine(HANDLE h, HANDLE event, OVERLAPPED& ov, const std::string& s, ULONGLONG deadline) {
    std::string line = s + "\n";
    return PipeWrite(h, event, ov, line.data(), (DWORD)line.size(), deadline);
}

HANDLE NewJob() {
    ULONGLONG t = GetTickCount64(); HANDLE j = CreateJobObjectW(nullptr, nullptr); gJobCreateMs += GetTickCount64() - t;
    if (!j) return nullptr;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION x{}; x.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(j, JobObjectExtendedLimitInformation, &x, sizeof(x))) { CloseHandle(j); return nullptr; }
    return j;
}
bool Active(HANDLE job, DWORD& n) {
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION x{};
    ULONGLONG t = GetTickCount64(); BOOL ok = QueryInformationJobObject(job, JobObjectBasicAccountingInformation, &x, sizeof(x), nullptr); gQueryJobMs += GetTickCount64() - t;
    if (!ok) return false;
    n = x.ActiveProcesses; return true;
}
DWORD LimitFlags(HANDLE job) {
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION x{};
    ULONGLONG t = GetTickCount64(); BOOL ok = QueryInformationJobObject(job, JobObjectExtendedLimitInformation, &x, sizeof(x), nullptr); gQueryJobMs += GetTickCount64() - t;
    if (!ok) return 0xFFFFFFFF;
    return x.BasicLimitInformation.LimitFlags;
}
bool CreateInJob(const std::wstring& cmd, const std::vector<HANDLE>& handles, HANDLE job, PROCESS_INFORMATION& pi,
                 HANDLE stdIn = nullptr, HANDLE stdOut = nullptr) {
    STARTUPINFOEXW sx{}; sx.StartupInfo.cb = sizeof(sx);
    if (stdIn || stdOut) { sx.StartupInfo.dwFlags |= STARTF_USESTDHANDLES;
        sx.StartupInfo.hStdInput = stdIn ? stdIn : GetStdHandle(STD_INPUT_HANDLE);
        sx.StartupInfo.hStdOutput = stdOut ? stdOut : GetStdHandle(STD_OUTPUT_HANDLE);
        sx.StartupInfo.hStdError = stdOut ? stdOut : GetStdHandle(STD_ERROR_HANDLE); }
    SIZE_T bytes = 0; DWORD attrs = (DWORD)(!handles.empty());
    InitializeProcThreadAttributeList(nullptr, attrs, 0, &bytes);
    std::vector<unsigned char> buf(bytes); sx.lpAttributeList = (LPPROC_THREAD_ATTRIBUTE_LIST)buf.data();
    if (!InitializeProcThreadAttributeList(sx.lpAttributeList, attrs, 0, &bytes)) { gCreateStage="init_attr"; gCreateError=GetLastError(); return false; }
    bool ok = true;
    if (!handles.empty()) { ok = UpdateProcThreadAttribute(sx.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        (void*)handles.data(), handles.size() * sizeof(HANDLE), nullptr, nullptr) != FALSE; if (!ok) { gCreateStage="handle_list"; gCreateError=GetLastError(); } }
    std::vector<wchar_t> mutableCmd(cmd.begin(), cmd.end()); mutableCmd.push_back(L'\0');
    if (ok) { ULONGLONG t = GetTickCount64(); ok = CreateProcessW(nullptr, mutableCmd.data(), nullptr, nullptr, !handles.empty(),
        EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED, nullptr, nullptr, &sx.StartupInfo, &pi) != FALSE;
        gCreateProcessMs += GetTickCount64() - t; if (!ok) { gCreateStage="CreateProcessW"; gCreateError=GetLastError(); } }
    if (ok && job) { ULONGLONG t = GetTickCount64(); ok = AssignProcessToJobObject(job, pi.hProcess) != FALSE;
        gAssignJobMs += GetTickCount64() - t; if (!ok) { gCreateStage="AssignProcessToJobObject"; gCreateError=GetLastError(); TerminateProcess(pi.hProcess, 0xE80000FF); CloseHandle(pi.hThread); CloseHandle(pi.hProcess); pi = {}; } }
    DeleteProcThreadAttributeList(sx.lpAttributeList); return ok;
}
void ClosePi(PROCESS_INFORMATION& p) { Close(p.hThread); Close(p.hProcess); }
DWORD ResumeTracked(HANDLE thread) { ULONGLONG t = GetTickCount64(); DWORD n = ResumeThread(thread); gResumeMs += GetTickCount64() - t; return n; }
bool StartPipePair(HANDLE& r, HANDLE& w) {
    SECURITY_ATTRIBUTES sa{ sizeof(sa), nullptr, TRUE };
    ULONGLONG t = GetTickCount64(); BOOL ok = CreatePipe(&r, &w, &sa, 4096); gPipeCreateMs += GetTickCount64() - t; return ok != FALSE;
}

int WorkerMain(int argc, wchar_t** argv) {
    bool startupStall = argc > 2 && std::wstring(argv[2]) == L"startup-stall";
    bool ignore = argc > 2 && std::wstring(argv[2]) == L"ignore-stall";
    if (startupStall) Sleep(INFINITE);
    WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "WORKER_READY");
    if (ignore) Sleep(INFINITE);
    for (;;) {
        std::string req; if (!ReadLineSync(GetStdHandle(STD_INPUT_HANDLE), req)) return 31;
        if (req == "success") { WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "DONE"); return 0; }
        if (req == "descendant") {
            std::wstring cmd = Q(ExePath()) + L" --sleeper"; std::vector<wchar_t> mutableCmd(cmd.begin(), cmd.end()); mutableCmd.push_back(L'\0');
            STARTUPINFOW si{}; si.cb = sizeof(si); PROCESS_INFORMATION child{};
            if (!CreateProcessW(nullptr, mutableCmd.data(), nullptr, nullptr, FALSE, CREATE_SUSPENDED, nullptr, nullptr, &si, &child)) return 32;
            DWORD resumed = ResumeThread(child.hThread); DWORD childPid = child.dwProcessId;
            CloseHandle(child.hThread); CloseHandle(child.hProcess);
            if (resumed == (DWORD)-1) return 33;
            WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "DESCENDANT_READY pid=" + std::to_string(childPid));
            Sleep(INFINITE);
        }
        if (req == "block") { WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "SETUP_BLOCK_READY"); Sleep(INFINITE); }
        if (req == "shutdown") { WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "BYE"); return 0; }
    }
}

int CustodianMain(int argc, wchar_t** argv) {
    if (argc < 11) return 41;
    HANDLE request = HParse(argv[2]), go = HParse(argv[3]), ready = HParse(argv[4]);
    HANDLE workerJob = HParse(argv[5]), workerProc = HParse(argv[6]), workerThread = HParse(argv[7]);
    HANDLE workerIn = HParse(argv[8]), workerOut = HParse(argv[9]); std::wstring mode = argv[10];
    DWORD active = 999; DWORD exitCode = STILL_ACTIVE;
    if (mode == L"not-ready") Sleep(INFINITE);
    bool handlesReady = Valid(request) && Valid(go) && Valid(workerJob) && Valid(workerProc) &&
        Valid(workerThread) && Valid(workerIn) && Valid(workerOut) && Active(workerJob, active) && active == 1 &&
        GetExitCodeProcess(workerProc, &exitCode) && exitCode == STILL_ACTIVE;
    if (!handlesReady) return 42;
    SetEvent(ready); // READY means IPC and all custodian controls are already held.
    if (WaitForSingleObject(go, INFINITE) != WAIT_OBJECT_0) return 43;
    if (mode == L"block" || mode == L"admission-sync" || mode == L"admission-overlapped")
        Sleep(INFINITE); // request path is deliberately wedged inside custodian.
    std::string req;
    if (!ReadLineSync(request, req)) return 44;
    if (mode == L"worker-join-block") {
        WriteLine(workerIn, "block"); std::string readyLine; ReadLineSync(workerOut, readyLine);
        WaitForSingleObject(workerProc, INFINITE); // synchronous Join-like stall, independent controller can kill custodian.
        return 45;
    }
    if (mode == L"cleanup-block") {
        WriteLine(workerIn, "success"); std::string done; ReadLineSync(workerOut, done);
        WaitForSingleObject(workerProc, INFINITE); // exit is exact; the next cleanup stage is deliberately stuck.
        DWORD n = 999; Active(workerJob, n); if (n != 0) return 46;
        Sleep(INFINITE); // simulated synchronous cleanup/receipt release stall.
    }
    if (mode == L"worker-write-block") {
        std::vector<char> huge(2 * 1024 * 1024, 'W'); DWORD wrote = 0;
        WriteFile(workerIn, huge.data(), (DWORD)huge.size(), &wrote, nullptr); // worker is not reading this payload.
        Sleep(INFINITE);
    }
    if (mode == L"descendant") {
        if (!WriteLine(workerIn, "descendant")) return 51;
        std::string childReady;
        if (!ReadLineSync(workerOut, childReady) || childReady.rfind("DESCENDANT_READY pid=", 0) != 0) return 52;
        WriteLine(request, "UNKNOWN_DESCENDANTS_READY " + childReady);
        return 0;
    }
    if (req != "success") return 47;
    if (!WriteLine(workerIn, "success")) return 48;
    std::string workerMessage;
    if (!ReadLineSync(workerOut, workerMessage) || workerMessage != "DONE") return 49;
    DWORD wait = WaitForSingleObject(workerProc, 5000); if (wait != WAIT_OBJECT_0) return 50;
    GetExitCodeProcess(workerProc, &exitCode); Active(workerJob, active);
    std::ostringstream result;
    result << "SUCCEEDED exact=" << ((exitCode == 0 && active == 0) ? 1 : 0)
           << " exit=" << exitCode << " job_active=" << active;
    WriteLine(request, result.str());
    return 0;
}

struct IoCtx {
    HANDLE pipe = nullptr, begin = nullptr, shutdown = nullptr, cancelRequest = nullptr, submitted = nullptr, done = nullptr, event = nullptr;
    OVERLAPPED ov{}; std::vector<char> buffer; DWORD bytes = 0, error = 0, ownerTid = 0, cancelError = ERROR_SUCCESS;
    BOOL ok = FALSE, cancelIssued = FALSE;
};
DWORD WINAPI IoReaper(void* raw) {
    IoCtx* c = (IoCtx*)raw; HANDLE startWaits[2] = { c->begin, c->shutdown };
    DWORD startWait = WaitForMultipleObjects(2, startWaits, FALSE, INFINITE);
    if (startWait == WAIT_OBJECT_0 + 1) return 0;
    c->ownerTid = GetCurrentThreadId();
    c->ov = {}; c->ov.hEvent = c->event;
    BOOL started = WriteFile(c->pipe, c->buffer.data(), (DWORD)c->buffer.size(), &c->bytes, &c->ov);
    DWORD e = started ? ERROR_SUCCESS : GetLastError(); SetEvent(c->submitted);
    if (!started && e == ERROR_IO_PENDING) {
        HANDLE waits[2] = { c->event, c->cancelRequest };
        DWORD w = WaitForMultipleObjects(2, waits, FALSE, INFINITE);
        if (w == WAIT_OBJECT_0 + 1) {
            c->cancelIssued = CancelIoEx(c->pipe, &c->ov);
            if (!c->cancelIssued) c->cancelError = GetLastError();
            w = WaitForSingleObject(c->event, INFINITE);
        }
        if (w == WAIT_OBJECT_0) { c->ok = GetOverlappedResult(c->pipe, &c->ov, &c->bytes, FALSE); if (!c->ok) c->error = GetLastError(); }
        else c->error = GetLastError();
    } else { c->ok = started; c->error = e; }
    SetEvent(c->done); return 0;
}
struct OverlappedApiArgs {
    HANDLE pipe = nullptr, go = nullptr, ownReady = nullptr, custReady = nullptr, report = nullptr;
    DWORD timeoutMs = 0; std::wstring mode; IoCtx* io = nullptr;
};
DWORD WINAPI OverlappedApiThread(void* raw) {
    OverlappedApiArgs* a = (OverlappedApiArgs*)raw;
    SetEvent(a->ownReady);
    if (WaitForSingleObject(a->go, INFINITE) != WAIT_OBJECT_0) return 1;
    ULONGLONG start = GetTickCount64(), deadline = start + a->timeoutMs;
    if (WaitForSingleObject(a->custReady, 0) != WAIT_OBJECT_0) {
        WriteLine(a->report, "API_RETURN status=REJECTED_NOT_READY elapsed_ms=0"); return 0;
    }
    SetEvent(a->io->begin);
    if (WaitForSingleObject(a->io->submitted, 300) != WAIT_OBJECT_0) {
        WriteLine(a->report, "API_RETURN status=UNKNOWN submit_not_observed elapsed_ms=" + std::to_string(GetTickCount64() - start)); return 0;
    }
    DWORD phaseMs = a->timeoutMs > 200 ? a->timeoutMs - 200 : a->timeoutMs;
    DWORD wait = WaitForSingleObject(a->io->done, phaseMs);
    bool unknown = wait != WAIT_OBJECT_0;
    bool pending = WaitForSingleObject(a->io->done, 0) != WAIT_OBJECT_0;
    std::ostringstream s; s << "API_RETURN status=" << (unknown ? "UNKNOWN" : "SENT")
        << " accepted_tick_ms=" << start << " local_deadline_tick_ms=" << deadline
        << " elapsed_ms=" << GetTickCount64() - start << " io_pending=" << pending
        << " owner_process_pid=" << GetCurrentProcessId() << " owner_thread_id=" << a->io->ownerTid
        << " api_thread_id=" << GetCurrentThreadId()
        << " pipe_handle=" << (unsigned long long)(uintptr_t)a->io->pipe
        << " event_handle=" << (unsigned long long)(uintptr_t)a->io->event
        << " overlapped_ptr=" << (unsigned long long)(uintptr_t)&a->io->ov
        << " buffer_bytes=" << a->io->buffer.size() << " context_preallocated_before_ready=1";
    WriteLine(a->report, s.str());
    return 0; // This thread is the simulated caller API; it returns with any pending op still owned by IoReaper.
}
int CallerMain(int argc, wchar_t** argv) {
    if (argc < 9) return 51;
    HANDLE pipe = HParse(argv[2]), go = HParse(argv[3]), ownReady = HParse(argv[4]);
    HANDLE custReady = HParse(argv[5]), report = HParse(argv[6]);
    DWORD timeoutMs = (DWORD)_wtoi(argv[7]); std::wstring mode = argv[8];
    HANDLE ioEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr); OVERLAPPED ov{}; IoCtx io; HANDLE reaper = nullptr;
    if (!ioEvent) return 52;
    if (mode == L"admission-overlapped") {
        io.pipe = pipe; io.begin = CreateEventW(nullptr, TRUE, FALSE, nullptr); io.shutdown = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        io.cancelRequest = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        io.submitted = CreateEventW(nullptr, TRUE, FALSE, nullptr); io.done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        io.event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        io.buffer.assign(2 * 1024 * 1024, 'X');
        if (!io.begin || !io.shutdown || !io.cancelRequest || !io.submitted || !io.done || !io.event) return 53;
        reaper = CreateThread(nullptr, 0, IoReaper, &io, 0, nullptr); if (!reaper) return 54;
        OverlappedApiArgs api{ pipe, go, ownReady, custReady, report, timeoutMs, mode, &io };
        HANDLE apiThread = CreateThread(nullptr, 0, OverlappedApiThread, &api, 0, nullptr);
        if (!apiThread) return 57;
        WaitForSingleObject(apiThread, INFINITE); // API thread returned; host process remains only to custody pending I/O.
        if (WaitForSingleObject(io.submitted, 0) == WAIT_OBJECT_0 && WaitForSingleObject(io.done, 0) != WAIT_OBJECT_0)
            SetEvent(io.cancelRequest);
        else SetEvent(io.shutdown);
        WaitForSingleObject(reaper, INFINITE);
        std::ostringstream cancel; cancel << "CANCEL_RESULT issued=" << (io.cancelIssued ? 1 : 0)
            << " error=" << io.cancelError << " io_pending_after=" << (WaitForSingleObject(io.done, 0) != WAIT_OBJECT_0)
            << " context_owner_thread_id=" << io.ownerTid;
        WriteLine(report, cancel.str());
        std::ostringstream done; done << "REAPER_DONE io_complete=1 ok=" << (io.ok ? 1 : 0)
            << " error=" << io.error << " bytes=" << io.bytes << " owner_thread_id=" << io.ownerTid;
        WriteLine(report, done.str());
        Close(apiThread); Close(reaper); Close(io.begin); Close(io.shutdown); Close(io.cancelRequest);
        Close(io.submitted); Close(io.done); Close(io.event); Close(ioEvent); return 0;
    }
    SetEvent(ownReady);
    if (WaitForSingleObject(go, INFINITE) != WAIT_OBJECT_0) return 55;
    ULONGLONG requestStart = GetTickCount64(), deadline = requestStart + timeoutMs;
    if (WaitForSingleObject(custReady, 0) != WAIT_OBJECT_0) {
        WriteLine(report, "API_RETURN status=REJECTED_NOT_READY elapsed_ms=" + std::to_string(GetTickCount64() - requestStart));
        Close(ioEvent); return 0;
    }
    if (mode == L"admission-sync") {
        std::vector<char> huge(2 * 1024 * 1024, 'A'); DWORD wrote = 0;
        BOOL ok = WriteFile(pipe, huge.data(), (DWORD)huge.size(), &wrote, nullptr);
        WriteLine(report, std::string("API_RETURN status=") + (ok ? "SYNC_WRITE_RETURNED" : "UNKNOWN_SYNC_WRITE_FAILED") +
            " elapsed_ms=" + std::to_string(GetTickCount64() - requestStart));
        Close(ioEvent); return ok ? 56 : 0;
    }
    OVERLAPPED writeOv{};
    ULONGLONG callerReturnDeadline = deadline > 250 ? deadline - 250 : deadline;
    if (!PipeWriteLine(pipe, ioEvent, writeOv, "success", callerReturnDeadline)) {
        WriteLine(report, "API_RETURN status=UNKNOWN send_timeout elapsed_ms=" + std::to_string(GetTickCount64() - requestStart));
        Close(ioEvent); return 0;
    }
    std::string response; OVERLAPPED readOv{};
    bool got = PipeReadLine(pipe, ioEvent, readOv, callerReturnDeadline, response);
    WriteLine(report, std::string("API_RETURN status=") + (got ? response : "UNKNOWN response_timeout") +
        " elapsed_ms=" + std::to_string(GetTickCount64() - requestStart));
    Close(ioEvent); return 0;
}

struct Supervisor {
    HANDLE workerJob = nullptr, custodianJob = nullptr, callerJob = nullptr;
    PROCESS_INFORMATION worker{}, custodian{}, caller{};
    HANDLE workerInRead = nullptr, workerInWrite = nullptr, workerOutRead = nullptr, workerOutWrite = nullptr;
    HANDLE requestServer = nullptr, requestClient = nullptr;
    HANDLE go = nullptr, workerReady = nullptr, custReady = nullptr, callerReady = nullptr;
    HANDLE reportRead = nullptr, reportWrite = nullptr;
};
bool StartChild(const std::wstring& roleCmd, const std::vector<HANDLE>& inherit, HANDLE job, PROCESS_INFORMATION& pi) {
    if (!CreateInJob(Q(ExePath()) + L" " + roleCmd, inherit, job, pi)) return false;
    if (ResumeTracked(pi.hThread) == (DWORD)-1) { TerminateJobObject(job, kCustodianKilled); return false; }
    return true;
}
bool WaitActive(HANDLE job, DWORD expected, DWORD ms) {
    ULONGLONG end = GetTickCount64() + ms;
    do { DWORD n = 0; if (!Active(job, n)) return false; if (n == expected) return true; Sleep(1); } while (GetTickCount64() < end);
    return false;
}
bool WriteJsonLine(const std::string& s) { std::cout << s << std::endl; return true; }

int SupervisorMain(const std::wstring& mode) {
    Supervisor h; const std::wstring exe = ExePath(); ULONGLONG prewarmStart = GetTickCount64();
    ULONGLONG createNamedPipeMs = 0, openNamedPipeMs = 0, connectNamedPipeMs = 0;
    h.workerJob = NewJob(); h.custodianJob = NewJob(); h.callerJob = NewJob();
    if (!h.workerJob || !h.custodianJob || !h.callerJob) { WriteJsonLine("{\"setup\":\"job_create_failed\"}"); return 2; }
    if (!StartPipePair(h.workerInRead, h.workerInWrite) || !StartPipePair(h.workerOutRead, h.workerOutWrite)) {
        WriteJsonLine("{\"setup\":\"worker_pipe_create_failed\"}"); return 3;
    }
    Inherit(h.workerInWrite, false); Inherit(h.workerOutRead, false);
    std::wstring workerMode = mode == L"prewarm-not-ready" ? L" startup-stall" :
        mode == L"worker-write-block" ? L" ignore-stall" : L"";
    std::wstring workerCmd = Q(exe) + L" --worker" + workerMode;
    Inherit(h.workerInRead, true); Inherit(h.workerOutWrite, true);
    if (!CreateInJob(workerCmd, { h.workerInRead, h.workerOutWrite }, h.workerJob, h.worker, h.workerInRead, h.workerOutWrite)) {
        WriteJsonLine("{\"setup\":\"worker_create_process_failed\",\"winerr\":" + std::to_string(gCreateError) + ",\"stage\":\"" + gCreateStage + "\"}"); return 4;
    }
    Close(h.workerInRead); Close(h.workerOutWrite);
    if (!WaitActive(h.workerJob, 1, 1000) || ResumeTracked(h.worker.hThread) == (DWORD)-1) {
        WriteJsonLine("{\"setup\":\"worker_job_or_resume_failed\"}"); return 5;
    }
    std::string workerReady;
    if (!ReadLineDeadline(h.workerOutRead, GetTickCount64() + 700, workerReady) || workerReady != "WORKER_READY") {
        TerminateJobObject(h.workerJob, kWorkerKilled); WaitForSingleObject(h.worker.hProcess, 1000);
        DWORD x = STILL_ACTIVE, n = 999; GetExitCodeProcess(h.worker.hProcess, &x); Active(h.workerJob, n);
        std::ostringstream o; o << "{\"mode\":\"prewarm-not-ready\",\"request_admitted\":false,\"status\":\"REJECTED_NOT_READY\",\"worker_ready\":false,\"worker_exit\":" << x << ",\"worker_job_active\":" << n << ",\"prewarm_elapsed_ms\":" << GetTickCount64() - prewarmStart << "}";
        WriteJsonLine(o.str()); ClosePi(h.worker); Close(h.workerOutRead); Close(h.workerInWrite); Close(h.workerJob); Close(h.custodianJob); Close(h.callerJob); return 0;
    }
    h.workerReady = CreateEventW(nullptr, TRUE, TRUE, nullptr);
    SECURITY_ATTRIBUTES evsa{ sizeof(evsa), nullptr, TRUE };
    h.go = CreateEventW(&evsa, TRUE, FALSE, nullptr); h.custReady = CreateEventW(&evsa, TRUE, FALSE, nullptr);
    h.callerReady = CreateEventW(&evsa, TRUE, FALSE, nullptr);
    if (!h.go || !h.custReady || !h.callerReady || !StartPipePair(h.reportRead, h.reportWrite)) {
        WriteJsonLine("{\"setup\":\"events_or_report_pipe_failed\"}"); return 6;
    }
    Inherit(h.reportRead, false);

    std::wstring pipeName = L"\\\\.\\pipe\\g1-r8-" + std::to_wstring(GetCurrentProcessId()) + L"-" + std::to_wstring(GetTickCount64());
    ULONGLONG tSetup = GetTickCount64();
    h.requestServer = CreateNamedPipeW(pipeName.c_str(), PIPE_ACCESS_DUPLEX, PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
        1, 4096, 4096, 0, nullptr);
    createNamedPipeMs = GetTickCount64() - tSetup;
    if (h.requestServer == INVALID_HANDLE_VALUE) { WriteJsonLine("{\"setup\":\"CreateNamedPipe_failed\"}"); return 7; }
    SECURITY_ATTRIBUTES clientSa{ sizeof(clientSa), nullptr, TRUE };
    DWORD clientFlags = mode == L"admission-sync" ? 0 : FILE_FLAG_OVERLAPPED;
    tSetup = GetTickCount64();
    h.requestClient = CreateFileW(pipeName.c_str(), GENERIC_READ | GENERIC_WRITE, 0, &clientSa, OPEN_EXISTING, clientFlags, nullptr);
    openNamedPipeMs = GetTickCount64() - tSetup;
    if (h.requestClient == INVALID_HANDLE_VALUE) { WriteJsonLine("{\"setup\":\"CreateFile_named_pipe_failed\"}"); return 8; }
    tSetup = GetTickCount64(); BOOL connected = ConnectNamedPipe(h.requestServer, nullptr);
    connectNamedPipeMs = GetTickCount64() - tSetup;
    if (!connected && GetLastError() != ERROR_PIPE_CONNECTED) { WriteJsonLine("{\"setup\":\"ConnectNamedPipe_failed\"}"); return 9; }

    // Custodian receives duplicated, already-owned worker Job/process/thread/pipe handles before READY.
    Inherit(h.workerJob, true); Inherit(h.worker.hProcess, true); Inherit(h.worker.hThread, true);
    Inherit(h.workerInWrite, true); Inherit(h.workerOutRead, true); Inherit(h.requestServer, true);
    std::vector<HANDLE> custHandles = { h.requestServer, h.go, h.custReady, h.workerJob, h.worker.hProcess,
        h.worker.hThread, h.workerInWrite, h.workerOutRead };
    std::wstring custMode = mode == L"custodian-not-ready" ? L"not-ready" : mode;
    std::wstring custCmd = L"--custodian " + HArg(h.requestServer) + L" " + HArg(h.go) + L" " + HArg(h.custReady) + L" " +
        HArg(h.workerJob) + L" " + HArg(h.worker.hProcess) + L" " + HArg(h.worker.hThread) + L" " +
        HArg(h.workerInWrite) + L" " + HArg(h.workerOutRead) + L" " + custMode;
    ULONGLONG prewarmCustStart = GetTickCount64();
    if (!StartChild(custCmd, custHandles, h.custodianJob, h.custodian)) {
        WriteJsonLine("{\"setup\":\"custodian_create_process_failed\"}"); return 10;
    }
    Close(h.requestServer); Close(h.workerInWrite); Close(h.workerOutRead);

    Inherit(h.requestClient, true); Inherit(h.go, true); Inherit(h.callerReady, true);
    Inherit(h.custReady, true); Inherit(h.reportWrite, true);
    std::vector<HANDLE> callHandles = { h.requestClient, h.go, h.callerReady, h.custReady, h.reportWrite };
    std::wstring callerMode = mode == L"custodian-not-ready" ? L"not-ready" : mode;
    std::wstring callerCmd = L"--caller " + HArg(h.requestClient) + L" " + HArg(h.go) + L" " + HArg(h.callerReady) + L" " +
        HArg(h.custReady) + L" " + HArg(h.reportWrite) + L" " + std::to_wstring(kRequestMs) + L" " + callerMode;
    if (!StartChild(callerCmd, callHandles, h.callerJob, h.caller)) { WriteJsonLine("{\"setup\":\"caller_create_process_failed\"}"); return 11; }
    Close(h.requestClient); Close(h.reportWrite);
    DWORD callerReadyWait = WaitTracked(h.callerReady, 1500);
    bool custReady = WaitForSingleObject(h.custReady, 0) == WAIT_OBJECT_0;
    bool callerReady = callerReadyWait == WAIT_OBJECT_0;
    bool ready = callerReady && (mode == L"custodian-not-ready" || custReady);
    ULONGLONG prewarmElapsed = GetTickCount64() - prewarmStart;
    if (!ready) {
        TerminateJobTracked(h.callerJob, kCallerKilled); TerminateJobTracked(h.custodianJob, kCustodianKilled);
        TerminateJobTracked(h.workerJob, kWorkerKilled); WaitTracked(h.worker.hProcess, 1000);
        DWORD wx = STILL_ACTIVE, wa = 999; GetExitCodeProcess(h.worker.hProcess, &wx); Active(h.workerJob, wa);
        std::ostringstream o; o << "{\"mode\":\"" << NarrowAscii(mode) << "\",\"request_admitted\":false,\"status\":\"REJECTED_NOT_READY\",\"caller_ready\":" << (callerReady ? "true":"false") << ",\"custodian_ready\":" << (custReady ? "true":"false") << ",\"prewarm_ms\":" << prewarmElapsed << ",\"worker_exit\":" << wx << ",\"worker_job_active\":" << wa << "}";
        WriteJsonLine(o.str()); return 0;
    }

    ULONGLONG requestStart = GetTickCount64(), deadline = requestStart + kRequestMs;
    std::ostringstream barrier;
    barrier << "SUPERVISOR_REQUEST_BARRIER request_id=" << NarrowAscii(mode) << "-" << GetCurrentProcessId() << "-" << requestStart
            << " request_start_tick_ms=" << requestStart << " deadline_tick_ms=" << deadline
            << " worker_pid=" << h.worker.dwProcessId
            << " custodian_pid=" << h.custodian.dwProcessId << " caller_pid=" << h.caller.dwProcessId
            << " worker_job_active=" << 1 << " custodian_ready=" << (custReady ? 1 : 0)
            << " caller_ready=" << (callerReady ? 1 : 0) << " prewarm_ms=" << prewarmElapsed;
    std::cout << barrier.str() << std::endl;
    SetEvent(h.go);
    std::string callerApi;
    bool apiReturned = ReadLineDeadline(h.reportRead, deadline, callerApi);
    bool callerKilled = false, callerBlocked = false;
    if (!apiReturned) {
        callerBlocked = WaitTracked(h.caller.hProcess, 0) != WAIT_OBJECT_0;
        TerminateJobTracked(h.callerJob, kCallerKilled); callerKilled = true;
        WaitTracked(h.caller.hProcess, 500);
        callerApi = "WATCHDOG_UNKNOWN caller_api_did_not_return_by_absolute_deadline";
    }
    ULONGLONG callerDecisionMs = GetTickCount64() - requestStart;
    bool wasOverlapped = mode == L"admission-overlapped";
    bool unknownAtDecision = !apiReturned || callerApi.find("status=UNKNOWN") != std::string::npos ||
        callerApi.find("WATCHDOG_UNKNOWN") != std::string::npos;
    bool controlsRetainedAtUnknown = false; DWORD activeAtUnknown = 999, custActiveAtUnknown = 999, callerActiveAtUnknown = 999;
    if (unknownAtDecision) {
        bool qWorker = Active(h.workerJob, activeAtUnknown);
        bool qCust = Active(h.custodianJob, custActiveAtUnknown);
        bool qCaller = Active(h.callerJob, callerActiveAtUnknown);
        controlsRetainedAtUnknown = Valid(h.workerJob) && Valid(h.worker.hProcess) && Valid(h.worker.hThread) &&
            Valid(h.custodianJob) && Valid(h.custodian.hProcess) && Valid(h.callerJob) &&
            Valid(h.caller.hProcess) && qWorker && qCust && qCaller;
    }
    // Caller UNKNOWN permits the independent controller to terminate a wedged custodian; controls stay held.
    if (mode != L"normal") TerminateJobTracked(h.custodianJob, kCustodianKilled);
    if (wasOverlapped && apiReturned) {
        std::string cancelLine, reaperLine;
        bool cancelLineRead = ReadLineDeadline(h.reportRead, GetTickCount64() + 200, cancelLine);
        // The OVERLAPPED may still be pending; closing the custodian process's endpoint lets the caller's reaper finish.
        bool reaperLineRead = ReadLineDeadline(h.reportRead, GetTickCount64() + 1500, reaperLine);
        callerApi += " | " + (cancelLineRead ? cancelLine : "CANCEL_RESULT_MISSING");
        callerApi += " | " + (reaperLineRead ? reaperLine : "REAPER_DONE_MISSING");
    }
    // Exact terminal proof comes from parent-owned worker handles and Job accounting, independent of custodian.
    DWORD workerExit = STILL_ACTIVE, active = 999; GetExitCodeProcess(h.worker.hProcess, &workerExit); Active(h.workerJob, active);
    DWORD activeBeforeSupervisorKill = active;
    if (mode == L"descendant") Active(h.workerJob, activeBeforeSupervisorKill);
    bool workerExact = workerExit != STILL_ACTIVE && active == 0;
    bool forcedWorkerKill = false;
    if (!workerExact) {
        forcedWorkerKill = TerminateJobTracked(h.workerJob, kWorkerKilled) != FALSE;
        WaitTracked(h.worker.hProcess, 1000); GetExitCodeProcess(h.worker.hProcess, &workerExit); Active(h.workerJob, active);
        workerExact = workerExit != STILL_ACTIVE && active == 0;
    }
    DWORD custExit = STILL_ACTIVE, custActive = 999;
    WaitTracked(h.custodian.hProcess, 500); GetExitCodeProcess(h.custodian.hProcess, &custExit); Active(h.custodianJob, custActive);
    DWORD callerExit = STILL_ACTIVE; WaitTracked(h.caller.hProcess, 500); GetExitCodeProcess(h.caller.hProcess, &callerExit);
    DWORD callerJobActive = 999; bool callerJobQueryOk = Active(h.callerJob, callerJobActive);
    bool callerExact = callerExit != STILL_ACTIVE && callerJobQueryOk && callerJobActive == 0;
    bool custodianExact = custExit != STILL_ACTIVE && custActive == 0;
    DWORD workerJobLimits = LimitFlags(h.workerJob);
    bool controlsValid = Valid(h.workerJob) && Valid(h.worker.hProcess) && Valid(h.worker.hThread) && Valid(h.custodianJob);
    bool release = workerExact;
    if (release) { Close(h.workerInWrite); Close(h.workerOutRead); ClosePi(h.worker); Close(h.workerJob); }
    bool controlsReleased = release && !Valid(h.workerInWrite) && !Valid(h.workerOutRead) &&
        !Valid(h.worker.hProcess) && !Valid(h.worker.hThread) && !Valid(h.workerJob) && gCloseFailures == 0;
    if (callerExact) { ClosePi(h.caller); Close(h.callerJob); }
    if (custodianExact) { ClosePi(h.custodian); Close(h.custodianJob); }
    if (callerExact && custodianExact) {
        Close(h.requestClient); Close(h.requestServer);
        Close(h.go); Close(h.workerReady); Close(h.custReady); Close(h.callerReady); Close(h.reportRead); Close(h.reportWrite);
    }
    std::ostringstream o;
    o << "{\"mode\":\"" << NarrowAscii(mode) << "\",\"status\":\""
      << ((apiReturned && callerApi.find("status=SUCCEEDED") != std::string::npos && controlsReleased) ? "SUCCEEDED" :
          (apiReturned && callerApi.find("REJECTED_NOT_READY") != std::string::npos) ? "REJECTED_NOT_READY" : "UNKNOWN")
      << "\",\"request_admitted\":" << (mode == L"custodian-not-ready" ? "false" : "true")
      << ",\"request_budget_ms\":" << kRequestMs << ",\"caller_decision_ms\":" << callerDecisionMs
      << ",\"request_start_tick_ms\":" << requestStart << ",\"absolute_deadline_tick_ms\":" << deadline
      << ",\"decision_tick_ms\":" << GetTickCount64()
      << ",\"caller_api_returned\":" << (apiReturned ? "true":"false") << ",\"caller_blocked_at_deadline\":" << (callerBlocked ? "true":"false")
      << ",\"caller_watchdog_terminated\":" << (callerKilled ? "true":"false") << ",\"caller_api_line\":\"" << callerApi << "\""
      << ",\"caller_exit\":" << callerExit << ",\"custodian_ready_before_go\":true,\"custodian_exit\":" << custExit
      << ",\"custodian_job_active_after\":" << custActive << ",\"custodian_job_killed_by_supervisor\":" << (mode != L"normal" ? "true":"false")
      << ",\"custodian_exact_exit_and_job_empty\":" << (custodianExact ? "true":"false")
      << ",\"caller_job_active_after\":" << callerJobActive << ",\"caller_exact_exit_and_job_empty\":" << (callerExact ? "true":"false")
      << ",\"worker_process_handle_preowned\":true,\"worker_thread_handle_preowned\":true,\"worker_job_handle_preowned\":true"
      << ",\"worker_exit\":" << workerExit << ",\"worker_job_active_after\":" << active
      << ",\"worker_job_active_before_supervisor_cleanup\":" << activeBeforeSupervisorKill
      << ",\"worker_exact_exit_and_job_empty\":" << (workerExact ? "true":"false") << ",\"worker_forced_kill\":" << (forcedWorkerKill ? "true":"false")
      << ",\"controls_retained_at_unknown\":" << (controlsRetainedAtUnknown ? "true":"false")
      << ",\"worker_job_active_at_unknown\":" << activeAtUnknown << ",\"custodian_job_active_at_unknown\":" << custActiveAtUnknown
      << ",\"caller_job_active_at_unknown\":" << callerActiveAtUnknown
      << ",\"worker_job_limit_flags\":" << workerJobLimits
      << ",\"controls_valid_before_exact_release\":" << (controlsValid ? "true":"false") << ",\"controls_released_after_exact_proof\":" << (controlsReleased ? "true":"false")
      << ",\"supervisor_pid\":" << GetCurrentProcessId() << ",\"worker_pid\":" << h.worker.dwProcessId
      << ",\"custodian_pid\":" << h.custodian.dwProcessId << ",\"caller_pid\":" << h.caller.dwProcessId
      << ",\"prewarm_ms\":" << prewarmElapsed << ",\"job_create_sync_ms\":" << gJobCreateMs
      << ",\"pipe_create_sync_ms\":" << gPipeCreateMs << ",\"create_process_sync_ms\":" << gCreateProcessMs
      << ",\"assign_job_sync_ms\":" << gAssignJobMs << ",\"resume_thread_sync_ms\":" << gResumeMs
      << ",\"create_named_pipe_sync_ms\":" << createNamedPipeMs << ",\"open_named_pipe_sync_ms\":" << openNamedPipeMs
      << ",\"connect_named_pipe_sync_ms\":" << connectNamedPipeMs
      << ",\"query_job_sync_ms\":" << gQueryJobMs << ",\"terminate_job_sync_ms\":" << gTerminateJobMs
      << ",\"wait_sync_ms\":" << gWaitMs << ",\"close_handle_sync_ms\":" << gCloseHandleMs
      << ",\"close_handle_calls\":" << gCloseCalls << ",\"close_handle_failures\":" << gCloseFailures
      << ",\"inner_job_assignment\":\"post_CreateProcess_pre_ResumeThread\",\"outer_job_inherited_at_creation\":true"
      << ",\"custodian_start_ms\":" << GetTickCount64() - prewarmCustStart << "}";
    WriteJsonLine(o.str());
    if (!controlsReleased) { // Retain any worker controls whose exact release could not be established.
        return 12;
    }
    return 0;
}

int OuterRun(const std::wstring& mode, DWORD externalPid) {
    HANDLE rootJob = NewJob(); if (!rootJob) { WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "OUTER_SETUP_FAILED job"); return 80; }
    HANDLE external = OpenProcess(PROCESS_DUP_HANDLE, FALSE, externalPid);
    HANDLE externalJob = nullptr;
    if (!external || !DuplicateHandle(GetCurrentProcess(), rootJob, external, &externalJob,
            JOB_OBJECT_QUERY | JOB_OBJECT_TERMINATE | SYNCHRONIZE, FALSE, 0)) {
        WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "OUTER_SETUP_FAILED external_job_duplicate"); Close(external); Close(rootJob); return 84;
    }
    Close(external);
    std::ostringstream control; control << "OUTER_JOB_CONTROL_READY launcher_pid=" << GetCurrentProcessId()
        << " external_job_handle=" << (unsigned long long)(uintptr_t)externalJob;
    WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), control.str());
    // The outside runner already owns a duplicate handle before this synchronous assignment/setup path.
    if (!AssignProcessToJobObject(rootJob, GetCurrentProcess())) {
        WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "OUTER_SETUP_FAILED assign_launcher_job"); return 85;
    }
    HANDLE outRead = nullptr, outWrite = nullptr;
    if (!StartPipePair(outRead, outWrite)) { Close(rootJob); return 81; }
    Inherit(outRead, false); Inherit(outWrite, true);
    PROCESS_INFORMATION child{};
    std::wstring cmd = Q(ExePath()) + L" " + mode;
    if (!CreateInJob(cmd, { outWrite }, nullptr, child, nullptr, outWrite)) {
        WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "OUTER_SETUP_FAILED child_create"); Close(outRead); Close(outWrite); Close(rootJob); return 82;
    }
    Close(outWrite);
    BOOL childInOuter = FALSE;
    if (!IsProcessInJob(child.hProcess, rootJob, &childInOuter) || !childInOuter) {
        TerminateProcess(child.hProcess, 0xE80000FE); ClosePi(child); Close(outRead); Close(rootJob);
        WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), "OUTER_SETUP_FAILED child_not_inherited_job"); return 86;
    }
    if (ResumeThread(child.hThread) == (DWORD)-1) { TerminateJobObject(rootJob, kCallerKilled); ClosePi(child); Close(outRead); Close(rootJob); return 83; }
    Sleep(150);
    DWORD active = 999; Active(rootJob, active);
    std::ostringstream ready; ready << "OUTER_JOB_READY child_pid=" << child.dwProcessId << " active_count=" << active
        << " external_job_handle=" << (unsigned long long)(uintptr_t)externalJob;
    WriteLine(GetStdHandle(STD_OUTPUT_HANDLE), ready.str());
    char buf[4096]; HANDLE consoleOut = GetStdHandle(STD_OUTPUT_HANDLE);
    for (;;) { DWORD n = 0; if (!ReadFile(outRead, buf, sizeof(buf), &n, nullptr) || n == 0) break; if (!WriteExact(consoleOut, buf, n)) break; }
    WaitForSingleObject(child.hProcess, 5000);
    DWORD exit = STILL_ACTIVE; GetExitCodeProcess(child.hProcess, &exit);
    ClosePi(child); Close(outRead); Close(rootJob); return (int)exit;
}

int wmain(int argc, wchar_t** argv) {
    if (argc >= 2 && std::wstring(argv[1]) == L"--sleeper") { Sleep(INFINITE); return 0; }
    if (argc >= 2 && std::wstring(argv[1]) == L"--worker") return WorkerMain(argc, argv);
    if (argc >= 2 && std::wstring(argv[1]) == L"--custodian") return CustodianMain(argc, argv);
    if (argc >= 2 && std::wstring(argv[1]) == L"--caller") return CallerMain(argc, argv);
    if (argc >= 4 && std::wstring(argv[1]) == L"--outer-run") return OuterRun(argv[2], (DWORD)_wtoi(argv[3]));
    return SupervisorMain(argc > 1 ? argv[1] : L"normal");
}
