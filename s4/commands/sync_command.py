#! -*- encoding: utf -*-

import sys

from clint.textui.colored import ColoredString

from s4 import sync, utils
from s4.clients.local import get_local_client
from s4.clients.s3 import get_s3_client
from s4.diff import show_diff
from s4.progressbar import ProgressBar
from s4.resolution import Resolution


def get_clients(entry):
    target_1 = entry['local_folder']
    target_2 = entry['s3_uri']
    aws_access_key_id = entry['aws_access_key_id']
    aws_secret_access_key = entry['aws_secret_access_key']
    region_name = entry['region_name']

    # append trailing slashes to prevent incorrect prefix matching on s3
    if not target_1.endswith('/'):
        target_1 += '/'
    if not target_2.endswith('/'):
        target_2 += '/'

    client_1 = get_local_client(target_1)
    client_2 = get_s3_client(target_2, aws_access_key_id, aws_secret_access_key, region_name)
    return client_1, client_2


def handle_conflict(key, action_1, client_1, action_2, client_2):
    print(
        '\n'
        'Conflict for "{}". Which version would you like to keep?\n'
        '   (1) {}{} updated at {} ({})\n'
        '   (2) {}{} updated at {} ({})\n'
        '   (d) View difference (requires the diff command)\n'
        '   (X) Skip this file\n'.format(
            key,
            client_1.get_uri(),
            key, action_1.get_remote_datetime(), action_1.state,
            client_2.get_uri(),
            key, action_2.get_remote_datetime(), action_2.state,
        ),
        file=sys.stderr,
    )
    while True:
        choice = utils.get_input('Choice (default=skip): ')
        print('', file=sys.stderr)

        if choice == 'd':
            show_diff(client_1, client_2, key)
        else:
            break

    if choice == '1':
        return Resolution.get_resolution(key, action_1, client_2, client_1)
    elif choice == '2':
        return Resolution.get_resolution(key, action_2, client_1, client_2)


def display_progress_bar(sync_object):
    ProgressBar(
        total=sync_object.total_size,
        leave=False,
        ncols=80,
        unit='B',
        unit_scale=True,
        mininterval=0.2,
    )


def update_progress_bar(value):
    ProgressBar.update(value)


def hide_progress_bar(sync_object):
    ProgressBar.close()


class SyncCommand(object):
    def __init__(self, args, config, logger):
        self.logger = logger
        self.args = args
        self.config = config

    def run(self):
        all_targets = list(self.config['targets'].keys())
        if not self.args.targets:
            targets = all_targets
        else:
            targets = self.args.targets

        try:
            for name in sorted(targets):
                if name not in self.config['targets']:
                    self.logger.info(
                        '"%s" is an unknown target. Choices are: %s',
                        name, all_targets
                    )
                    continue

                entry = self.config['targets'][name]
                client_1, client_2 = get_clients(entry)

                try:
                    worker = sync.SyncWorker(
                        client_1,
                        client_2,
                        start_callback=display_progress_bar,
                        update_callback=update_progress_bar,
                        complete_callback=hide_progress_bar,
                        conflict_handler=handle_conflict,
                        action_callback=self.action_callback,
                    )

                    self.logger.info(
                        'Syncing %s [%s <=> %s]',
                        name, client_1.get_uri(), client_2.get_uri()
                    )
                    worker.sync(
                        conflict_choice=self.args.conflicts,
                        dry_run=self.args.dry_run,
                    )
                except Exception as e:
                    if self.args.log_level == "DEBUG":
                        self.logger.exception(e)
                    else:
                        self.logger.error("There was an error syncing '%s': %s", name, e)

        except KeyboardInterrupt:
            self.logger.warning('Quitting due to Keyboard Interrupt...')

    def action_callback(self, resolution):
        if resolution.action == Resolution.UPDATE:
            self.logger.info(
                self._colored('YELLOW', 'Updating %s (%s => %s)'),
                resolution.key,
                resolution.from_client.get_uri(),
                resolution.to_client.get_uri()
            )
        elif resolution.action == Resolution.CREATE:
            self.logger.info(
                self._colored('GREEN', 'Creating %s (%s => %s)'),
                resolution.key,
                resolution.from_client.get_uri(),
                resolution.to_client.get_uri()
            )
        elif resolution.action == Resolution.DELETE:
            self.logger.info(
                self._colored('RED', 'Deleting %s on %s'),
                resolution.key,
                resolution.to_client.get_uri()
            )

    def _colored(self, color, text):
        return text if self.args.no_colors else ColoredString(color, text)
