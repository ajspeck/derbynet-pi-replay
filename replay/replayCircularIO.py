# -*- coding: utf-8 -*-
"""
Created on Thu Jan 17 20:36:07 2019

@author: ASpeck
"""

import io
import picamera
from operator import attrgetter
from picamera.frames import PiVideoFrameType


class BoundedPiCameraCircularIO(picamera.PiCameraCircularIO):
    def __init__(
            self, camera, size=None, seconds=None, bitrate=17000000,
            splitter_port=1):
        super(BoundedPiCameraCircularIO, self).__init__(camera=camera, size=size,
                                                        seconds=seconds, bitrate=bitrate,
                                                        splitter_port=splitter_port)
    def _find_bounded(self, firstTime, lastTime, frame_ends=PiVideoFrameType.sps_header):
        first = last = None
        field = 'timestamp'
        attr = attrgetter(field)
        for frame in reversed(self._frames):
            if (attr(frame)>=lastTime) and frame_ends in (None,frame.frame_type):
                last = frame
            if frame_ends in (None, frame.frame_type):
                first = frame
            if last is not None and attr(first) <= firstTime:
                break
                if last is not None and attr(first) <= firstTime:
                    break
        return first, last

    def copy_to_bounded(
            self, output, firstTime, lastTime,
            frame_ends=PiVideoFrameType.sps_header):
        """
        copy_to(output, firstTime, lastTime, first_frame=PiVideoFrameType.sps_header)
        Copies content from the stream to *output*.
        By default, this method copies all complete frames from the circular
        stream to the filename or file-like object given by *output*.
        If *size* is specified then the copy will be limited to the whole
        number of frames that fit within the specified number of bytes. If
        *seconds* if specified, then the copy will be limited to that number of
        seconds worth of frames. If *frames* is specified then the copy will
        be limited to that number of frames. Only one of *size*, *seconds*, or
        *frames* can be specified. If none is specified, all frames are copied.
        If *frame_ends* is specified, it defines the frame type of the first and last
        frame to be copied. By default this is
        :attr:`~PiVideoFrameType.sps_header` as this must usually be the first
        frame in an H264 stream. If *first_frame* is ``None``, not such limit
        will be applied.
        .. warning::
            Note that if a frame of the specified type (e.g. SPS header) cannot
            be found within the specified number of seconds, bytes, or frames,
            then this method will simply copy nothing (but no error will be
            raised).
        The stream's position is not affected by this method.
        """
        if isinstance(output, bytes):
            output = output.decode('utf-8')
        opened = isinstance(output, str)
        if opened:
            output = io.open(output, 'wb')
        try:
            with self.lock:

                first, last = self._find_bounded(firstTime,lastTime,frame_ends)
                # Copy chunk references into a holding buffer; this allows us
                # to release the lock on the stream quickly (in case recording
                # is on-going)
                chunks = []
                if first is not None and last is not None:
                    pos = 0
                    for buf, frame in self._data.iter_both(False):
                        if pos > last.position + last.frame_size:
                            break
                        elif pos >= first.position:
                            chunks.append(buf)
                        pos += len(buf)
            # Perform the actual I/O, copying chunks to the output
            for buf in chunks:
                output.write(buf)
            return first, last
        finally:
            if opened:
                output.close()
