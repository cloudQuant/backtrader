from __future__ import annotations
import hashlib
import json
import multiprocessing
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from account_actor_port import ActorCommandContextV1
from account_actor_server_core import (
    AccountActorIntentV1, AccountActorServerCoreV1, AccountSnapshotBundleV1,
    ActorServerError, FakeSnapshotAuthorityV1, SnapshotDomainFactV1, WriterEpochV1,
)

ACCOUNT_A = 'ctp-account-ref.v1:' + hashlib.sha256(b'g6-independent-probe-account').hexdigest()
SOURCE_ID = 'qa-fake-source'
AUTHORITY_ID = 'qa-fake-authority'
KEY = b'qa-only-known-fake-hmac-key-012345678901234567890123'

def authority():
    return FakeSnapshotAuthorityV1(authority_id=AUTHORITY_ID, source_id=SOURCE_ID, key=KEY)

def context(epoch=1, session_id='session-qa'):
    return ActorCommandContextV1(
        account_ref=ACCOUNT_A, runtime_id='qa-runtime', mode='simulation',
        config_digest=hashlib.sha256(b'qa-config').hexdigest(),
        session_id=session_id, front_id=71, native_session_id=81,
        session_generation=1, actor_epoch=epoch,
    )

def bundle(version, *, available='1000000000.00', account_ref=ACCOUNT_A, source_id=SOURCE_ID):
    payloads = {
        'funds': {'available': available, 'currency': 'CNY'},
        'orders': {'open_order_count': 0},
        'trades': {'trade_count': 0},
        'positions': {'position_count': 0},
    }
    facts = tuple(SnapshotDomainFactV1.from_payload(
        account_ref=account_ref, snapshot_version=version, source_id=source_id,
        domain=domain, payload=payloads[domain])
        for domain in ('funds','orders','trades','positions'))
    return AccountSnapshotBundleV1(account_ref, version, source_id, facts)

def intent(epoch=1, ident='qa-intent'):
    return AccountActorIntentV1.from_payload(
        operation='SUBMIT', intent_id=ident, context=context(epoch),
        payload={'instrument':'IF2612','side':'BUY','offset':'OPEN','quantity':1,'limit_price':'1.0'})

def _reserve_child(db, writer, barrier, conn):
    core = AccountActorServerCoreV1(db, snapshot_authority=authority())
    try:
        barrier.wait(timeout=15)
        command = core.reserve_intent(writer, intent(), expected_snapshot_version=1)
        conn.send(('reserved', command.command_digest, command.state))
    except ActorServerError as exc:
        conn.send(('rejected', exc.code, ''))
    finally:
        core.close(); conn.close()

