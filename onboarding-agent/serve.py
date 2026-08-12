#!/usr/bin/env python3

import logging
import os
import sys

from onboarding_agent.production_api import OnboardingApplication, OnboardingHttpServer


def main(argv=None):
    logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'),
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    data_dir = os.environ.get('ONBOARDING_DATA_DIR', os.path.join(repo_root, '.local', 'data'))
    db_path = os.environ.get('ONBOARDING_DB_PATH', os.path.join(data_dir, 'onboarding.sqlite'))
    checkpoint_db = os.environ.get('ONBOARDING_CHECKPOINT_DB',
                                   os.path.join(data_dir, 'onboarding-checkpoints.sqlite'))
    host = os.environ.get('HOST', '127.0.0.1')
    if host not in ['127.0.0.1', '::1', 'localhost'] and os.environ.get('ALLOW_NON_LOOPBACK') != 'true':
        raise ValueError('non-loopback binding requires ALLOW_NON_LOOPBACK=true')
    port = int(os.environ.get('PORT', os.environ.get('ADAPTER_PORT', '8087')))
    app = OnboardingApplication(db_path, checkpoint_db)
    server = OnboardingHttpServer((host, port), app)
    logging.getLogger(__name__).info('onboarding agent serving host=%s port=%s', host, port)
    server.serve_forever()
    return 0


if __name__ == '__main__':
    sys.exit(main())
