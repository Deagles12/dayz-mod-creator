from locale_studio import tr

import ctypes as c
import os
import struct
import time
import json
from contextlib import contextmanager
from urllib.parse import urlencode
from urllib.request import urlopen


class Callback(c.Structure):
    _fields_ = [('user', c.c_int), ('callback', c.c_int), ('data', c.c_void_p), ('size', c.c_int)]


@contextmanager
def steam(game):
    os.environ['SteamAppId'] = '221100'
    os.environ['SteamGameId'] = '221100'
    with os.add_dll_directory(str(game)):
        api = c.CDLL(str(game / 'steam_api64.dll'))

    def bind(name, result, *arguments):
        function = getattr(api, name)
        function.restype = result
        function.argtypes = arguments
        return function

    def interface(name):
        for version in range(40, 0, -1):
            try:
                return bind(f'SteamAPI_Steam{name}_v{version:03}', c.c_void_p)()
            except AttributeError:
                continue
        raise RuntimeError(tr('Інтерфейс Steam {} недоступний.', 'The Steam {} interface is unavailable.').format(name))

    if not bind('SteamAPI_Init', c.c_bool)():
        raise RuntimeError(tr('Steam API недоступний. Увійди в Steam на цьому ПК.', 'The Steam API is unavailable. Sign in to Steam on this PC.'))
    try:
        user = interface('User')
        ugc = interface('UGC')
        ptr, u64 = c.c_void_p, c.c_uint64
        if not user or not ugc:
            raise RuntimeError(tr('Steam не повернув активного користувача або UGC.', 'Steam did not provide an active user or UGC interface.'))
        owner = bind('SteamAPI_ISteamUser_GetSteamID', u64, ptr)(user)
        yield bind, ugc, owner
    finally:
        bind('SteamAPI_Shutdown', None)()


def active_user(game):
    with steam(game) as (_, _, owner):
        return str(owner)


def item_details(item):
    encoded = urlencode({'itemcount': '1', 'publishedfileids[0]': item}).encode('ascii')
    url = 'https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/'
    with urlopen(url, data=encoded, timeout=10) as response:
        data = json.loads(response.read(512 * 1024))
    result = data.get('response', {}).get('publishedfiledetails', [])
    item_data = result[0] if result else {}
    if item_data.get('result') != 1:
        return None
    return dict(title=str(item_data.get('title', '')), owner=str(item_data.get('creator', '')),
                dayz=str(item_data.get('consumer_app_id', '')) == '221100')


def check_owner(actual, expected):
    if actual != expected:
        raise ValueError(tr('Активний Steam-акаунт відрізняється від SteamID64 у профілі.', 'The active Steam account differs from the configured SteamID64.'))


def agreement(item):
    return RuntimeError(tr('Прийми угоду Steam Workshop на сторінці item і повтори публікацію.',
                           'Accept the Steam Workshop agreement on the item page, then retry publication.')
                        + f' https://steamcommunity.com/sharedfiles/filedetails/?id={item}')


def callbacks(bind):
    bind('SteamAPI_ManualDispatch_Init', None)()
    pipe = bind('SteamAPI_GetHSteamPipe', c.c_int)()
    run = bind('SteamAPI_ManualDispatch_RunFrame', None, c.c_int)
    next_callback = bind('SteamAPI_ManualDispatch_GetNextCallback', c.c_bool, c.c_int, c.POINTER(Callback))
    free = bind('SteamAPI_ManualDispatch_FreeLastCallback', None, c.c_int)
    result = bind('SteamAPI_ManualDispatch_GetAPICallResult', c.c_bool,
                  c.c_int, c.c_uint64, c.c_void_p, c.c_int, c.c_int, c.POINTER(c.c_bool))

    def wait(call, expected, minimum, tick=lambda: None):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            run(pipe)
            message = Callback()
            while next_callback(pipe, c.byref(message)):
                try:
                    if message.callback != 703 or message.size < 16:
                        continue
                    request, kind, size = struct.unpack_from('<Qii', c.string_at(message.data, 16))
                    if request != call:
                        continue
                    if kind != expected or not minimum <= size <= 1024:
                        raise TimeoutError(tr('Неочікувана відповідь Steam. Перевір Workshop.',
                                              'Unexpected Steam response. Check Workshop.'))
                    buffer = c.create_string_buffer(size)
                    failed = c.c_bool()
                    if not result(pipe, call, buffer, size, kind, c.byref(failed)) or failed.value:
                        raise TimeoutError(tr('Steam не підтвердив результат. Перевір Workshop.',
                                              'Steam did not confirm the result. Check Workshop.'))
                    if struct.unpack_from('<i', buffer.raw)[0] == 16:
                        break
                    return buffer.raw
                finally:
                    free(pipe)
            else:
                tick()
                time.sleep(.15)
                continue
            break
        raise TimeoutError(tr('Steam не повернув результат. Перевір Workshop перед повторною спробою.',
                              'Steam returned no result. Check Workshop before trying again.'))

    return wait