def main():
    results = {}
    # A local test signer can vouch for arbitrary well-formed domain values and version numbers.
    with tempfile.TemporaryDirectory(prefix='g6-r1-fake-signer-') as td:
        db = str(Path(td)/'fake-sign.sqlite3')
        core = AccountActorServerCoreV1(db, snapshot_authority=authority())
        writer = core.claim_writer(ACCOUNT_A, 'qa-writer')
        core.bind_session(writer, context(writer.epoch))
        forged = bundle(77, available='999999999999999999.99')
        proof = authority().attest(forged)
        core.publish_snapshot(writer, forged)
        command = core.reserve_intent(writer, intent(writer.epoch, 'fake-signed'), expected_snapshot_version=77)
        auth = core.authorize_dispatch(writer, operation='SUBMIT', intent_id='fake-signed')
        results['fake_signer_arbitrary_snapshot'] = {
            'accepted': True, 'version': auth.snapshot_version,
            'funds_fact': forged.facts[0].payload_json, 'proof_is_test_hmac': len(proof.proof_hex)==64,
            'return_type': type(auth).__name__, 'state': auth.state,
            'dispatch_rows': core.count_dispatch_rows(ACCOUNT_A),
        }
        assert auth.snapshot_version == 77 and auth.state == 'AUTHORIZED_LOCAL_OUTBOX'
        # Current pointer advances; idempotent AUTHORIZED branch still returns authorization for version 77.
        newer = bundle(78, available='0.00')
        core.publish_snapshot(writer, newer)
        stale_again = core.authorize_dispatch(writer, operation='SUBMIT', intent_id='fake-signed')
        with closing(sqlite3.connect(db)) as connection:
            current = connection.execute('SELECT snapshot_version FROM actor_current_snapshots WHERE account_ref=?',(ACCOUNT_A,)).fetchone()[0]
            state = connection.execute('SELECT state,expected_snapshot_version FROM actor_commands WHERE account_ref=? AND intent_id=?',(ACCOUNT_A,'fake-signed')).fetchone()
        results['authorization_replayed_after_new_snapshot'] = {
            'current_version': current, 'command_state': state[0], 'reserved_version': state[1],
            'returned_version': stale_again.snapshot_version, 'same_prior_authorization': stale_again == auth,
            'dispatch_rows': core.count_dispatch_rows(ACCOUNT_A),
        }
        assert current == 78 and stale_again == auth and stale_again.snapshot_version == 77
        core.close()

    # Writer with filesystem write access can replace the local capability hash and impersonate the core.
    with tempfile.TemporaryDirectory(prefix='g6-r1-db-writer-') as td:
        db = str(Path(td)/'db-writer.sqlite3')
        core = AccountActorServerCoreV1(db, snapshot_authority=authority())
        core.close()
        token='known-local-attacker-token-000000000000000000000000'
        token_hash=hashlib.sha256(token.encode()).hexdigest()
        with closing(sqlite3.connect(db)) as connection:
            connection.execute(
                "INSERT INTO actor_account_writers(account_ref,epoch,owner_id,token_sha256,state,context_json) VALUES(?,?,?,?, 'ACTIVE', NULL)",
                (ACCOUNT_A, 1, 'db-writer', token_hash))
            connection.commit()
        forged_writer=WriterEpochV1(ACCOUNT_A,'db-writer',1,token)
        core=AccountActorServerCoreV1(db,snapshot_authority=authority())
        core.bind_session(forged_writer,context(1))
        core.publish_snapshot(forged_writer,bundle(1))
        command=core.reserve_intent(forged_writer,intent(1,'db-write'),expected_snapshot_version=1)
        auth=core.authorize_dispatch(forged_writer,operation='SUBMIT',intent_id='db-write')
        results['same_host_db_writer_forges_capability']={
            'accepted':True,'writer_epoch':auth.writer_epoch,'owner_id':forged_writer.owner_id,
            'state':auth.state,'dispatch_rows':core.count_dispatch_rows(ACCOUNT_A),
        }
        assert auth.state=='AUTHORIZED_LOCAL_OUTBOX'
        core.close()

    # A valid layout with post-reservation domain deletion fails final gate and rolls back.
    with tempfile.TemporaryDirectory(prefix='g6-r1-domain-tamper-') as td:
        db=str(Path(td)/'domain.sqlite3'); core=AccountActorServerCoreV1(db,snapshot_authority=authority())
        writer=core.claim_writer(ACCOUNT_A,'domain-writer'); core.bind_session(writer,context(writer.epoch)); core.publish_snapshot(writer,bundle(1))
        core.reserve_intent(writer,intent(writer.epoch,'domain-hole'),expected_snapshot_version=1)
        with closing(sqlite3.connect(db)) as connection:
            connection.execute("DELETE FROM actor_snapshot_domains WHERE account_ref=? AND snapshot_version=1 AND domain='trades'",(ACCOUNT_A,)); connection.commit()
        try:
            core.authorize_dispatch(writer,operation='SUBMIT',intent_id='domain-hole')
            raise AssertionError('missing domain unexpectedly authorized')
        except ActorServerError as exc:
            with closing(sqlite3.connect(db)) as connection:
                command_state=connection.execute("SELECT state FROM actor_commands WHERE account_ref=? AND intent_id='domain-hole'",(ACCOUNT_A,)).fetchone()[0]
            rows=core.count_dispatch_rows(ACCOUNT_A)
            results['domain_tamper_rolls_back_final_gate']={'code':exc.code,'command_state':command_state,'dispatch_rows':rows}
            assert exc.code=='snapshot_domain_set_incomplete' and command_state=='RESERVED' and rows==0
        core.close()

    # Incompatible startup schema is rejected and left untouched.
    with tempfile.TemporaryDirectory(prefix='g6-r1-schema-tamper-') as td:
        db=str(Path(td)/'schema.sqlite3'); fresh=AccountActorServerCoreV1(db); fresh.close()
        with closing(sqlite3.connect(db)) as connection:
            connection.execute('DROP TABLE actor_account_writers')
            connection.execute('CREATE TABLE actor_account_writers(account_ref TEXT, epoch INTEGER, owner_id TEXT, token_sha256 TEXT, state TEXT)')
            connection.commit()
        try:
            AccountActorServerCoreV1(db)
            raise AssertionError('malformed schema accepted')
        except ActorServerError as exc:
            with closing(sqlite3.connect(db)) as connection:
                user_version=connection.execute('PRAGMA user_version').fetchone()[0]
                ddl=connection.execute("SELECT sql FROM sqlite_master WHERE name='actor_account_writers'").fetchone()[0]
            results['malformed_schema_not_repaired']={'code':exc.code,'user_version':user_version,'pk_preserved':('PRIMARY KEY' in ddl)}
            assert exc.code=='database_schema_shape_invalid' and user_version==1 and 'PRIMARY KEY' not in ddl

    # Two separate Python processes submit the same exact command concurrently: one durable row, same digest.
    with tempfile.TemporaryDirectory(prefix='g6-r1-replay-race-') as td:
        db=str(Path(td)/'replay.sqlite3'); core=AccountActorServerCoreV1(db,snapshot_authority=authority())
        writer=core.claim_writer(ACCOUNT_A,'replay-writer'); core.bind_session(writer,context(writer.epoch)); core.publish_snapshot(writer,bundle(1)); core.close()
        mp=multiprocessing.get_context('spawn'); barrier=mp.Barrier(2); ends=[mp.Pipe(duplex=False) for _ in range(2)]
        procs=[mp.Process(target=_reserve_child,args=(db,writer,barrier,ends[i][1])) for i in range(2)]
        for p in procs:p.start()
        for _,child in ends:child.close()
        messages=[parent.recv() for parent,_ in ends]
        for p in procs:p.join(20)
        assert all(p.exitcode==0 for p in procs),[p.exitcode for p in procs]
        core=AccountActorServerCoreV1(db,snapshot_authority=authority())
        with closing(sqlite3.connect(db)) as connection:
            count=connection.execute("SELECT COUNT(*) FROM actor_commands WHERE account_ref=? AND operation='SUBMIT' AND intent_id='qa-intent'",(ACCOUNT_A,)).fetchone()[0]
        results['two_process_same_intent_replay']={'responses':messages,'command_rows':count}
        assert len(messages)==2 and all(m[0]=='reserved' for m in messages) and messages[0][1]==messages[1][1] and count==1
        core.close()

    # No provider/SDK argument or method exists in authorize_dispatch; this proof object is only local outbox state.
    results['provider_dispatch_surface']={'core_has_dispatch_method':hasattr(AccountActorServerCoreV1,'dispatch'),'authorization_is_provider_receipt':False}
    print(json.dumps(results,sort_keys=True,indent=2))

if __name__=='__main__':
    multiprocessing.freeze_support()
    main()
