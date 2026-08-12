#!/usr/bin/env python3

import logging
import os
import sys

from circle_agent.api import CircleApplication, serve


def main(argv=None):
    logging.basicConfig(
        level=os.environ.get('LOG_LEVEL', 'INFO'),
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )
    agent_dir = os.path.abspath(os.path.dirname(__file__))
    repo_root = os.path.abspath(os.path.join(agent_dir, '..'))
    data_dir = os.environ.get('CIRCLE_DATA_DIR', os.path.join(repo_root, '.local', 'data'))
    db_path = os.environ.get('CIRCLE_DB_PATH', os.path.join(data_dir, 'circle.sqlite'))
    checkpoint_db = os.environ.get(
        'CIRCLE_CHECKPOINT_DB', os.path.join(data_dir, 'circle-checkpoints.sqlite'),
    )
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', os.environ.get('ADAPTER_PORT', '8086')))
    app = CircleApplication(db_path, checkpoint_db)
    serve(host, port, app)
    return 0


if __name__ == '__main__':
    sys.exit(main())
