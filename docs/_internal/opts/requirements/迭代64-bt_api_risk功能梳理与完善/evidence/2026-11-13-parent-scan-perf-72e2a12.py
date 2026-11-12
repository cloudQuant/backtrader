"""Bounded iteration 64 local diagnostic: fake ports and hypothetical setup grant."""
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import bt_api_base
import bt_api_risk
from bt_api_risk.pretrade.engine import PretradeEngine
from test_pretrade_support import Harness, base_policy, caller, make_parent, make_view

N = 20
WARMUP = 3
CHILDREN_PER_PARENT = 3

def stats(values):
    values = sorted(values)
    def pct(q): return round(values[max(0, math.ceil(q * len(values)) - 1)], 3)
    return {"n": len(values), "min_ms": round(values[0], 3), "p50_ms": pct(.5),
            "p95_ms": pct(.95), "p99_ms": pct(.99), "max_ms": round(values[-1], 3),
            "mean_ms": round(statistics.fmean(values), 3)}

def checked(result, outcome, state=None):
    if result.outcome != outcome or (state is not None and result.state != state):
        raise RuntimeError(f"unexpected synthetic outcome {result.outcome} {result.state} {result.code}")
    return result

def run_case(root, count):
    h = Harness(root / f"case-{count}.sqlite")
    started = time.perf_counter()
    try:
        h.publish(base_policy(self_trade={"enabled": False}, closable_check={"enabled": False}))
        h.verify_stream()
        execution = caller("strat-a", role="execution", principal="exec", run="exec-run")
        newer = caller("strat-a", role="execution", principal="exec", run="exec-run-2")
        with patch.object(PretradeEngine, "_parent_contract_verified", staticmethod(lambda: True)):
            for i in range(count):
                parent = f"parent-{i:03d}"
                checked(h.engine.parent_reserve(execution, make_parent(parent_ref=parent, total="4")),
                        "RESERVED", "ACTIVE")
                for j in range(CHILDREN_PER_PARENT):
                    child = f"child-{i:03d}-{j}"
                    v = make_view(key=child, origin="execution", parent_ref=parent, child_id=child)
                    checked(h.reserve(v, execution), "RESERVED", "RESERVED")
                if i % 2:
                    child = f"frozen-attempt-{i:03d}"
                    v = make_view(key=child, origin="execution", parent_ref=parent, child_id=child)
                    result = h.reserve(v, newer)
                    if result.code != "risk_parent_frozen":
                        raise RuntimeError(f"expected frozen refusal, got {result.outcome} {result.code}")
        setup_seconds = time.perf_counter() - started
        if h.engine._parent_contract_verified():
            raise RuntimeError("setup-only synthetic parent grant was not restored")
        with h.ledger.transaction() as txn:
            parent_counts = dict(txn._c.execute("SELECT state, COUNT(*) FROM risk_pretrade_parents GROUP BY state"))
            child_counts = dict(txn._c.execute("SELECT state, COUNT(*) FROM risk_pretrade_permits WHERE parent_ref IS NOT NULL GROUP BY state"))
        expected_parents = {"ACTIVE": (count + 1)//2, "FROZEN": count//2}
        if any(parent_counts.get(k, 0) != v for k,v in expected_parents.items()):
            raise RuntimeError(f"unexpected parent counts {parent_counts}")
        if child_counts.get("RESERVED", 0) != count * CHILDREN_PER_PARENT or child_counts.get("DENIED", 0) != count // 2:
            raise RuntimeError(f"unexpected child counts {child_counts}")

        def scan():
            with h.ledger.transaction() as txn:
                if not h.engine._holding_parents_consistent(txn):
                    raise RuntimeError("parent integrity check failed")

        scan_times = []
        for i in range(WARMUP + N):
            t=time.perf_counter_ns(); scan(); dt=(time.perf_counter_ns()-t)/1e6
            if i >= WARMUP: scan_times.append(dt)
        with h.ledger.transaction() as txn:
            sql=[]
            txn._c.set_trace_callback(sql.append)
            try:
                if not h.engine._holding_parents_consistent(txn):
                    raise RuntimeError("trace scan failed")
            finally:
                txn._c.set_trace_callback(None)
        query_counts = {"holding_parent_selects": sum("FROM risk_pretrade_parents" in q and "SELECT" in q.upper() for q in sql),
                        "child_selects": sum("FROM risk_pretrade_permits" in q and "parent_ref=" in q for q in sql)}

        original = PretradeEngine._holding_parents_consistent
        calls=[]
        def counted(self, txn):
            calls.append(1)
            return original(self, txn)
        with patch.object(PretradeEngine, "_holding_parents_consistent", counted):
            v=make_view(key=f"trace-reserve-{count}")
            reserved=checked(h.reserve(v), "RESERVED", "RESERVED")
            reserve_scans=len(calls); calls.clear()
            checked(h.dispatch(v, reserved), "DISPATCHED", "DISPATCHED")
            dispatch_scans=len(calls)

        reserve_times=[]
        for i in range(WARMUP+N):
            v=make_view(key=f"sample-reserve-{count}-{i}")
            t=time.perf_counter_ns(); checked(h.reserve(v), "RESERVED", "RESERVED"); dt=(time.perf_counter_ns()-t)/1e6
            if i >= WARMUP: reserve_times.append(dt)
        identity=make_view(key=f"idempotent-{count}")
        checked(h.reserve(identity), "RESERVED", "RESERVED")
        retry_times=[]
        for i in range(WARMUP+N):
            t=time.perf_counter_ns(); checked(h.reserve(identity), "RESERVED", "RESERVED"); dt=(time.perf_counter_ns()-t)/1e6
            if i >= WARMUP: retry_times.append(dt)
        prepared=[]
        for i in range(WARMUP+N):
            v=make_view(key=f"dispatch-{count}-{i}")
            prepared.append((v,checked(h.reserve(v), "RESERVED", "RESERVED")))
        dispatch_times=[]
        for i,(v,permit) in enumerate(prepared):
            t=time.perf_counter_ns(); checked(h.dispatch(v,permit), "DISPATCHED", "DISPATCHED"); dt=(time.perf_counter_ns()-t)/1e6
            if i >= WARMUP: dispatch_times.append(dt)
        return {"parents": count, "parent_states": parent_counts, "child_states": child_counts,
                "children_per_parent": CHILDREN_PER_PARENT, "setup_seconds": round(setup_seconds,3),
                "one_scan_query_counts": query_counts, "integrity_scans_per_reserve": reserve_scans,
                "integrity_scans_per_dispatch": dispatch_scans, "scan_transaction": stats(scan_times),
                "ordinary_new_reserve_fake_gateway": stats(reserve_times),
                "ordinary_idempotent_reserve": stats(retry_times),
                "ordinary_dispatch_fake_gateway": stats(dispatch_times)}
    finally:
        h.close()

def main():
    output=Path(sys.argv[1])
    if output.exists(): raise RuntimeError("do not overwrite evidence")
    result={"kind":"local diagnostic with fake gateway, facts, clock and setup-only assumed parent grant",
            "risk_commit":"72e2a1284fe46a37501ab74947aac546808207ae",
            "base_commit":"99d2bd381dbc750e743ff3bb1fd4291080134cc5",
            "risk_module":bt_api_risk.__file__,"base_module":bt_api_base.__file__,
            "machine":{"platform":platform.platform(),"python":platform.python_version(),"cpu_count":os.cpu_count()},
            "samples_per_metric":N,"warmups":WARMUP,
            "setup_assumption":"Only while creating historic parent/child rows, _parent_contract_verified is patched True; it is restored to production False before timed calls. No provider or account operations.",
            "percentile_method":"nearest-rank; with 20 samples p99 is max", "cases":[]}
    with tempfile.TemporaryDirectory(prefix="parent-case-",dir=output.parent) as temporary:
        for count in (0,10,100):
            case=run_case(Path(temporary),count); result["cases"].append(case)
            print(json.dumps(case,ensure_ascii=False),flush=True)
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("evidence",output,flush=True)

if __name__ == "__main__": main()
