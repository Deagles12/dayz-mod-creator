from locale_studio import tr

import ctypes as c
import os
import struct
import time


class Callback(c.Structure):
    _fields_ = [('user', c.c_int), ('callback', c.c_int), ('data', c.c_void_p), ('size', c.c_int)]


def upload(game, item, owner, package, notes, log):
    if not 0 < item < 2**64 or not 0 < owner < 2**64:
        raise ValueError(tr('Потрібні числові Workshop ID та SteamID64 власника.', 'Enter a numeric Workshop ID and owner SteamID64.'))
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
        if bind('SteamAPI_ISteamUser_GetSteamID', u64, ptr)(user) != owner:
            raise ValueError(tr('Активний Steam-акаунт відрізняється від SteamID64 у профілі.', 'The active Steam account differs from the configured SteamID64.'))
        bind('SteamAPI_ManualDispatch_Init', None)()
        pipe = bind('SteamAPI_GetHSteamPipe', c.c_int)()
        run = bind('SteamAPI_ManualDispatch_RunFrame', None, c.c_int)
        next_callback = bind('SteamAPI_ManualDispatch_GetNextCallback', c.c_bool, c.c_int, c.POINTER(Callback))
        free = bind('SteamAPI_ManualDispatch_FreeLastCallback', None, c.c_int)
        result = bind('SteamAPI_ManualDispatch_GetAPICallResult', c.c_bool,
                      c.c_int, u64, ptr, c.c_int, c.c_int, c.POINTER(c.c_bool))
        start = bind('SteamAPI_ISteamUGC_StartItemUpdate', u64, ptr, c.c_uint32, u64)
        content = bind('SteamAPI_ISteamUGC_SetItemContent', c.c_bool, ptr, u64, c.c_char_p)
        submit = bind('SteamAPI_ISteamUGC_SubmitItemUpdate', u64, ptr, u64, c.c_char_p)
        progress = bind('SteamAPI_ISteamUGC_GetItemUpdateProgress', c.c_int, ptr, u64, c.POINTER(u64), c.POINTER(u64))
        handle = start(ugc, 221100, item)
        if handle in (0, 2**64 - 1) or not content(ugc, handle, str(package).encode('utf-8')):
            raise RuntimeError(tr('Steam відхилив Workshop ID або папку пакета.', 'Steam rejected the Workshop ID or package folder.'))
        call = submit(ugc, handle, notes.encode('utf-8'))
        if call in (0, 2**64 - 1):
            raise RuntimeError(tr('Steam не прийняв запит оновлення.', 'Steam did not accept the update request.'))
        log(tr('Steam прийняв запит для item {}. Очікування підтвердження…', 'Steam accepted the request for item {}. Waiting for confirmation…').format(item))
        deadline = time.monotonic() + 600
        previous = None
        next_log = 0
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
                    if kind != 3404 or not 5 <= size <= 1024:
                        raise RuntimeError(tr('Неочікувана відповідь Steam.', 'Unexpected Steam response.'))
                    buffer = c.create_string_buffer(size)
                    failed = c.c_bool()
                    if not result(pipe, call, buffer, size, kind, c.byref(failed)) or failed.value:
                        raise RuntimeError(tr('Steam не підтвердив результат оновлення.', 'Steam did not confirm the update result.'))
                    code = struct.unpack_from('<i', buffer.raw)[0]
                    if buffer.raw[4]:
                        raise RuntimeError(tr('Steam вимагає прийняти угоду Steam Workshop.', 'Steam requires acceptance of the Workshop agreement.'))
                    if code != 1:
                        raise RuntimeError(tr('Steam відхилив оновлення. EResult: {}', 'Steam rejected the update. EResult: {}').format(code))
                    log(tr('Steam підтвердив оновлення item {}.', 'Steam confirmed the update for item {}.').format(item))
                    return
                finally:
                    free(pipe)
            done, total = u64(), u64()
            status = progress(ugc, handle, c.byref(done), c.byref(total))
            current = (status, done.value, total.value)
            if current != previous and time.monotonic() >= next_log:
                log(tr('Steam: етап {}, {:,} / {:,} байт', 'Steam: stage {}, {:,} / {:,} bytes').format(status, done.value, total.value))
                previous, next_log = current, time.monotonic() + 2
            time.sleep(.15)
        raise TimeoutError(tr('Steam не повернув результат. Перевір Workshop перед повторною спробою.', 'Steam returned no result. Check Workshop before trying again.'))
    finally:
        bind('SteamAPI_Shutdown', None)()