class CreateItemResult(c.Structure):
    _fields_ = [('result', c.c_int), ('item', c.c_uint64), ('agreement', c.c_bool)]


def create(game, owner):
    with steam(game) as (bind, ugc, actual):
        check_owner(actual, owner)
        wait = callbacks(bind)
        create_item = bind('SteamAPI_ISteamUGC_CreateItem', c.c_uint64, c.c_void_p, c.c_uint32, c.c_int)
        call = create_item(ugc, 221100, 0)
        if call in (0, 2**64 - 1):
            raise RuntimeError('Steam did not accept the item creation request.')
        data = CreateItemResult.from_buffer_copy(wait(call, 3403, c.sizeof(CreateItemResult)))
        if data.result != 1 or not data.item:
            raise RuntimeError(f'Steam rejected item creation. EResult: {data.result}')
        return data.item, data.agreement


def upload(game, item, owner, package, notes, log, metadata=None):
    if not 0 < item < 2**64 or not 0 < owner < 2**64:
        raise ValueError(tr('Потрібні числові Workshop ID та SteamID64 власника.', 'Enter a numeric Workshop ID and owner SteamID64.'))
    with steam(game) as (bind, ugc, actual):
        check_owner(actual, owner)
        ptr, u64 = c.c_void_p, c.c_uint64
        wait = callbacks(bind)
        start = bind('SteamAPI_ISteamUGC_StartItemUpdate', u64, ptr, c.c_uint32, u64)
        content = bind('SteamAPI_ISteamUGC_SetItemContent', c.c_bool, ptr, u64, c.c_char_p)
        submit = bind('SteamAPI_ISteamUGC_SubmitItemUpdate', u64, ptr, u64, c.c_char_p)
        progress = bind('SteamAPI_ISteamUGC_GetItemUpdateProgress', c.c_int, ptr, u64, c.POINTER(u64), c.POINTER(u64))
        handle = start(ugc, 221100, item)
        if handle in (0, 2**64 - 1) or not content(ugc, handle, str(package).encode('utf-8')):
            raise RuntimeError(tr('Steam відхилив Workshop ID або папку пакета.', 'Steam rejected the Workshop ID or package folder.'))
        if metadata:
            for key, field in [('Title', 'title'), ('Description', 'description'), ('Preview', 'preview')]:
                setter = bind('SteamAPI_ISteamUGC_SetItem' + key, c.c_bool, ptr, u64, c.c_char_p)
                if not setter(ugc, handle, metadata[field].encode('utf-8')):
                    raise ValueError(f'Steam rejected the item {field}.')
            visibility = bind('SteamAPI_ISteamUGC_SetItemVisibility', c.c_bool, ptr, u64, c.c_int)
            if not visibility(ugc, handle, metadata['visibility']):
                raise ValueError('Steam rejected the item visibility.')
        call = submit(ugc, handle, notes.encode('utf-8'))
        if call in (0, 2**64 - 1):
            raise RuntimeError(tr('Steam не прийняв запит оновлення.', 'Steam did not accept the update request.'))
        log(tr('Steam прийняв запит для item {}. Очікування підтвердження…', 'Steam accepted the request for item {}. Waiting for confirmation…').format(item))
        previous = None
        next_log = 0

        def tick():
            nonlocal previous, next_log
            done, total = u64(), u64()
            status = progress(ugc, handle, c.byref(done), c.byref(total))
            current = (status, done.value, total.value)
            if current != previous and time.monotonic() >= next_log:
                log(tr('Steam: етап {}, {:,} / {:,} байт', 'Steam: stage {}, {:,} / {:,} bytes').format(status, done.value, total.value))
                previous, next_log = current, time.monotonic() + 2
        data = wait(call, 3404, 5, tick)
        if data[4]:
            raise agreement(item)
        code = struct.unpack_from('<i', data)[0]
        if code != 1:
            raise RuntimeError(tr('Steam відхилив оновлення. EResult: {}', 'Steam rejected the update. EResult: {}').format(code))
        log(tr('Steam підтвердив оновлення item {}.', 'Steam confirmed the update for item {}.').format(item))
