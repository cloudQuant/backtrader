#define NOMINMAX
#include <windows.h>
#include <stdint.h>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

static const DWORD kBudgetMs = 1200;
static const DWORD kCallerKilled = 0xE9000001;
static const DWORD kWorkerKilled = 0xE9000002;
static const DWORD kBrokerKilled = 0xE9000003;
static const DWORD kOuterKilled = 0xE9000004;

struct alignas(8) Shared {
    volatile LONG go;
    volatile LONG requestKind;
    volatile LONG requestSubmitted;
    volatile LONG decision;
    volatile LONG apiReturned;
    volatile LONG brokerReady;
    volatile LONG writerStarted;
    volatile LONG writerSubmitted;
    volatile LONG writerPending;
    volatile LONG writerDone;
    volatile LONG writerError;
    volatile LONG cancelRequested;
    volatile LONG callerDeadSeen;
    volatile LONG helperReady;
    volatile LONG helperStage;
    volatile LONG shutdown;
    volatile LONG writerCancelIssued;
    volatile LONG writerCancelError;
    volatile LONG writerEventObserved;
    volatile LONG writerCompletionHoldMs;
    volatile LONG64 requestStartTick;
    volatile LONG64 deadlineTick;
    volatile LONG64 apiReturnTick;
    volatile LONG64 decisionTick;
    volatile LONG64 writerSubmitTick;
    volatile LONG64 writerCompletionTick;
    volatile LONG64 cancelTick;
};
struct BrokerContext {
    Shared* s;
    HANDLE pipe, begin, stop, cancel, submitted, complete, ovEvent;
    std::vector<char>* buffer;
};

std::wstring ExePath() {
    std::vector<wchar_t> b(32768);
    DWORD n = GetModuleFileNameW(nullptr, b.data(), (DWORD)b.size());
    return n ? std::wstring(b.data(), n) : L"";
}
std::wstring Quote(const std::wstring& s) { return L"\"" + s + L"\""; }
std::wstring HandleArg(HANDLE h) { return std::to_wstring((unsigned long long)(uintptr_t)h); }
HANDLE ParseHandle(const wchar_t* s) { return (HANDLE)(uintptr_t)_wcstoui64(s, nullptr, 10); }
std::string Narrow(const std::wstring& s) { std::string o; for (auto c : s) o.push_back(c >= 0 && c < 128 ? (char)c : '?'); return o; }
void Put32(volatile LONG* p, LONG v) { InterlockedExchange(p, v); }
LONG Get32(volatile LONG* p) { return InterlockedCompareExchange(p, 0, 0); }
void Put64(volatile LONG64* p, LONG64 v) { InterlockedExchange64(p, v); }
LONG64 Get64(volatile LONG64* p) { return InterlockedCompareExchange64(p, 0, 0); }
void WriteStd(const std::string& s) {
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD n = 0;
    if (h && h != INVALID_HANDLE_VALUE) WriteFile(h, s.data(), (DWORD)s.size(), &n, nullptr);
}
void WriteLine(const std::string& s) { WriteStd(s + "\n"); }
bool Valid(HANDLE h) { DWORD flags = 0; return h && h != INVALID_HANDLE_VALUE && GetHandleInformation(h, &flags); }
void Close(HANDLE& h) { if (Valid(h)) { CloseHandle(h); h = nullptr; } }

HANDLE NewJob() {
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION x{};
    x.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    HANDLE j = CreateJobObjectW(nullptr, nullptr);
    if (!j) return nullptr;
    if (!SetInformationJobObject(j, JobObjectExtendedLimitInformation, &x, sizeof(x))) { CloseHandle(j); return nullptr; }
    return j;
}
bool JobActive(HANDLE job, DWORD& active) {
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION x{};
    if (!QueryInformationJobObject(job, JobObjectBasicAccountingInformation, &x, sizeof(x), nullptr)) return false;
    active = x.ActiveProcesses;
    return true;
}
bool WaitJobEmpty(HANDLE job, DWORD ms, DWORD& last) {
    ULONGLONG end = GetTickCount64() + ms;
    do {
        if (!JobActive(job, last)) return false;
        if (last == 0) return true;
        Sleep(1);
    } while (GetTickCount64() < end);
    return false;
}

