"""Read PCM from one fixed source through PulseAudio or PipeWire's Pulse server."""
import ctypes as ct
from functools import cache
from time import monotonic


class CaptureError(RuntimeError):
    """A capture failure safe to display in the application."""


class SampleSpec(ct.Structure):
    _fields_ = [('format', ct.c_int), ('rate', ct.c_uint32), ('channels', ct.c_uint8)]


class BufferAttr(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in
                ('maxlength', 'tlength', 'prebuf', 'minreq', 'fragsize')]


Notify = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_void_p)
CONTEXT_READY = 4
STREAM_READY = 2
S16LE = 3
DONT_MOVE = 0x0200
ADJUST_LATENCY = 0x2000
UNSPECIFIED = 0xffffffff


@cache
def pulse():
    try:
        lib = ct.CDLL('libpulse.so.0')
    except OSError:
        raise CaptureError('Install libpulse0 to capture playback audio.') from None
    ptr, integer, uint, string = ct.c_void_p, ct.c_int, ct.c_uint32, ct.c_char_p
    signatures = (
        ('mainloop_new', ptr, ()),
        ('mainloop_free', None, (ptr,)),
        ('mainloop_get_api', ptr, (ptr,)),
        ('mainloop_iterate', integer, (ptr, integer, ptr)),
        ('context_new', ptr, (ptr, string)),
        ('context_connect', integer, (ptr, string, integer, ptr)),
        ('context_get_state', integer, (ptr,)),
        ('context_disconnect', None, (ptr,)),
        ('context_unref', None, (ptr,)),
        ('stream_new', ptr, (ptr, string, ct.POINTER(SampleSpec), ptr)),
        ('stream_connect_record', integer, (ptr, string, ct.POINTER(BufferAttr), integer)),
        ('stream_get_state', integer, (ptr,)),
        ('stream_get_device_index', uint, (ptr,)),
        ('stream_get_device_name', string, (ptr,)),
        ('stream_set_moved_callback', None, (ptr, Notify, ptr)),
        ('stream_peek', integer, (ptr, ct.POINTER(ptr), ct.POINTER(ct.c_size_t))),
        ('stream_drop', integer, (ptr,)),
        ('stream_disconnect', integer, (ptr,)),
        ('stream_unref', None, (ptr,)),
    )
    for name, result, args in signatures:
        function = getattr(lib, 'pa_' + name)
        function.restype, function.argtypes = result, args
    return lib


def record(source, stop, rate):
    if stop.is_set():
        return
    lib = pulse()
    loop = lib.pa_mainloop_new()
    if not loop:
        raise CaptureError('Could not initialize audio capture.')
    context = stream = None

    def dispatch():
        if lib.pa_mainloop_iterate(loop, 0, None) < 0:
            raise CaptureError('Audio server disconnected.')

    def ready(get_state, handle, target):
        deadline = monotonic() + 5
        while not stop.is_set():
            state = get_state(handle)
            if state == target:
                return True
            if state > target or monotonic() >= deadline:
                raise CaptureError('Could not connect to the selected playback monitor.')
            dispatch()
            stop.wait(.01)
        return False

    try:
        context = lib.pa_context_new(lib.pa_mainloop_get_api(loop), b'Cicada')
        if not context or lib.pa_context_connect(context, None, 1, None) < 0:  # PA_CONTEXT_NOAUTOSPAWN
            raise CaptureError('Could not connect to the audio server.')
        if not ready(lib.pa_context_get_state, context, CONTEXT_READY):
            return
        spec = SampleSpec(S16LE, rate, 1)
        stream = lib.pa_stream_new(context, b'Cicada playback capture', ct.byref(spec), None)
        if not stream:
            raise CaptureError('Could not create the playback capture stream.')
        moved = False

        @Notify
        def on_move(_stream, _data):
            nonlocal moved
            moved = True

        lib.pa_stream_set_moved_callback(stream, on_move, None)
        device = source.encode('utf-8')
        attrs = BufferAttr(rate * 4, UNSPECIFIED, UNSPECIFIED, UNSPECIFIED, rate // 5)
        if lib.pa_stream_connect_record(stream, device, ct.byref(attrs), DONT_MOVE | ADJUST_LATENCY) < 0:
            raise CaptureError('Could not open the selected playback monitor.')
        if not ready(lib.pa_stream_get_state, stream, STREAM_READY):
            return
        source_index = lib.pa_stream_get_device_index(stream)
        while True:
            if not stop.is_set():
                dispatch()
            if (lib.pa_context_get_state(context) != CONTEXT_READY
                    or lib.pa_stream_get_state(stream) != STREAM_READY):
                raise CaptureError('Audio capture disconnected. Select a playback monitor to resume.')
            if (moved or source_index == UNSPECIFIED
                    or lib.pa_stream_get_device_name(stream) != device
                    or lib.pa_stream_get_device_index(stream) != source_index):
                raise CaptureError('Playback monitor changed. Select a playback monitor to resume.')
            data, size = ct.c_void_p(), ct.c_size_t()
            if lib.pa_stream_peek(stream, ct.byref(data), ct.byref(size)) < 0:
                raise CaptureError('Could not read the selected playback monitor.')
            if not size.value:
                if stop.wait(.01):
                    break
                continue
            # libpulse reports gaps as a nonzero length with a null data pointer.
            pcm = ct.string_at(data, size.value) if data.value else bytes(size.value)
            if lib.pa_stream_drop(stream) < 0:
                raise CaptureError('Audio capture disconnected.')
            yield pcm
    finally:
        if stream:
            lib.pa_stream_disconnect(stream)
            lib.pa_stream_unref(stream)
        if context:
            lib.pa_context_disconnect(context)
            lib.pa_context_unref(context)
        lib.pa_mainloop_free(loop)
