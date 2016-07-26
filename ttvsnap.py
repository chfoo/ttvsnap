'''Save Twitch screenshots using Twitch API preview thumbnails'''
# Copyright 2015 Christopher Foo. License: MIT.

import argparse
import datetime
import logging
import os
import subprocess
import sys
import time
import email.utils

import requests
import requests.exceptions


__version__ = '1.0.3'
__version__ = '1.0.4'

_logger = logging.getLogger()


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument(
        'channel_name', help='Username of the Twitch channel')
    arg_parser.add_argument(
        'output_dir', help='Path of output directory')
    arg_parser.add_argument(
        '--interval', type=int, default=301,
        help='Number of seconds between each grab')
    arg_parser.add_argument(
        '--subdir', action='store_true',
        help='Create subdirectories for each day.')
    arg_parser.add_argument(
        '--thumbnail', action='store_true',
        help='Create thumbnails using Imagemagick "convert" command.')
    arg_parser.add_argument(
        '--client-id',
        help='Twitch Client ID'
    )

    args = arg_parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if not os.path.isdir(args.output_dir):
        sys.exit('Output directory specified is not valid.')

    if args.interval < 60:
        sys.exit('Interval cannot be less than 60 seconds.')

    subprocess.check_call(['convert', '-version'])

    grabber = Grabber(args.channel_name, args.output_dir, args.interval,
                      args.subdir, args.thumbnail, args.client_id)
    grabber.run()


class APIError(Exception):
    pass


ERROR_SLEEP_TIME = 90


class Grabber(object):
    def __init__(self, channel, output_dir, interval, subdir=False,
                 thumbnail=False, client_id=None):
        self._channel = channel
        self._output_dir = output_dir
        self._interval = interval
        self._subdir = subdir
        self._thumbnail = thumbnail
        self._client_id = client_id
        self._last_file_date = None

    def run(self):
        try:
            if self._client_id and not self._check_client_id():
                _logger.warning('Client ID is not valid')
        except (requests.exceptions.RequestException, ValueError):
            _logger.exception('Could not check Client ID validity')

        while True:
            try:
                doc = self._fetch_stream_object()
            except (requests.exceptions.RequestException, ValueError):
                _logger.exception('Error fetching stream object.')
                time.sleep(ERROR_SLEEP_TIME)
                continue

            if 'error' in doc:
                _logger.error('API error: %s: %s', doc['error'], doc.get('message'))
                time.sleep(ERROR_SLEEP_TIME)
                continue

            if doc.get('stream'):
                try:
                    url = doc['stream']['preview']['template']
                except KeyError:
                    _logger.exception('Unexpected document format.')
                    time.sleep(ERROR_SLEEP_TIME)
                    continue

                url = url.replace('{width}', '0').replace('{height}', '0')

                try:
                    path = self._fetch_image_and_save(url)
                except (APIError, requests.exceptions.RequestException):
                    _logger.exception('Error fetching image.')
                    time.sleep(ERROR_SLEEP_TIME)
                    continue

                if path and self._thumbnail:
                    self._create_thumbnail(path)

            time.sleep(self._interval)

    def _new_headers(self):
        headers = {
            'user-agent':
                'python-requests/{requests_ver} ttvsnap/{this_ver}'
                .format(requests_ver=requests.__version__,
                        this_ver=__version__)
        }
        if self._client_id:
            headers['Client-ID'] = self._client_id

        return headers

    def _check_client_id(self):
        headers = self._new_headers()
        url = 'https://api.twitch.tv/kraken/?api_version=3'
        response = requests.get(url, timeout=60, headers=headers)
        doc = response.json()
        return doc['identified']

    def _fetch_stream_object(self):
        headers = self._new_headers()
        url = 'https://api.twitch.tv/kraken/streams/{}?api_version=3'.format(self._channel)
        response = requests.get(url, timeout=60, headers=headers)
        doc = response.json()
        return doc

    def _fetch_image_and_save(self, url):
        headers = self._new_headers()

        if self._last_file_date:
            headers['if-modified-since'] = self._last_file_date

        response = requests.get(url, timeout=60, allow_redirects=False,
                                headers=headers)

        if response.status_code == 304:
            return

        if response.status_code != 200:
            raise APIError('Image status code: %s', response.status_code)

        self._last_file_date = response.headers['last-modified']

        datetime_obj = email.utils.parsedate_to_datetime(
            response.headers['last-modified']).astimezone(datetime.timezone.utc)

        extension = url.rsplit('.', 1)[-1] or 'bin'

        path_parts = [self._output_dir]

        if self._subdir:
            path_parts.append(datetime_obj.strftime('%Y-%m-%d'))
            subdir_path = os.path.join(*path_parts)

            if not os.path.exists(subdir_path):
                os.mkdir(subdir_path)

        path_parts.append('{}.{}'.format(
            datetime_obj.strftime('%Y-%m-%d_%H-%M-%S'),
            extension
        ))

        path = os.path.join(*path_parts)

        with open(path, 'wb') as file:
            for part in response.iter_content():
                file.write(part)

        _logger.info('Saved %s', path)

        return path

    def _create_thumbnail(self, path):
        basename, ext = os.path.splitext(path)
        thumbnail_path = '{}_thumb{}'.format(basename, ext)

        subprocess.check_call(['convert', path, '-thumbnail', 'x144',
                               thumbnail_path])


if __name__ == '__main__':
    main()
