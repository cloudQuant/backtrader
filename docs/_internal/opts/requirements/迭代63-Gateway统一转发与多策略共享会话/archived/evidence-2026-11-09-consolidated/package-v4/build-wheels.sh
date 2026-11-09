#!/bin/sh
set -e
TASK_TMP_DIR=$1
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pip wheel --no-build-isolation --no-deps -w "$TASK_TMP_DIR/wheels" "$TASK_TMP_DIR/projects/bt_api_base" "$TASK_TMP_DIR/projects/bt_api_ctp" "$TASK_TMP_DIR/projects/bt_api_gateway" "$TASK_TMP_DIR/projects/bt_api_risk" "$TASK_TMP_DIR/projects/bt_api_monitor" "$TASK_TMP_DIR/projects/bt_api_transport_zmq" "$TASK_TMP_DIR/projects/bt_api_execution" "$TASK_TMP_DIR/projects/bt_api_py"
(cd "$TASK_TMP_DIR/wheels" && shasum -a 256 *.whl > "$TASK_TMP_DIR/wheel-sha256.txt")
