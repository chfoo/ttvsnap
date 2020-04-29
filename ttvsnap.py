'''Save Twitch screenshots using Twitch API preview thumbnails'''
# Copyright 2015-2018,2020 Christopher Foo. License: MIT.

import argparse
import datetime
import email.utils
import logging
import os
import re
import subprocess
import sys
import time

import requests
import requests.exceptions

__version__ = '1.1.0'

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
        '--client-id', required=True,
        help='Twitch Client ID')
    arg_parser.add_argument(
        '--client-secret-file', required=True, type=argparse.FileType('r'),
        help='Filename that contains Client Secret for the given Client ID')
    arg_parser.add_argument(
        '--cache-dir', required=True,
        help='Directory path where the script can write temporary secrets such as tokens')

    args = arg_parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if not os.path.isdir(args.output_dir):
        sys.exit('Output directory specified is not valid.')

    if not os.path.isdir(args.cache_dir):
        sys.exit('Cache directory specified is not valid.')

    if args.interval < 60:
        sys.exit('Interval cannot be less than 60 seconds.')

    subprocess.check_call(['convert', '-version'])

    grabber = Grabber(args)
    grabber.run()


class APIError(Exception):
    pass


ERROR_SLEEP_TIME = 90


class Grabber(object):
    def __init__(self, args):
        self._channel = args.channel_name
        self._output_dir = args.output_dir
        self._interval = args.interval
        self._subdir = args.subdir
        self._thumbnail = args.thumbnail
        self._client_id = args.client_id
        self._client_secret = args.client_secret_file.read().strip()
        self._cache_dir = args.cache_dir
        self._access_token = None
        self._last_file_date = None

    def run(self):
        self._load_access_token()

        if not self._access_token:
            try:
                _logger.info('Fetching access token')
                response = self._fetch_access_token()
            except (APIError, requests.exceptions.RequestException):
                _logger.exception('Request to get access token failed')

        if not self._access_token:
            doc = response.json()
            _logger.error('Authentication error %s %s %s',
                doc.get('status'), doc.get('error'), doc.get('message'))
        else:
            self._save_acesss_token()

        if self._check_client_id():
            _logger.info('Authentication looks OK')
        else:
            _logger.warning('Authenticated failed.')

        while True:
            try:
                response = self._fetch_stream_object()
                doc = response.json()
            except (requests.exceptions.RequestException, ValueError):
                _logger.exception('Error fetching stream object.')
                time.sleep(ERROR_SLEEP_TIME)
                continue

            if self._is_bad_token(response):
                _logger.info('Fetching access token')

                try:
                    response = self._fetch_access_token()
                except (APIError, requests.exceptions.RequestException):
                    _logger.exception('Request to get access token failed')
                    time.sleep(ERROR_SLEEP_TIME)
                    continue

                if not self._access_token:
                    doc = response.json()
                    _logger.error('Authentication error %s %s %s',
                        doc.get('status'), doc.get('error'), doc.get('message'))
                    time.sleep(ERROR_SLEEP_TIME)
                else:
                    self._save_acesss_token()
                continue

            if 'error' in doc:
                _logger.error('API error: %s: %s', doc['error'], doc.get('message'))
                time.sleep(ERROR_SLEEP_TIME)
                continue

            if doc.get('data'):
                try:
                    url = doc['data'][0]['thumbnail_url']
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

        if self._access_token:
            headers['Authorization'] = 'Bearer: {token}'.format(token=self._access_token)

        return headers

    def _check_client_id(self):
        headers = self._new_headers()
        url = 'https://api.twitch.tv/helix/users?login=jtv'
        response = requests.get(url, timeout=60, headers=headers)
        doc = response.json()
        return 'data' in doc

    def _load_access_token(self):
        path = os.path.join(self._cache_dir, 'access_token.txt')

        if os.path.exists(path):
            with open(path, 'r') as file:
                self._access_token = file.read().strip()

    def _save_acesss_token(self):
        path = os.path.join(self._cache_dir, 'access_token.txt')
        with open(path, 'w') as file:
            file.write(self._access_token or '')

    def _fetch_access_token(self):
        self._access_token = None
        headers = self._new_headers()
        url = 'https://id.twitch.tv/oauth2/token'
        data = {
            'client_id': self._client_id,
            'client_secret': self._client_secret,
            'grant_type': 'client_credentials',
            'scope': ''
        }
        response = requests.post(url, timeout=60, headers=headers, data=data)
        doc = response.json()

        self._access_token = doc.get('access_token')

        return response

    def _is_bad_token(self, response):
        return 'invalid_token' in response.headers.get('WWW-Authenticate', '')

    def _fetch_stream_object(self):
        headers = self._new_headers()
        url = 'https://api.twitch.tv/helix/streams?user_login={}'.format(self._channel)
        response = requests.get(url, timeout=60, headers=headers)
        return response

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

        if 'last-modified' in response.headers:
            self._last_file_date = response.headers['last-modified']
            datetime_obj = email.utils.parsedate_to_datetime(
                response.headers['last-modified']
            ).astimezone(datetime.timezone.utc)
        elif 'age' in response.headers and 'date' in response.headers:
            current_datetime_obj = email.utils.parsedate_to_datetime(
                response.headers['date']
            ).astimezone(datetime.timezone.utc)
            age_int = int(response.headers['age'])
            datetime_obj = current_datetime_obj - datetime.timedelta(seconds=age_int)
            self._last_file_date = email.utils.format_datetime(datetime_obj, True)
        elif 'expires' in response.headers \
                and 'cache-control' in response.headers \
                and 'max-age' in response.headers['cache-control']:
            match = re.match(r'max-age=(\d+)', response.headers['cache-control'])
            age_int = int(match.group(1))
            expires_date_obj = email.utils.parsedate_to_datetime(
                response.headers['expires']
            ).astimezone(datetime.timezone.utc)
            datetime_obj = expires_date_obj - datetime.timedelta(seconds=age_int)
            self._last_file_date = email.utils.format_datetime(datetime_obj, True)
        else:
            raise APIError("Could not get date of image")

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
