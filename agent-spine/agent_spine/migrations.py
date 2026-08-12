import argparse
import os
import sys

from agent_spine.store import Store


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Initialize or migrate the agent-spine SQLite database.')
    parser.add_argument('--db-path', default=os.getenv('AGENT_DB_PATH', '.local/data/agent.sqlite'))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    store = Store(args.db_path)
    store.migrate()
    print('migrated agent database: %s' % store.db_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
