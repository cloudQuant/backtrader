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

enum TicketSlot : LONG { SLOT_FREE = 0, SLOT_ADMITTED = 1, SLOT_POISONED = 2 };
enum TicketState : LONG { TICKET_EMPTY = 0, TICKET_PUBLISHED = 1, TICKET_RUNNING = 2, TICKET_UNKNOWN = 3, TICKET_SUCCESS = 4 };
enum SubmitResult : LONG { SUBMIT_ACCEPTED = 0, SUBMIT_BUSY = 1, SUBMIT_POISONED = 2, SUBMIT_NOT_READY = 3 };

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
    // R10 one-slot asynchronous ticket protocol. These are appended so the
    // frozen R9 helper's prefix offsets remain valid in this isolated port.
    volatile LONG admissionReady;
    volatile LONG slotState;
    volatile LONG ticketState;
    volatile LONG preReadySubmitResult;
    volatile LONG submitResult;
    volatile LONG busySubmitResult;
    volatile LONG poisonSubmitResult;
    volatile LONG lateSuccessAttempted;
    volatile LONG lateSuccessCasPrevious;
    volatile LONG lateSuccessBlocked;
    volatile LONG callerPollFinalState;
    volatile LONG callerPollCalls;
    volatile LONG reaperUnknownTick;
    volatile LONG writerPendingAtUnknown;
    volatile LONG supervisorPoisonResult;
    volatile LONG64 submitStartQpc;
    volatile LONG64 submitReturnQpc;
    volatile LONG64 ticketUnknownTick;
    volatile LONG64 lateAttemptTick;
    volatile LONG64 ticketId;
    volatile LONG64 callerTicketId;
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
LONG64 Get64(const volatile LONG64* p) { return InterlockedCompareExchange64(const_cast<volatile LONG64*>(p), 0, 0); }
LONG64 Qpc() { LARGE_INTEGER x{}; QueryPerformanceCounter(&x); return x.QuadPart; }
LONG ReadTicket(const Shared* s) { return InterlockedCompareExchange(const_cast<volatile LONG*>(&s->ticketState), 0, 0); }
LONG SubmitTicket(Shared* s, LONG64* ticketOut = nullptr) {
    if (Get32(&s->admissionReady) == 0) return SUBMIT_NOT_READY;
    LONG previous = InterlockedCompareExchange(&s->slotState, SLOT_ADMITTED, SLOT_FREE);
    if (previous != SLOT_FREE) return previous == SLOT_POISONED ? SUBMIT_POISONED : SUBMIT_BUSY;
    // SLOT_ADMITTED is the sole atomic publication. Request kind and D were
    // preconfigured before READY, so no post-CAS caller stores can race D.
    if (ticketOut) *ticketOut = Get64(&s->ticketId);
    return SUBMIT_ACCEPTED;
}
LONG PollTicket(const Shared* s, LONG64 ticket) {
    if (ticket == 0 || ticket != Get64(&s->ticketId)) return -1;
    return ReadTicket(s); // A read-only atomic load; no ticket transition occurs here.
}
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
    std::wstring name = L"\\\\.\\pipe\\r10-inert-" + std::to_wstring(GetCurrentProcessId()) + L"-" + std::to_wstring(GetTickCount64());
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
    // A real request API rejects before READY and does not wait for warmup.
    Put32(&s->preReadySubmitResult, SubmitTicket(s));
    SetEvent(ready);
    while (!Get32(&s->go)) YieldProcessor();
    Put64(&s->submitStartQpc, Qpc());
    LONG64 ticket = 0;
    LONG result = SubmitTicket(s, &ticket); // One CAS + fixed shared-memory publication; no waits or I/O.
    Put64(&s->submitReturnQpc, Qpc());
    Put32(&s->submitResult, result);
    Put64(&s->callerTicketId, ticket);
    Put64(&s->apiReturnTick, (LONG64)GetTickCount64());
    Put32(&s->apiReturned, 1);
    // One mailbox slot: concurrent/duplicate intake must fail immediately.
    Put32(&s->busySubmitResult, SubmitTicket(s));
    if (result == SUBMIT_ACCEPTED) {
        LONG observed = TICKET_EMPTY;
        LONG64 deadline = Get64(&s->deadlineTick);
        while ((LONG64)GetTickCount64() < deadline + 200) {
            observed = PollTicket(s, ticket); // Poll is read-only.
            InterlockedIncrement(&s->callerPollCalls);
            if (observed == TICKET_UNKNOWN || observed == TICKET_SUCCESS) break;
            Sleep(1); // Test client cadence only; SubmitTicket itself never waits.
        }
        Put32(&s->callerPollFinalState, PollTicket(s, ticket));
        Put32(&s->poisonSubmitResult, SubmitTicket(s));
    }
    UnmapViewOfFile(s);
    return 0;
}

