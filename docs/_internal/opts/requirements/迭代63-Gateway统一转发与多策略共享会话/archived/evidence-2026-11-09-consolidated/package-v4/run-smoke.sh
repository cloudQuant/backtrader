#!/bin/sh
set -e
TASK_TMP_DIR=$1
TASK_BUNDLE="$TASK_TMP_DIR/claim-wheel-smoke"
TASK_SITE="$TASK_TMP_DIR/venv/lib/python3.11/site-packages"
cd "$TASK_BUNDLE"
TASK_WHEEL_SITE="$TASK_SITE" TASK_CHILD_LOG="$TASK_TMP_DIR/child-imports.log" PYTHONPATH="$TASK_BUNDLE:$TASK_SITE" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -S -m pytest -s -q --import-mode=importlib -c "$TASK_BUNDLE/pytest.ini" "$TASK_BUNDLE/base/test_iter63_claim_fence.py" "$TASK_BUNDLE/tests/unit/test_iter63_gateway_dispatch_claim.py" "$TASK_BUNDLE/tests/unit/test_iter63_gateway_settlement_claim.py"