bool SpawnSuspended(const std::wstring& command, const std::vector<HANDLE>& inherit,
                    HANDLE job, PROCESS_INFORMATION& pi, HANDLE stdOut = nullptr) {
    STARTUPINFOEXW sx{};
    sx.StartupInfo.cb = sizeof(sx);
    if (stdOut) {
        sx.StartupInfo.dwFlags |= STARTF_USESTDHANDLES;
        sx.StartupInfo.hStdOutput = stdOut;
        sx.StartupInfo.hStdError = stdOut;
        sx.StartupInfo.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    }
    SIZE_T bytes = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &bytes);
    std::vector<unsigned char> storage(bytes);
    sx.lpAttributeList = (LPPROC_THREAD_ATTRIBUTE_LIST)storage.data();
    if (!InitializeProcThreadAttributeList(sx.lpAttributeList, 1, 0, &bytes)) return false;
    bool ok = UpdateProcThreadAttribute(sx.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        (void*)inherit.data(), inherit.size() * sizeof(HANDLE), nullptr, nullptr) != FALSE;
    std::vector<wchar_t> mutableCommand(command.begin(), command.end());
    mutableCommand.push_back(L'\0');
    if (ok) ok = CreateProcessW(nullptr, mutableCommand.data(), nullptr, nullptr, TRUE,
        CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT, nullptr, nullptr, &sx.StartupInfo, &pi) != FALSE;
    DeleteProcThreadAttributeList(sx.lpAttributeList);
    if (!ok) return false;
    if (job && !AssignProcessToJobObject(job, pi.hProcess)) {
        TerminateProcess(pi.hProcess, kWorkerKilled);
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess); pi = {};
        return false;
    }
    return true;
}
bool Resume(PROCESS_INFORMATION& pi) { return ResumeThread(pi.hThread) != (DWORD)-1; }
void ClosePi(PROCESS_INFORMATION& pi) { Close(pi.hThread); Close(pi.hProcess); }
bool StartPipe(HANDLE& server, HANDLE& client) {
    SECURITY_ATTRIBUTES sa{ sizeof(sa), nullptr, TRUE };
    std::wstring name = L"\\\\.\\pipe\\r9-inert-" + std::to_wstring(GetCurrentProcessId()) + L"-" + std::to_wstring(GetTickCount64());
    server = CreateNamedPipeW(name.c_str(), PIPE_ACCESS_INBOUND, PIPE_TYPE_BYTE | PIPE_WAIT,
        1, 4096, 4096, 0, &sa);
    if (server == INVALID_HANDLE_VALUE) return false;
    client = CreateFileW(name.c_str(), GENERIC_WRITE, 0, &sa, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
    if (client == INVALID_HANDLE_VALUE) return false;
    BOOL connected = ConnectNamedPipe(server, nullptr);
    return connected || GetLastError() == ERROR_PIPE_CONNECTED;
}

DWORD WINAPI WriterThread(void* raw) {
    BrokerContext* c = (BrokerContext*)raw;
    HANDLE starts[] = { c->begin, c->stop };
    DWORD which = WaitForMultipleObjects(2, starts, FALSE, INFINITE);
    if (which != WAIT_OBJECT_0) { Put32(&c->s->writerDone, 1); return 0; }
    OVERLAPPED ov{};
    ov.hEvent = c->ovEvent;
    DWORD bytes = 0;
    BOOL ok = WriteFile(c->pipe, c->buffer->data(), (DWORD)c->buffer->size(), &bytes, &ov);
    DWORD error = ok ? ERROR_SUCCESS : GetLastError();
    Put64(&c->s->writerSubmitTick, (LONG64)GetTickCount64());
    Put32(&c->s->writerSubmitted, 1);
    SetEvent(c->submitted);
    if (!ok && error == ERROR_IO_PENDING) {
        Put32(&c->s->writerPending, 1);
        HANDLE waits[] = { c->ovEvent, c->cancel };
        DWORD result = WaitForMultipleObjects(2, waits, FALSE, INFINITE);
        if (result == WAIT_OBJECT_0 + 1) {
            BOOL canceled = CancelIoEx(c->pipe, &ov);
            DWORD cancelError = canceled ? ERROR_SUCCESS : GetLastError();
            Put32(&c->s->writerCancelIssued, canceled ? 1 : 0);
            Put32(&c->s->writerCancelError, (LONG)cancelError);
            Put64(&c->s->cancelTick, (LONG64)GetTickCount64());
            WaitForSingleObject(c->ovEvent, INFINITE);
        }
        Put32(&c->s->writerEventObserved, 1);
        Put32(&c->s->writerCompletionHoldMs, 100); // Context stays owned while completion consumption is delayed.
        Sleep(100);
        ok = GetOverlappedResult(c->pipe, &ov, &bytes, FALSE);
        error = ok ? ERROR_SUCCESS : GetLastError();
    }
    Put32(&c->s->writerPending, 0);
    Put32(&c->s->writerError, (LONG)error);
    Put64(&c->s->writerCompletionTick, (LONG64)GetTickCount64());
    Put32(&c->s->writerDone, 1);
    SetEvent(c->complete);
    return 0;
}

int CallerMain(int argc, wchar_t** argv) {
    if (argc < 4) return 11;
    HANDLE mapping = ParseHandle(argv[2]), ready = ParseHandle(argv[3]);
    Shared* s = (Shared*)MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Shared));
    if (!s) return 12;
    SetEvent(ready);
    while (!Get32(&s->go)) YieldProcessor();
    Put32(&s->requestSubmitted, 1); // Fixed-size shared-memory handoff; no pipe/queue/child setup here.
    LONG64 deadline = Get64(&s->deadlineTick);
    for (;;) {
        if (Get32(&s->decision) != 0) break;
        if ((LONG64)GetTickCount64() >= deadline) {
            if (InterlockedCompareExchange(&s->decision, 1, 0) == 0)
                Put64(&s->decisionTick, (LONG64)GetTickCount64());
            break;
        }
        YieldProcessor();
    }
    Put64(&s->apiReturnTick, (LONG64)GetTickCount64());
    Put32(&s->apiReturned, 1);
    UnmapViewOfFile(s);
    return 0;
}

