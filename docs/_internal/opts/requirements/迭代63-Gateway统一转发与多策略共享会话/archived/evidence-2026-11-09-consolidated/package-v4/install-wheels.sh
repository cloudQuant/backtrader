#!/bin/sh
set -e
TASK_TMP_DIR=$1
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pip --python "$TASK_TMP_DIR/venv" install --index-url https://pypi.org/simple --find-links "$TASK_TMP_DIR/wheels" --report "$TASK_TMP_DIR/install-report.json" 'bt_api_py[gateway,risk,monitoring]==0.16.0.dev64' 'bt_api_base==0.16.0.dev64' 'bt_api_risk==0.1.1.dev64' 'bt_api_monitor==0.1.1.dev64' 'bt_api_ctp==2.1.0.dev64' 'bt_api_gateway==0.2.0.dev64' 'bt_api_transport_zmq==0.1.0' 'bt_api_execution==0.2.0'
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pip --python "$TASK_TMP_DIR/venv" check