void ReaperMarkUnknown(Shared* s) {
    LONG observed = ReadTicket(s);
    while (observed == TICKET_EMPTY || observed == TICKET_PUBLISHED || observed == TICKET_RUNNING) {
        LONG previous = InterlockedCompareExchange(&s->ticketState, TICKET_UNKNOWN, observed);
        if (previous == observed) {
            LONG64 now = (LONG64)GetTickCount64();
            Put64(&s->ticketUnknownTick, now);
            Put32(&s->decision, 1);
            Put64(&s->decisionTick, now);
            Put32(&s->writerPendingAtUnknown, Get32(&s->writerPending));
            InterlockedExchange(&s->slotState, SLOT_POISONED);
            Put32(&s->cancelRequested, 1);
            return;
        }
        observed = previous;
    }
    if (observed == TICKET_UNKNOWN) InterlockedExchange(&s->slotState, SLOT_POISONED);
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
    Put32(&s->brokerReady, 1); // OVERLAPPED, event and 2 MiB buffer pre-exist READY.
    SetEvent(ready);
    bool ticketObserved = false, writerStarted = false, lateAttempted = false;
    for (;;) {
        LONG slot = Get32(&s->slotState);
        LONG kind = Get32(&s->requestKind); // Fixed before READY; caller publishes only slotState.
        ULONGLONG now = GetTickCount64();
        LONG64 deadline = Get64(&s->deadlineTick);
        if (slot == SLOT_ADMITTED && !ticketObserved) {
            if ((LONG64)now >= deadline) {
                ReaperMarkUnknown(s);
            } else {
                LONG previous = InterlockedCompareExchange(&s->ticketState, TICKET_PUBLISHED, TICKET_EMPTY);
                if (previous == TICKET_EMPTY) {
                    Put32(&s->requestSubmitted, 1); // Reaper observes atomic mailbox admission.
                    previous = InterlockedCompareExchange(&s->ticketState, TICKET_RUNNING, TICKET_PUBLISHED);
                    if (previous == TICKET_PUBLISHED) {
                        ticketObserved = true;
                        if (kind == 1 || kind == 2) {
                            writerStarted = true;
                            Put32(&s->writerStarted, 1);
                            SetEvent(begin);
                        }
                    }
                }
            }
        }
        if ((LONG64)now >= deadline && Get32(&s->slotState) == SLOT_ADMITTED)
            ReaperMarkUnknown(s);
        if (Get32(&s->requestSubmitted) && !Get32(&s->callerDeadSeen) &&
            WaitForSingleObject(callerProcess, 0) == WAIT_OBJECT_0)
            Put32(&s->callerDeadSeen, 1);
        if (Get32(&s->cancelRequested)) SetEvent(cancel);
        if (ReadTicket(s) == TICKET_UNKNOWN && !lateAttempted && (LONG64)now >= deadline + 150) {
            LONG previous = InterlockedCompareExchange(&s->ticketState, TICKET_SUCCESS, TICKET_RUNNING);
            Put32(&s->lateSuccessCasPrevious, previous);
            Put32(&s->lateSuccessBlocked, previous == TICKET_UNKNOWN && ReadTicket(s) == TICKET_UNKNOWN);
            Put64(&s->lateAttemptTick, (LONG64)now);
            Put32(&s->lateSuccessAttempted, 1);
            lateAttempted = true;
        }
        if (Get32(&s->shutdown)) {
            if (!writerStarted) SetEvent(stop);
            else if (!Get32(&s->writerDone)) SetEvent(cancel);
            if (!writerStarted || Get32(&s->writerDone)) break;
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
    script = script.substr(0, slash + 1) + L"r10_sacrificial_popen.py";
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
    LONG64 ticketId = (((LONG64)GetCurrentProcessId()) << 32) ^ ((LONG64)GetTickCount64() & 0xffffffffLL);
    Put64(&s->ticketId, ticketId ? ticketId : 1);
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
    CloseHandle(h.clientPipe); h.clientPipe = nullptr; // Broker owns the connected client pipe before READY.

    LONG kind = mode == L"caller-death" ? 2 : mode == L"popen-before" ? 3 : mode == L"popen-after" ? 4 : 1;
    Put32(&s->requestKind, kind); // The one-shot slot's action is fixed before it is admitted.
    DWORD workerActive = 999, brokerActive = 999, callerActive = 999;
    JobActive(h.workerJob, workerActive); JobActive(h.brokerJob, brokerActive); JobActive(h.callerJob, callerActive);
    std::ostringstream ready;
    ready << "R10_READY supervisor_pid=" << GetCurrentProcessId() << " caller_pid=" << h.caller.dwProcessId
          << " broker_pid=" << h.broker.dwProcessId << " worker_pid=" << h.worker.dwProcessId
          << " caller_job_active=" << callerActive << " broker_job_active=" << brokerActive << " worker_job_active=" << workerActive
          << " named_pipe_connected=1 broker_io_context_preowned=1 worker_job_preowned=1 caller_job_preowned=1"
          << " slot_capacity=1 admission_ready=0 prewarmed_handles=1";
    WriteLine(ready.str());

    if (WaitForSingleObject(go, 15000) != WAIT_OBJECT_0) {
        WriteLine("{\"setup\":\"go_not_received\"}"); return 10;
    }
    ULONGLONG start = GetTickCount64(), deadline = start + kBudgetMs;
    Put64(&s->requestStartTick, (LONG64)start);
    Put64(&s->deadlineTick, (LONG64)deadline);
    Put32(&s->admissionReady, 1);
    Put32(&s->go, 1);
    std::ostringstream barrier;
    barrier << "R10_REQUEST_BARRIER mode=" << Narrow(mode) << " request_start_tick_ms=" << start
            << " deadline_tick_ms=" << deadline << " budget_ms=" << kBudgetMs
            << " caller_pid=" << h.caller.dwProcessId << " broker_pid=" << h.broker.dwProcessId
            << " worker_pid=" << h.worker.dwProcessId << " submit_is_single_atomic_slot_cas=1";
    WriteLine(barrier.str());

    if (mode == L"outer-job") {
        ULONGLONG pendingWait = GetTickCount64() + 1000;
        while (GetTickCount64() < pendingWait && !Get32(&s->writerPending)) Sleep(1);
        std::ostringstream pending;
        pending << "R10_PENDING_IO pending=" << Get32(&s->writerPending) << " broker_pid=" << h.broker.dwProcessId
                << " caller_pid=" << h.caller.dwProcessId << " slot_state=" << Get32(&s->slotState);
        WriteLine(pending.str());
        Sleep(INFINITE);
        return 0;
    }

    bool callerKilled = false, workerKilled = false, callerBlocked = false, brokerAliveAtCallerTerminal = false;
    LONG pendingAtCallerDeath = 0;
    if (kind == 2) {
        ULONGLONG until = start + 350;
        while (GetTickCount64() < until && !Get32(&s->writerPending)) Sleep(1);
        pendingAtCallerDeath = Get32(&s->writerPending);
        callerBlocked = WaitForSingleObject(h.caller.hProcess, 0) != WAIT_OBJECT_0;
        if (callerBlocked) { TerminateJobObject(h.callerJob, kCallerKilled); callerKilled = true; }
        brokerAliveAtCallerTerminal = WaitForSingleObject(h.broker.hProcess, 0) == WAIT_TIMEOUT;
    }
    if (kind == 3 || kind == 4) {
        ULONGLONG stageEnd = start + 1000;
        while (GetTickCount64() < stageEnd && Get32(&s->helperStage) == 0) Sleep(1);
    }

    ULONGLONG observeEnd = deadline + 3000;
    while (GetTickCount64() < observeEnd && ReadTicket(s) != TICKET_UNKNOWN && ReadTicket(s) != TICKET_SUCCESS) Sleep(1);
    ULONGLONG supervisorObserved = GetTickCount64();
    LONG stateAtD = ReadTicket(s);
    DWORD workerBefore = 999, workerAfter = 999;
    bool workerEmpty = false;
    DWORD workerExit = STILL_ACTIVE;
    if (kind == 3 || kind == 4) {
        JobActive(h.workerJob, workerBefore);
        workerKilled = TerminateJobObject(h.workerJob, kWorkerKilled) != FALSE;
        workerEmpty = WaitJobEmpty(h.workerJob, 2500, workerAfter);
        WaitForSingleObject(h.worker.hProcess, 2500);
        GetExitCodeProcess(h.worker.hProcess, &workerExit);
    }

    ULONGLONG settleEnd = deadline + 1200;
    while (GetTickCount64() < settleEnd && (!Get32(&s->lateSuccessAttempted) ||
           ((kind == 1 || kind == 2) && !Get32(&s->writerDone)))) Sleep(1);
    if (stateAtD == TICKET_UNKNOWN && Get32(&s->poisonSubmitResult) == SUBMIT_ACCEPTED && !callerKilled)
        Put32(&s->supervisorPoisonResult, SubmitTicket(s));
    if (stateAtD == TICKET_UNKNOWN && Get32(&s->supervisorPoisonResult) == 0)
        Put32(&s->supervisorPoisonResult, SubmitTicket(s));

    if (!callerKilled) {
        DWORD callerWait = WaitForSingleObject(h.caller.hProcess, 1500);
        if (callerWait != WAIT_OBJECT_0) {
            callerBlocked = true;
            TerminateJobObject(h.callerJob, kCallerKilled);
            callerKilled = true;
        }
    }
    if (kind != 3 && kind != 4) {
        Put32(&s->shutdown, 1);
        WaitForSingleObject(h.worker.hProcess, 1500);
        if (JobActive(h.workerJob, workerAfter) && workerAfter != 0) {
            TerminateJobObject(h.workerJob, kWorkerKilled);
            workerKilled = true;
        }
        workerEmpty = WaitJobEmpty(h.workerJob, 2000, workerAfter);
        GetExitCodeProcess(h.worker.hProcess, &workerExit);
    }
    Put32(&s->shutdown, 1);
    DWORD callerActiveAfter = 999, brokerActiveAfter = 999, workerActiveAfter = 999;
    bool callerEmpty = WaitJobEmpty(h.callerJob, 1500, callerActiveAfter);
    bool brokerEmpty = false;
    DWORD brokerExit = STILL_ACTIVE;
    WaitForSingleObject(h.broker.hProcess, 3000);
    GetExitCodeProcess(h.broker.hProcess, &brokerExit);
    brokerEmpty = WaitJobEmpty(h.brokerJob, 1500, brokerActiveAfter);
    if (workerAfter == 999) workerEmpty = WaitJobEmpty(h.workerJob, 1500, workerActiveAfter);
    DWORD callerExit = STILL_ACTIVE;
    GetExitCodeProcess(h.caller.hProcess, &callerExit);
    if (callerKilled) WaitJobEmpty(h.callerJob, 1000, callerActiveAfter);
    if (kind != 2) brokerAliveAtCallerTerminal = true;

    LARGE_INTEGER qpf{}; QueryPerformanceFrequency(&qpf);
    LONG64 qpcStart = Get64(&s->submitStartQpc), qpcReturn = Get64(&s->submitReturnQpc);
    double submitUs = (qpf.QuadPart && qpcReturn >= qpcStart) ?
        (double)(qpcReturn - qpcStart) * 1000000.0 / (double)qpf.QuadPart : -1.0;
    LONG64 unknownTick = Get64(&s->ticketUnknownTick);
    LONG64 unknownLateMs = unknownTick > (LONG64)deadline ? unknownTick - (LONG64)deadline : 0;
    LONG poisonResult = Get32(&s->poisonSubmitResult);
    if (poisonResult != SUBMIT_POISONED) poisonResult = Get32(&s->supervisorPoisonResult);
    std::ostringstream o;
    o << "{\"mode\":\"" << Narrow(mode) << "\",\"status\":\""
      << (ReadTicket(s) == TICKET_UNKNOWN ? "UNKNOWN" : (ReadTicket(s) == TICKET_SUCCESS ? "SUCCESS" : "INCOMPLETE"))
      << "\",\"request_budget_ms\":" << kBudgetMs << ",\"request_start_tick_ms\":" << start
      << ",\"deadline_tick_ms\":" << deadline << ",\"ticket_state_final\":" << ReadTicket(s)
      << ",\"ticket_unknown_tick_ms\":" << unknownTick << ",\"reaper_unknown_lateness_ms\":" << unknownLateMs
      << ",\"caller_pre_ready_submit_result\":" << Get32(&s->preReadySubmitResult)
      << ",\"caller_submit_result\":" << Get32(&s->submitResult)
      << ",\"prewarmed_ticket_id\":" << Get64(&s->ticketId)
      << ",\"caller_ticket_id\":" << Get64(&s->callerTicketId)
      << ",\"caller_submit_elapsed_us\":" << submitUs
      << ",\"caller_submit_return_tick_ms\":" << Get64(&s->apiReturnTick)
      << ",\"caller_submit_returned\":" << (Get32(&s->apiReturned) ? "true":"false")
      << ",\"caller_submit_return_before_D\":" << (Get64(&s->apiReturnTick) && Get64(&s->apiReturnTick) < (LONG64)deadline ? "true":"false")
      << ",\"second_submit_busy_result\":" << Get32(&s->busySubmitResult)
      << ",\"post_unknown_submit_result\":" << poisonResult
      << ",\"caller_poll_final_state\":" << Get32(&s->callerPollFinalState)
      << ",\"caller_poll_calls\":" << Get32(&s->callerPollCalls)
      << ",\"slot_state_final\":" << Get32(&s->slotState)
      << ",\"late_success_attempted\":" << (Get32(&s->lateSuccessAttempted) ? "true":"false")
      << ",\"late_success_cas_previous_state\":" << Get32(&s->lateSuccessCasPrevious)
      << ",\"late_success_blocked_by_unknown\":" << (Get32(&s->lateSuccessBlocked) ? "true":"false")
      << ",\"late_attempt_tick_ms\":" << Get64(&s->lateAttemptTick)
      << ",\"writer_submitted\":" << (Get32(&s->writerSubmitted) ? "true":"false")
      << ",\"writer_pending_at_unknown\":" << (Get32(&s->writerPendingAtUnknown) ? "true":"false")
      << ",\"writer_pending_final\":" << (Get32(&s->writerPending) ? "true":"false")
      << ",\"writer_done\":" << (Get32(&s->writerDone) ? "true":"false")
      << ",\"writer_error\":" << Get32(&s->writerError)
      << ",\"writer_cancel_issued\":" << (Get32(&s->writerCancelIssued) ? "true":"false")
      << ",\"writer_event_observed\":" << (Get32(&s->writerEventObserved) ? "true":"false")
      << ",\"writer_completion_consume_hold_ms\":" << Get32(&s->writerCompletionHoldMs)
      << ",\"writer_completion_tick_ms\":" << Get64(&s->writerCompletionTick)
      << ",\"caller_killed\":" << (callerKilled ? "true":"false")
      << ",\"caller_pending_at_kill\":" << (pendingAtCallerDeath ? "true":"false")
      << ",\"caller_dead_seen_by_broker\":" << (Get32(&s->callerDeadSeen) ? "true":"false")
      << ",\"caller_exit\":" << callerExit << ",\"caller_job_active_after\":" << callerActiveAfter
      << ",\"caller_job_empty\":" << (callerEmpty ? "true":"false")
      << ",\"broker_alive_at_caller_terminal\":" << (brokerAliveAtCallerTerminal ? "true":"false")
      << ",\"broker_exit\":" << brokerExit << ",\"broker_job_active_after\":" << brokerActiveAfter
      << ",\"broker_exact_exit_and_job_empty\":" << (brokerExit != STILL_ACTIVE && brokerEmpty ? "true":"false")
      << ",\"helper_stage\":" << Get32(&s->helperStage)
      << ",\"worker_job_active_before_kill\":" << workerBefore
      << ",\"worker_job_terminated\":" << (workerKilled ? "true":"false")
      << ",\"worker_job_active_after\":" << workerAfter
      << ",\"worker_job_empty\":" << (workerEmpty ? "true":"false")
      << ",\"worker_exit\":" << workerExit
      << ",\"prewarmed_io_owner\":true,\"ticket_reaper_is_separate_process\":true"
      << ",\"supervisor_observed_tick_ms\":" << supervisorObserved << "}";
    WriteLine(o.str());

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
    if (!rootJob) { WriteLine("R10_OUTER_SETUP_FAILED job"); return 80; }
    HANDLE parent = OpenProcess(PROCESS_DUP_HANDLE, FALSE, parentPid), external = nullptr;
    if (!parent || !DuplicateHandle(GetCurrentProcess(), rootJob, parent, &external,
            JOB_OBJECT_QUERY | JOB_OBJECT_TERMINATE | SYNCHRONIZE, FALSE, 0)) {
        WriteLine("R10_OUTER_SETUP_FAILED duplicate"); return 81;
    }
    CloseHandle(parent);
    std::ostringstream marker; marker << "R10_OUTER_JOB_CONTROL_READY launcher_pid=" << GetCurrentProcessId()
        << " external_job_handle=" << (unsigned long long)(uintptr_t)external;
    WriteLine(marker.str());
    if (!AssignProcessToJobObject(rootJob, GetCurrentProcess())) { WriteLine("R10_OUTER_SETUP_FAILED assign_self"); return 82; }
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
    std::ostringstream ready; ready << "R10_OUTER_JOB_READY child_pid=" << child.dwProcessId
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