int BrokerMain(int argc, wchar_t** argv) {
    if (argc < 6) return 21;
    HANDLE mapping = ParseHandle(argv[2]), pipe = ParseHandle(argv[3]);
    HANDLE ready = ParseHandle(argv[4]), callerProcess = ParseHandle(argv[5]);
    Shared* s = (Shared*)MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Shared));
    if (!s) return 22;
    HANDLE begin = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE stop = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE cancel = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE submitted = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE complete = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE ovEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    std::vector<char> buffer(2 * 1024 * 1024, 'R');
    BrokerContext ctx{ s, pipe, begin, stop, cancel, submitted, complete, ovEvent, &buffer };
    if (!begin || !stop || !cancel || !submitted || !complete || !ovEvent) return 23;
    HANDLE writer = CreateThread(nullptr, 0, WriterThread, &ctx, 0, nullptr);
    if (!writer) return 24;
    Put32(&s->brokerReady, 1); // OVERLAPPED, event, pipe and 2 MiB buffer all pre-exist READY.
    SetEvent(ready);
    bool started = false;
    for (;;) {
        LONG request = Get32(&s->requestSubmitted);
        LONG kind = Get32(&s->requestKind);
        if (request && !started && (kind == 1 || kind == 2)) {
            started = true;
            Put32(&s->writerStarted, 1);
            SetEvent(begin);
        }
        if (request && !Get32(&s->callerDeadSeen) && WaitForSingleObject(callerProcess, 0) == WAIT_OBJECT_0)
            Put32(&s->callerDeadSeen, 1);
        if (Get32(&s->cancelRequested)) SetEvent(cancel);
        if (Get32(&s->shutdown)) {
            if (!started) SetEvent(stop);
            else if (!Get32(&s->writerDone)) SetEvent(cancel);
            if (!started || Get32(&s->writerDone)) break;
        }
        Sleep(1);
    }
    WaitForSingleObject(writer, INFINITE);
    CloseHandle(writer); CloseHandle(begin); CloseHandle(stop); CloseHandle(cancel);
    CloseHandle(submitted); CloseHandle(complete); CloseHandle(ovEvent);
    UnmapViewOfFile(s);
    return 0;
}

