"""Offline execution of the real entry point; all network boundaries are mocked."""
import contextlib
import io
import itertools
import json
import os
import runpy
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from telegram.error import BadRequest
from test_bot_advice import ROOT, weather_response


class PublicationTests(unittest.TestCase):
    def test_all_failure_combinations_with_and_without_photo(self):
        for photo in (False, True):
            for failures in itertools.product((False, True), repeat=4):
                with self.subTest(photo=photo, failures=failures):
                    self.check_publication(photo, failures)

    def check_publication(self, photo, failures):
        attempts = []
        delivered = []
        payloads = []
        secret = 'SECRET_CANARY'

        class FakeBot:
            def __init__(self, token):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def send_message(self, *, chat_id, text):
                index = 0 if chat_id == -1004382412226 else 1
                attempts.append(index)
                payloads.append(text)
                if failures[index]:
                    raise BadRequest('Chat not found ' + secret)
                delivered.append(index)

            async def send_photo(self, *, chat_id, photo, caption):
                assert photo.read() == b'fake-photo'
                await self.send_message(chat_id=chat_id, text=caption)

        uploads = []

        def urlopen(req, **kwargs):
            url = req if isinstance(req, str) else req.full_url
            if url.startswith('https://api.weatherapi.com/'):
                body = weather_response('dry')
            elif url == 'https://platform-api2.max.ru/uploads?type=image':
                uploads.append(url)
                body = {'url': 'https://upload.invalid/image'}
            elif url == 'https://upload.invalid/image':
                self.assertEqual(req.data, b'fake-photo')
                body = {'photos': {'image': {'token': secret}}}
            elif url.startswith('https://platform-api2.max.ru/messages?chat_id='):
                index = 2 if url.endswith('primary') else 3
                attempts.append(index)
                data = json.loads(req.data)
                payloads.append(data['text'])
                self.assertEqual('attachments' in data, photo)
                if failures[index]:
                    raise HTTPError(url + secret, 403, secret, {}, None)
                delivered.append(index)
                body = {'success': True}
            else:
                raise AssertionError('Unexpected network request')
            return io.BytesIO(json.dumps(body).encode())

        real_open = open

        def open_file(path, *args, **kwargs):
            if path == 'offline-photo.jpg':
                return io.BytesIO(b'fake-photo')
            return real_open(path, *args, **kwargs)

        output = io.StringIO()
        with (
            patch.dict(os.environ, {
                'TELEGRAM_BOT_TOKEN': secret, 'WEATHER_API_KEY': secret,
                'MAX_BOT_TOKEN': secret, 'MAX_CHAT_ID': 'primary',
                'MAX_NEWS_CHAT_ID': 'news',
            }),
            patch('telegram.Bot', FakeBot),
            patch('urllib.request.urlopen', side_effect=urlopen),
            patch('httpx.Client', side_effect=AssertionError('Real HTTP forbidden')),
            patch('weather_advice.generate_weather_advice', return_value='Ясная погода.'),
            patch('os.path.exists', return_value=photo),
            patch('os.listdir', return_value=['offline-photo.jpg']),
            patch('random.choice', side_effect=lambda values: (
                'offline-photo.jpg' if str(values[0]).endswith('.jpg') else values[0]
            )),
            patch('builtins.open', side_effect=open_file),
            contextlib.redirect_stdout(output),
        ):
            if any(failures):
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_path(str(ROOT / 'app_zngrd_weather.py'))
                self.assertEqual(raised.exception.code, 1)
            else:
                runpy.run_path(str(ROOT / 'app_zngrd_weather.py'))
        self.assertEqual(attempts, [0, 1, 2, 3])  # order and no retries
        self.assertEqual(delivered, [i for i in range(4) if not failures[i]])
        self.assertEqual(len(set(payloads)), 1)  # same forecast for all destinations
        self.assertEqual(len(uploads), 2 if photo else 0)
        logs = [json.loads(line) for line in output.getvalue().splitlines()
                if line.startswith('{"destination"') or line.startswith('{"publication_result"')]
        self.assertEqual([row['destination'] for row in logs[:-1]],
                         ['telegram_primary', 'telegram_news', 'max_primary', 'max_news'])
        self.assertEqual([row['result'] for row in logs[:-1]],
                         ['failure' if failed else 'success' for failed in failures])
        self.assertEqual(logs[-1]['failed'], sum(failures))
        self.assertEqual(logs[-1]['attempted'], 4)
        self.assertNotIn(secret, output.getvalue())
        self.assertNotIn('Authorization', output.getvalue())
        self.assertNotIn('https://', output.getvalue())


if __name__ == '__main__':
    unittest.main()