std::wstring ModePythonCommand(const std::wstring& mode, const std::wstring& python, HANDLE mapping, HANDLE ready) {
    std::wstring script = ExePath();
    size_t slash = script.find_last_of(L"\\/");
    script = script.substr(0, slash + 1) + L"r9_sacrificial_popen.py";
    return Quote(python) + L" " + Quote(script) + L" " + mode + L" " + HandleArg(mapping) + L" " + HandleArg(ready);
}

struct Handles {
    HANDLE mapping = nullptr, go = nullptr, helperReady = nullptr, callerReady = nullptr, brokerReady = nullptr;
    HANDLE serverPipe = nullptr, clientPipe = nullptr;
    HANDLE callerJob = nullptr, brokerJob = nullptr, workerJob = nullptr;
    PROCESS_INFORMATION caller{}, broker{}, worker{};
};

int SupervisorMain(const std::wstring& mode, HANDLE go, const std::wstring& python) {
    Handles h;
    h.callerJob = NewJob(); h.brokerJob = NewJob(); h.workerJob = NewJob();
    SECURITY_ATTRIBUTES inheritable{ sizeof(inheritable), nullptr, TRUE };
    h.mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, &inheritable, PAGE_READWRITE, 0, sizeof(Shared), nullptr);
    Shared* s = h.mapping ? (Shared*)MapViewOfFile(h.mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Shared)) : nullptr;
    h.helperReady = CreateEventW(&inheritable, TRUE, FALSE, nullptr);
    h.callerReady = CreateEventW(&inheritable, TRUE, FALSE, nullptr);
    h.brokerReady = CreateEventW(&inheritable, TRUE, FALSE, nullptr);
    if (!h.callerJob || !h.brokerJob || !h.workerJob || !s || !h.helperReady || !h.callerReady || !h.brokerReady) {
        WriteLine("{\"setup\":\"job_mapping_event_failed\"}"); return 2;
    }
    ZeroMemory(s, sizeof(*s));
    if (!StartPipe(h.serverPipe, h.clientPipe)) { WriteLine("{\"setup\":\"named_pipe_connect_failed\"}"); return 3; }

    std::wstring helperMode = mode == L"popen-before" ? L"before" : mode == L"popen-after" ? L"after" : L"idle";
    std::wstring helperCommand = ModePythonCommand(helperMode, python, h.mapping, h.helperReady);
    if (!SpawnSuspended(helperCommand, { h.mapping, h.helperReady }, h.workerJob, h.worker) || !Resume(h.worker)) {
        WriteLine("{\"setup\":\"sacrificial_worker_start_failed\"}"); return 4;
    }
    if (WaitForSingleObject(h.helperReady, 5000) != WAIT_OBJECT_0) {
        WriteLine("{\"setup\":\"sacrificial_worker_not_ready\"}"); return 5;
    }
    std::wstring exe = ExePath();
    std::wstring callerCommand = Quote(exe) + L" --caller " + HandleArg(h.mapping) + L" " + HandleArg(h.callerReady);
    if (!SpawnSuspended(callerCommand, { h.mapping, h.callerReady }, h.callerJob, h.caller) || !Resume(h.caller)) {
        WriteLine("{\"setup\":\"caller_start_failed\"}"); return 6;
    }
    if (WaitForSingleObject(h.callerReady, 5000) != WAIT_OBJECT_0) {
        WriteLine("{\"setup\":\"caller_not_ready\"}"); return 7;
    }
    HANDLE inheritedCallerProcess = nullptr;
    if (!DuplicateHandle(GetCurrentProcess(), h.caller.hProcess, GetCurrentProcess(), &inheritedCallerProcess,
            0, TRUE, DUPLICATE_SAME_ACCESS)) {
        WriteLine("{\"setup\":\"caller_process_handle_duplicate_failed\"}"); return 8;
    }
    std::wstring brokerCommand = Quote(exe) + L" --broker " + HandleArg(h.mapping) + L" " + HandleArg(h.clientPipe) + L" " +
        HandleArg(h.brokerReady) + L" " + HandleArg(inheritedCallerProcess);
    bool brokerStarted = SpawnSuspended(brokerCommand, { h.mapping, h.clientPipe, h.brokerReady, inheritedCallerProcess }, h.brokerJob, h.broker);
    DWORD brokerStartError = GetLastError();
    CloseHandle(inheritedCallerProcess);
    if (!brokerStarted || !Resume(h.broker)) {
        std::ostringstream error; error << "{\"setup\":\"broker_start_failed\",\"win32_error\":" << brokerStartError << "}";
        WriteLine(error.str()); return 8;
    }
    if (WaitForSingleObject(h.brokerReady, 5000) != WAIT_OBJECT_0) {
        WriteLine("{\"setup\":\"broker_not_ready\"}"); return 9;
    }
    CloseHandle(h.clientPipe); h.clientPipe = nullptr; // Broker now owns its inherited pipe handle.
    DWORD ja = 999, jb = 999, jc = 999;
    JobActive(h.workerJob, ja); JobActive(h.brokerJob, jb); JobActive(h.callerJob, jc);
    std::ostringstream ready;
    ready << "R9_READY supervisor_pid=" << GetCurrentProcessId() << " caller_pid=" << h.caller.dwProcessId
          << " broker_pid=" << h.broker.dwProcessId << " worker_pid=" << h.worker.dwProcessId
          << " caller_job_active=" << jc << " broker_job_active=" << jb << " worker_job_active=" << ja
          << " named_pipe_connected=1 broker_io_context_preowned=1 worker_job_preowned=1 caller_job_preowned=1";
    WriteLine(ready.str());

    if (WaitForSingleObject(go, 15000) != WAIT_OBJECT_0) {
        WriteLine("{\"setup\":\"go_not_received\"}"); return 10;
    }
    LONG kind = mode == L"caller-death" ? 2 : mode == L"popen-before" ? 3 : mode == L"popen-after" ? 4 : 1;
    ULONGLONG start = GetTickCount64(), deadline = start + kBudgetMs;
    Put32(&s->requestKind, kind);
    Put64(&s->requestStartTick, (LONG64)start);
    Put64(&s->deadlineTick, (LONG64)deadline);
    Put32(&s->go, 1);
    std::ostringstream barrier;
    barrier << "R9_REQUEST_BARRIER mode=" << Narrow(mode) << " request_start_tick_ms=" << start
            << " deadline_tick_ms=" << deadline << " budget_ms=" << kBudgetMs
            << " caller_pid=" << h.caller.dwProcessId << " broker_pid=" << h.broker.dwProcessId
            << " worker_pid=" << h.worker.dwProcessId;
    WriteLine(barrier.str());
    if (mode == L"outer-job") {
        ULONGLONG pendingWait = GetTickCount64() + 1000;
        while (GetTickCount64() < pendingWait && !Get32(&s->writerPending)) Sleep(1);
        std::ostringstream pending;
        pending << "R9_PENDING_IO pending=" << Get32(&s->writerPending) << " broker_pid=" << h.broker.dwProcessId
                << " caller_pid=" << h.caller.dwProcessId;
        WriteLine(pending.str());
        Sleep(INFINITE);
        return 0;
    }

    bool callerKilled = false, workerKilled = false, callerBlocked = false;
    if (kind == 2) {
        ULONGLONG until = start + 350;
        while (GetTickCount64() < until && !Get32(&s->writerPending)) Sleep(1);
        callerBlocked = WaitForSingleObject(h.caller.hProcess, 0) != WAIT_OBJECT_0;
        if (callerBlocked) { TerminateJobObject(h.callerJob, kCallerKilled); callerKilled = true; }
    }
    if (kind == 3 || kind == 4) {
        ULONGLONG stageEnd = start + 900;
        while (GetTickCount64() < stageEnd && Get32(&s->helperStage) == 0) Sleep(1);
    }
    while (GetTickCount64() < deadline && !Get32(&s->apiReturned)) Sleep(1);
    if (InterlockedCompareExchange(&s->decision, 1, 0) == 0) Put64(&s->decisionTick, (LONG64)GetTickCount64());
    ULONGLONG decisionObserved = GetTickCount64();
    if (!callerKilled && !Get32(&s->apiReturned)) {
        callerBlocked = WaitForSingleObject(h.caller.hProcess, 0) != WAIT_OBJECT_0;
        if (callerBlocked) { TerminateJobObject(h.callerJob, kCallerKilled); callerKilled = true; }
    }
    if (kind == 3 || kind == 4) {
        DWORD before = 999; JobActive(h.workerJob, before);
        workerKilled = TerminateJobObject(h.workerJob, kWorkerKilled) != FALSE;
        DWORD after = 999; bool workerEmpty = WaitJobEmpty(h.workerJob, 2000, after);
        WaitForSingleObject(h.worker.hProcess, 2000);
        DWORD wx = STILL_ACTIVE; GetExitCodeProcess(h.worker.hProcess, &wx);
        LONG64 callerReturnTick = Get64(&s->apiReturnTick);
        bool callerByD = Get32(&s->apiReturned) && callerReturnTick <= (LONG64)deadline;
        LONG64 callerLateMs = callerReturnTick > (LONG64)deadline ? callerReturnTick - (LONG64)deadline : 0;
        std::ostringstream o;
        o << "{\"mode\":\"" << Narrow(mode) << "\",\"status\":\""
          << (callerByD ? "UNKNOWN" : (Get32(&s->apiReturned) ? "CALLER_RETURN_LATE" : "CALLER_RETURN_MISSING")) << "\",\"request_budget_ms\":" << kBudgetMs
          << ",\"caller_api_returned\":" << (Get32(&s->apiReturned) ? "true":"false")
          << ",\"caller_api_return_tick_ms\":" << callerReturnTick
          << ",\"caller_api_return_by_D\":" << (callerByD ? "true":"false")
          << ",\"caller_return_lateness_ms\":" << callerLateMs
          << ",\"caller_decision_observed_tick_ms\":" << decisionObserved
          << ",\"deadline_tick_ms\":" << deadline << ",\"helper_stage\":" << Get32(&s->helperStage)
          << ",\"worker_job_active_before_kill\":" << before << ",\"worker_job_terminated\":" << (workerKilled ? "true":"false")
          << ",\"worker_job_active_after\":" << after << ",\"worker_job_empty\":" << (workerEmpty ? "true":"false")
          << ",\"worker_exit\":" << wx << ",\"worker_controls_preowned\":true}";
        WriteLine(o.str());
    } else {
        LONG pendingAtTerminal = Get32(&s->writerPending);
        bool brokerAlive = WaitForSingleObject(h.broker.hProcess, 0) == WAIT_TIMEOUT;
        if (mode == L"caller-death" && !callerKilled && !Get32(&s->apiReturned)) {
            callerBlocked = WaitForSingleObject(h.caller.hProcess, 0) != WAIT_OBJECT_0;
            if (callerBlocked) { TerminateJobObject(h.callerJob, kCallerKilled); callerKilled = true; }
        }
        if (mode == L"p05" && Get32(&s->apiReturned)) Sleep(100); // Deliberately observe ownership after API return.
        bool pendingAfterReturn = Get32(&s->writerPending) != 0;
        Put32(&s->cancelRequested, 1);
        ULONGLONG drainEnd = GetTickCount64() + 2500;
        while (GetTickCount64() < drainEnd && !Get32(&s->writerDone)) Sleep(1);
        LONG writerDone = Get32(&s->writerDone);
        DWORD callerActive = 999, brokerActive = 999;
        bool callerEmpty = WaitJobEmpty(h.callerJob, 1500, callerActive);
        DWORD callerExit = STILL_ACTIVE; WaitForSingleObject(h.caller.hProcess, 1500); GetExitCodeProcess(h.caller.hProcess, &callerExit);
        bool callerExact = callerExit != STILL_ACTIVE && callerEmpty;
        Put32(&s->shutdown, 1);
        DWORD brokerExit = STILL_ACTIVE; WaitForSingleObject(h.broker.hProcess, 2500); GetExitCodeProcess(h.broker.hProcess, &brokerExit);
        bool brokerEmpty = WaitJobEmpty(h.brokerJob, 1500, brokerActive);
        bool workerEmpty = WaitJobEmpty(h.workerJob, 1500, ja);
        DWORD workerExit = STILL_ACTIVE; WaitForSingleObject(h.worker.hProcess, 1500); GetExitCodeProcess(h.worker.hProcess, &workerExit);
        LONG64 callerReturnTick = Get64(&s->apiReturnTick);
        bool callerByD = Get32(&s->apiReturned) && callerReturnTick <= (LONG64)deadline;
        LONG64 callerLateMs = callerReturnTick > (LONG64)deadline ? callerReturnTick - (LONG64)deadline : 0;
        std::ostringstream o;
        o << "{\"mode\":\"" << Narrow(mode) << "\",\"status\":\""
          << (callerByD ? "UNKNOWN" : (Get32(&s->apiReturned) ? "CALLER_RETURN_LATE" : "CALLER_RETURN_MISSING")) << "\",\"request_budget_ms\":" << kBudgetMs
          << ",\"request_start_tick_ms\":" << start << ",\"deadline_tick_ms\":" << deadline
          << ",\"decision_tick_ms\":" << Get64(&s->decisionTick) << ",\"supervisor_decision_observed_tick_ms\":" << decisionObserved
          << ",\"caller_api_returned\":" << (Get32(&s->apiReturned) ? "true":"false") << ",\"caller_api_return_tick_ms\":" << callerReturnTick
          << ",\"caller_api_return_by_D\":" << (callerByD ? "true":"false") << ",\"caller_return_lateness_ms\":" << callerLateMs
          << ",\"caller_killed\":" << (callerKilled ? "true":"false") << ",\"caller_blocked_before_kill\":" << (callerBlocked ? "true":"false")
          << ",\"caller_terminal_event\":\"" << (callerKilled ? "process-death" : "api-return") << "\""
          << ",\"writer_pending_at_caller_terminal_event\":" << (pendingAtTerminal ? "true":"false")
          << ",\"writer_pending_after_api_return\":" << (pendingAfterReturn ? "true":"false")
          << ",\"writer_submitted\":" << (Get32(&s->writerSubmitted) ? "true":"false")
          << ",\"writer_done\":" << (writerDone ? "true":"false") << ",\"writer_error\":" << Get32(&s->writerError)
          << ",\"cancel_issued\":" << (Get32(&s->writerCancelIssued) ? "true":"false")
          << ",\"cancel_error\":" << Get32(&s->writerCancelError)
          << ",\"writer_event_observed\":" << (Get32(&s->writerEventObserved) ? "true":"false")
          << ",\"writer_completion_consume_hold_ms\":" << Get32(&s->writerCompletionHoldMs)
          << ",\"writer_completion_tick_ms\":" << Get64(&s->writerCompletionTick)
          << ",\"caller_dead_seen_by_broker\":" << (Get32(&s->callerDeadSeen) ? "true":"false")
          << ",\"broker_alive_after_caller_death_or_return\":" << (brokerAlive ? "true":"false")
          << ",\"caller_exit\":" << callerExit << ",\"caller_job_active_after\":" << callerActive
          << ",\"caller_exact_exit_and_job_empty\":" << (callerExact ? "true":"false")
          << ",\"broker_exit\":" << brokerExit << ",\"broker_job_active_after\":" << brokerActive
          << ",\"broker_exact_exit_and_job_empty\":" << (brokerExit != STILL_ACTIVE && brokerEmpty ? "true":"false")
          << ",\"worker_exit\":" << workerExit << ",\"worker_job_active_after\":" << ja
          << ",\"worker_exact_exit_and_job_empty\":" << (workerExit != STILL_ACTIVE && workerEmpty ? "true":"false")
          << ",\"pending_context_preowned_before_ready\":true,\"reaper_process_separate_from_caller\":true}";
        WriteLine(o.str());
    }

    if (mode != L"popen-before" && mode != L"popen-after") {
        if (!Get32(&s->shutdown)) Put32(&s->shutdown, 1);
        WaitForSingleObject(h.worker.hProcess, 1000);
        if (JobActive(h.workerJob, ja) && ja != 0) TerminateJobObject(h.workerJob, kWorkerKilled);
        WaitJobEmpty(h.workerJob, 1000, ja);
    }
    if (h.serverPipe) CloseHandle(h.serverPipe);
    if (s) UnmapViewOfFile(s);
    Close(h.mapping); Close(h.go); Close(h.helperReady); Close(h.callerReady); Close(h.brokerReady);
    Close(h.callerJob); Close(h.brokerJob); Close(h.workerJob);
    Close(h.caller.hThread); Close(h.caller.hProcess); Close(h.broker.hThread); Close(h.broker.hProcess);
    Close(h.worker.hThread); Close(h.worker.hProcess);
    return 0;
}

int OuterRun(const std::wstring& mode, DWORD parentPid, HANDLE go, const std::wstring& python) {
    HANDLE rootJob = NewJob();
    if (!rootJob) { WriteLine("R9_OUTER_SETUP_FAILED job"); return 80; }
    HANDLE parent = OpenProcess(PROCESS_DUP_HANDLE, FALSE, parentPid), external = nullptr;
    if (!parent || !DuplicateHandle(GetCurrentProcess(), rootJob, parent, &external,
            JOB_OBJECT_QUERY | JOB_OBJECT_TERMINATE | SYNCHRONIZE, FALSE, 0)) {
        WriteLine("R9_OUTER_SETUP_FAILED duplicate"); return 81;
    }
    CloseHandle(parent);
    std::ostringstream marker; marker << "R9_OUTER_JOB_CONTROL_READY launcher_pid=" << GetCurrentProcessId()
        << " external_job_handle=" << (unsigned long long)(uintptr_t)external;
    WriteLine(marker.str());
    if (!AssignProcessToJobObject(rootJob, GetCurrentProcess())) { WriteLine("R9_OUTER_SETUP_FAILED assign_self"); return 82; }
    SECURITY_ATTRIBUTES sa{ sizeof(sa), nullptr, TRUE };
    HANDLE readPipe = nullptr, writePipe = nullptr;
    if (!CreatePipe(&readPipe, &writePipe, &sa, 4096)) return 83;
    SetHandleInformation(readPipe, HANDLE_FLAG_INHERIT, 0);
    std::wstring exe = ExePath();
    std::wstring cmd = Quote(exe) + L" --supervisor " + mode + L" " + HandleArg(go) + L" " + Quote(python);
    PROCESS_INFORMATION child{};
    if (!SpawnSuspended(cmd, { writePipe, go }, nullptr, child, writePipe)) return 84;
    CloseHandle(writePipe);
    if (Resume(child) == false) return 85;
    std::ostringstream ready; ready << "R9_OUTER_JOB_READY child_pid=" << child.dwProcessId
        << " external_job_handle=" << (unsigned long long)(uintptr_t)external;
    WriteLine(ready.str());
    char b[4096];
    for (;;) {
        DWORD n = 0;
        if (!ReadFile(readPipe, b, sizeof(b), &n, nullptr) || n == 0) break;
        DWORD wrote = 0; WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), b, n, &wrote, nullptr);
    }
    WaitForSingleObject(child.hProcess, 5000);
    DWORD exitCode = STILL_ACTIVE; GetExitCodeProcess(child.hProcess, &exitCode);
    CloseHandle(readPipe); ClosePi(child); CloseHandle(rootJob);
    return (int)exitCode;
}

int wmain(int argc, wchar_t** argv) {
    if (argc >= 2 && std::wstring(argv[1]) == L"--caller") return CallerMain(argc, argv);
    if (argc >= 2 && std::wstring(argv[1]) == L"--broker") return BrokerMain(argc, argv);
    if (argc >= 5 && std::wstring(argv[1]) == L"--supervisor") return SupervisorMain(argv[2], ParseHandle(argv[3]), argv[4]);
    if (argc >= 6 && std::wstring(argv[1]) == L"--outer-run") return OuterRun(argv[2], (DWORD)_wtoi(argv[3]), ParseHandle(argv[4]), argv[5]);
    return 1;
}
